"""The washer's cycles, one record each: program, start, end, how long it
really took and whether it finished or was interrupted.

A cycle is what machMode says, as for the durations (durations.py): it starts
when the machine runs (2, or 3 when first seen paused) and ends at done (7,
finished) or back at ready (1, interrupted: a stop). The power state says
nothing: the status stays on for hours while the machine only waits for a
delayed start, and flaps off in the middle of cycles.

The same watch reads the machine live and, once, the recorder history of
Peppina's own sensors. Six weeks of that history (tests/fixtures/history.json)
show what a reading has to put up with:
- a cycle that just finished can come back as running for a second, with the
  phase and program it had before, then go to ready: running again right
  after done, on the same program, is that echo and not a cycle;
- the first running state may carry the program set before, with the right
  one seconds later, or no program for the first half hour: the program is
  the last one seen while running;
- the sensors go unavailable for seconds while Home Assistant restarts, and
  once for two hours in the middle of a cycle, whose end the last cycle end
  sensor gave when they came back.
Where the history cannot tell how a cycle went, it gets no record.
"""
from __future__ import annotations

import bisect
from datetime import datetime, timedelta

from .durations import DONE, ERROR, PAUSED, READY, RUNNING, _when

FINISHED, INTERRUPTED = "finished", "interrupted"
# machMode while a cycle is on; a cycle starts on the first two only.
ON = (RUNNING, PAUSED, ERROR)
STARTS = (RUNNING, PAUSED)
# Running again this soon after done (seconds) is the old state replayed.
ECHO = 60
# Unseen this long (seconds), the machine may have done anything meanwhile.
BLINK = 60
# Two records that start this close (seconds) are the same cycle.
SAME = 120
# No cycle takes longer.
LONGEST = timedelta(hours=24)
# What the log keeps: a year, the recorder's longest retention, and at most
# this many cycles.
KEEP = timedelta(days=365)
KEEP_MAX = 1000
# The program_name sensor without a program.
NO_PROGRAM = "No program"
UNKNOWN = (None, "unavailable", "unknown")


class CycleWatch:
    """Turns looks at the machine into cycles, a record as each one ends.

    ends: when cycles ended, as hOn reported them (the last cycle end
    sensor), for a cycle that went on while the machine was unseen.
    """

    def __init__(self, ends: list[datetime] | None = None) -> None:
        self._ends = sorted(ends or [])
        self._seen = False
        self._cycle: dict | None = None
        # Since when the machine is unseen, while it is.
        self._unseen: datetime | None = None
        # When the last cycle finished and its program, until ready.
        self._done: tuple[datetime, str | None] | None = None
        self._echo = False
        # When the last cycle ended, recorded or not.
        self.last_end: datetime | None = None

    def observe(
        self,
        when: datetime,
        mode: str | None,
        program: str | None = None,
        temp: object = None,
        spin: object = None,
        started: object = None,
    ) -> dict | None:
        """One look: machMode (None when unknown), the running program and its
        settings, and hOn's start of the activity when known. The record of
        the cycle that just ended, else None."""
        if mode in UNKNOWN:
            self._unseen = self._unseen or when
            return None
        mode = str(mode)
        first, self._seen = not self._seen, True
        unseen, self._unseen = self._unseen, None
        record = None
        dark = unseen is not None and (when - unseen).total_seconds() > BLINK
        if self._cycle and dark:
            record = self._after_dark(unseen, when, mode, program)
            first = self._cycle is None
        if mode in ON:
            self._running(when, mode, program, temp, spin, _when(started), first)
            return record
        self._echo = False
        if mode == DONE:
            if self._cycle:
                program = self._cycle["program"]
                record = self._close(when, FINISHED)
            self._done = (when, program)
        elif mode == READY:
            self._done = None
            if self._cycle:
                record = self._close(when, INTERRUPTED)
        return record

    def _running(self, when, mode, program, temp, spin, started, first) -> None:
        if self._cycle is None:
            if self._echo or mode not in STARTS:
                return
            if self._done and (when - self._done[0]).total_seconds() <= ECHO and (
                program in (None, self._done[1])
            ):
                self._echo = True
                return
            # Seen already running, the cycle started before: only hOn knows when.
            self._cycle = {"seen": when, "blind": first, "program": None, "temp": None, "spin": None}
        cycle = self._cycle
        cycle["program"] = program or cycle["program"]
        if started is not None:
            cycle["started"] = started
        if mode in STARTS:
            # In error the sensors show the spin as 0.
            for key, value in (("temp", temp), ("spin", spin)):
                if (number := _number(value)) is not None:
                    cycle[key] = number

    def _after_dark(self, unseen: datetime, when: datetime, mode: str, program) -> dict | None:
        """How the cycle went while the machine was unseen: the end hOn
        reported for it, else on if it still runs the same program, else
        finished if it is done (done lasts a minute or two), else unknown."""
        cycle = self._cycle
        since = max(cycle["seen"], unseen - timedelta(seconds=SAME))
        end = next((e for e in reversed(self._ends) if since < e <= when), None)
        if end is not None:
            return self._close(end, FINISHED)
        if mode == DONE or (mode in ON and program in (None, cycle["program"])):
            return None
        # Ready with no end reported, or running another program: the cycle
        # ended unseen, finished or not.
        self._cycle = None
        return None

    def _close(self, end: datetime, outcome: str) -> dict | None:
        cycle, self._cycle = self._cycle, None
        previous, self.last_end = self.last_end, end
        start = cycle["seen"]
        if cycle["blind"]:
            start = cycle.get("started")
            if (
                start is None
                or start > cycle["seen"] + timedelta(seconds=SAME)
                or cycle["seen"] - start > LONGEST
                or (previous is not None and start <= previous)
            ):
                return None
        if not start < end:
            return None
        return {
            "start": _iso(start),
            "end": _iso(end),
            "minutes": round((end - start).total_seconds() / 60),
            "program": cycle["program"],
            "outcome": outcome,
            "temp": cycle["temp"],
            "spin": cycle["spin"],
        }


