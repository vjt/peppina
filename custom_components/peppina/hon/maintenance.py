"""Maintenance counters: filter, drum and detergent drawer.

hOn's maintenance-cycle answers, per counter, `count` out of `tot` with
`remaining` and `percentage` (measured 2026-11-01 on a Haier washer: 44 of
100 for the filter and the drawer, 43 for the drum). The maintenance cycles
run on the machine restart `count`; the hOn app's own "done" is not used.
Peppina's *done* keeps a local offset instead: the count when it was pressed,
dropped as soon as the machine restarts the count by itself.
"""
from __future__ import annotations

from dataclasses import dataclass

# Peppina's key -> hOn's.
COUNTERS = {
    "filter_cleaning": "filterCleaning",
    "drum_cleaning": "drumCleaning",
    "drawer_cleaning": "drawerCleaning",
}
DRUM = "drum_cleaning"
# Programs that clean the drum: their end counts as the drum done.
DRUM_PROGRAMS = ("hqd_autoclean", "iot_wash_quick_drum_cleaner")
# Due once this few cycles are left. A guess: when the machine or the app
# would first warn was never seen; 0 is count reaching tot.
DUE_REMAINING = 0


@dataclass(frozen=True)
class Counter:
    tot: int
    count: int

    @classmethod
    def parse(cls, data: object) -> Counter | None:
        try:
            tot, count = int(data["tot"]), int(data["count"])
        except (KeyError, TypeError, ValueError):
            return None
        return cls(tot, count) if tot > 0 and count >= 0 else None


def counters(payload: dict) -> dict[str, Counter]:
    """The counters a maintenance-cycle payload carries, by Peppina's key."""
    found = {key: Counter.parse(payload.get(name)) for key, name in COUNTERS.items()}
    return {key: counter for key, counter in found.items() if counter}


class Maintenance:
    """The machine's counters, read against the offsets *done* left."""

    def __init__(self) -> None:
        self.counters: dict[str, Counter] = {}
        # Machine count when *done* was pressed, by key.
        self.offsets: dict[str, int] = {}

    def load(self, payload: dict) -> None:
        self.counters.update(counters(payload))
        self._drop_reset()

    def restore(self, key: str, offset: int) -> None:
        self.offsets[key] = offset
        self._drop_reset()

    def _drop_reset(self) -> None:
        """A count below its offset was restarted by the machine: the offset
        has nothing left to correct."""
        for key, offset in list(self.offsets.items()):
            counter = self.counters.get(key)
            if counter is not None and counter.count < offset:
                del self.offsets[key]

    def done(self, key: str) -> bool:
        """Cleaned now; False if hOn has not given this counter yet."""
        counter = self.counters.get(key)
        if counter is None:
            return False
        self.offsets[key] = counter.count
        return True

    def count(self, key: str) -> int | None:
        """Cycles since the last cleaning, the machine's or Peppina's."""
        counter = self.counters.get(key)
        if counter is None:
            return None
        return counter.count - self.offsets.get(key, 0)

    def remaining(self, key: str) -> int | None:
        count = self.count(key)
        return None if count is None else self.counters[key].tot - count

    def percentage(self, key: str) -> int | None:
        count = self.count(key)
        return None if count is None else round(100 * count / self.counters[key].tot)

    def due(self, key: str) -> bool | None:
        remaining = self.remaining(key)
        return None if remaining is None else remaining <= DUE_REMAINING
