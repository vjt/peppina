"""How long a program takes, as the machine itself estimates it.

hOn's command tree carries no duration: mainWashTime is the main wash only.
The machine reports one in remainingTimeMM, for the program set on its knob
while it waits and for a cycle as it starts; retrieve-last-activity keeps the
one of the last cycle. Measured 2026-10-11: ready again after a cycle it
reported 170 for Eco 40-60; the Smart cycle of that morning was estimated at
81 minutes when it started and took 81.5.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from .appliance import Appliance
from .programs import knob, program_codes, running_program

READY, RUNNING, PAUSED, ERROR, DONE = "1", "2", "3", "6", "7"
# A start Peppina sent explains a cycle that starts within this many seconds.
SENT_FOR = 600


def activity_duration(appliance: Appliance, activity: dict) -> dict | None:
    """What retrieve-last-activity kept of the last cycle, when its program
    code and knob position point at one program: the estimate at its start
    and how long it really took (activityStarted to activityEnded)."""
    attributes = activity.get("attributes") or {}
    found = program_codes(appliance, attributes.get("prCode"), attributes.get("prPosition"))
    reading = {
        "minutes": _minutes(attributes.get("remainingTimeMM")),
        "actual": _elapsed(activity.get("activityStarted"), _when(activity.get("activityEnded"))),
    }
    reading = {key: value for key, value in reading.items() if value}
    if len(found) != 1 or not reading:
        return None
    return {
        "program": found[0],
        **reading,
        "temp": attributes.get("temp"),
        "spin": attributes.get("spinSpeed"),
    }


class DurationWatch:
    """Reads the machine's estimates off its state, one update at a time.

    Waiting, the machine shows the duration of the program on its knob. When a
    cycle starts it shows that cycle's: the program is the one Peppina just
    sent, else the only one with that program code. Resuming a paused cycle,
    or a first look at a cycle already running, is not a start.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._clock = clock
        self._now = now
        self._mode: object = None
        self._sent: tuple[str, float] | None = None
        self._starting: str | None = None
        # The cycle on, for how long it really took when it ends.
        self._running: str | None = None

    def started(self, program: str) -> None:
        """Peppina sent a start for this program."""
        self._sent = (program, self._clock())

    def observe(self, appliance: Appliance) -> dict | None:
        """A reading {program, minutes, temp, spin} from the current state, or None."""
        mode = appliance.get("machMode")
        code = appliance.get("prCode")
        minutes = _minutes(appliance.get("remainingTimeMM"))
        previous, self._mode = self._mode, mode
        if mode in (RUNNING, PAUSED):
            self._running = running_program(appliance) or self._running
        if mode == DONE and previous in (RUNNING, PAUSED) and self._running:
            program, self._running = self._running, None
            # From the start of hOn's activity: Home Assistant may have
            # restarted since the cycle began.
            activity = appliance.context.get("activity") or {}
            actual = _elapsed(activity.get("activityStarted"), self._now())
            return _reading(appliance, program, actual, "actual") if actual else None
        if mode == READY:
            self._starting = None
            program = knob(appliance, program_codes(appliance, code))
            return _reading(appliance, program, minutes) if program and minutes else None
        if mode != RUNNING:
            self._starting = None
            return None
        if previous is not None and previous not in (RUNNING, PAUSED, ERROR):
            sent, self._sent = self._sent, None
            if sent and self._clock() - sent[1] < SENT_FOR:
                self._starting = sent[0]
            else:
                found = program_codes(appliance, code)
                self._starting = found[0] if len(found) == 1 else None
        # The first running update may still carry the old program's values.
        if self._starting and minutes and self._starting in program_codes(appliance, code):
            program, self._starting = self._starting, None
            return _reading(appliance, program, minutes)
        return None


def _reading(appliance: Appliance, program: str, minutes: int, kind: str = "minutes") -> dict:
    return {
        "program": program,
        kind: minutes,
        "temp": appliance.get("temp"),
        "spin": appliance.get("spinSpeed"),
    }


def _when(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed(start: object, end: datetime | None) -> int:
    """Whole minutes from an hOn timestamp to end; 0 if unknown or absurd."""
    begun = _when(start)
    if begun is None or end is None:
        return 0
    minutes = round((end - begun).total_seconds() / 60)
    return minutes if 0 < minutes < 24 * 60 else 0


def _minutes(value: object) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0