def from_history(history: dict[str, list[tuple[datetime, str | None]]]) -> list[dict]:
    """The cycles in the recorder history of the washer's sensors, oldest
    first. history: role -> [(when, state)], for the roles mode, program
    (program_name), temp, spin and end (last_cycle_end)."""
    ends = {_when(value) for _, value in history.get("end", []) if value not in UNKNOWN}
    watch = CycleWatch([end for end in ends if end is not None])
    events = [
        (when, role, value)
        for role in ("mode", "program", "temp", "spin")
        for when, value in history.get(role, [])
    ]
    # Stable: at the same instant, the mode comes first.
    events.sort(key=lambda event: event[0])
    now: dict[str, str | None] = {}
    cycles = []
    for when, role, value in events:
        now[role] = None if value in UNKNOWN else value
        program = now.get("program")
        record = watch.observe(
            when,
            now.get("mode"),
            None if program == NO_PROGRAM else program,
            now.get("temp"),
            now.get("spin"),
        )
        if record:
            cycles.append(record)
    return cycles


def keep(records: list[dict], new: list[dict], now: datetime) -> list[dict]:
    """The records plus the new ones not among them yet, oldest first: those
    that ended within KEEP of now, at most KEEP_MAX."""
    kept = sorted(_dated(records, now), key=lambda pair: pair[0])
    starts = [start for start, _ in kept]
    for start, record in _dated(new, now):
        i = bisect.bisect(starts, start)
        if (i and (start - starts[i - 1]).total_seconds() <= SAME) or (
            i < len(starts) and (starts[i] - start).total_seconds() <= SAME
        ):
            continue
        starts.insert(i, start)
        kept.insert(i, (start, record))
    return [record for _, record in kept][-KEEP_MAX:]


def _dated(records: list[dict], now: datetime) -> list[tuple[datetime, dict]]:
    """(start, record) for the records that ended within KEEP of now."""
    dated = []
    for record in records:
        start, end = _when(record.get("start")), _when(record.get("end"))
        if start is not None and end is not None and now - end <= KEEP:
            dated.append((start, record))
    return dated


def _number(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")
