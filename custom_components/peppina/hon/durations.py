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
from typing import Callable

from .appliance import Appliance
from .programs import knob, program_codes

READY, RUNNING, PAUSED, ERROR = "1", "2", "3", "6"
# A start Peppina sent explains a cycle that starts within this many seconds.
SENT_FOR = 600


def activity_duration(appliance: Appliance, activity: dict) -> dict | None:
    """The estimate retrieve-last-activity kept for the last cycle, when its
    program code and knob position point at one program."""
    found = program_codes(appliance, activity.get("prCode"), activity.get("prPosition"))
    minutes = _minutes(activity.get("remainingTimeMM"))
    if len(found) != 1 or not minutes:
        return None
    return {
        "program": found[0],
        "minutes": minutes,
        "temp": activity.get("temp"),
        "spin": activity.get("spinSpeed"),
    }


class DurationWatch:
    """Reads the machine's estimates off its state, one update at a time.

    Waiting, the machine shows the duration of the program on its knob. When a
    cycle starts it shows that cycle's: the program is the one Peppina just
    sent, else the only one with that program code. Resuming a paused cycle,
    or a first look at a cycle already running, is not a start.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._mode: object = None
        self._sent: tuple[str, float] | None = None
        self._starting: str | None = None

    def started(self, program: str) -> None:
        """Peppina sent a start for this program."""
        self._sent = (program, self._clock())

    def observe(self, appliance: Appliance) -> dict | None:
        """A reading {program, minutes, temp, spin} from the current state, or None."""
        mode = appliance.get("machMode")
        code = appliance.get("prCode")
        minutes = _minutes(appliance.get("remainingTimeMM"))
        previous, self._mode = self._mode, mode
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


def _reading(appliance: Appliance, program: str, minutes: int) -> dict:
    return {
        "program": program,
        "minutes": minutes,
        "temp": appliance.get("temp"),
        "spin": appliance.get("spinSpeed"),
    }


def _minutes(value: object) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0
