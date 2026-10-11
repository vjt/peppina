"""What a cycle consumed, and what the machine consumed in its life.

hOn reports currentWaterUsed (litres) and currentElectricityUsed (kWh) for
the cycle under way, and totalWaterUsed, totalElectricityUsed and
totalWashCycle for the machine's life, in the context and in its pushes.
Measured 2026-10-11 (tests/fixtures/push_events.json): when the Smart cycle
ended (mode 7) the current values still held its 52 L and 0.77 kWh; two
minutes later, ready again (mode 1), the machine set them to 0.
"""
from __future__ import annotations

from .appliance import Appliance

# machMode while a cycle runs, is paused or has just ended: the current
# values are that cycle's.
CYCLE_MODES = {"2", "3", "7"}


def number(appliance: Appliance, key: str) -> int | float | None:
    """A figure as hOn sends it ("52", "0.70"); whole numbers as int, so a
    template says 52 litres, not 52.0."""
    try:
        value = float(appliance.get(key))
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def total(appliance: Appliance, key: str) -> int | float | None:
    """A life counter, None rather than 0: Home Assistant would take a drop
    to 0 for a new meter and count the machine's whole life again once the
    real figure came back."""
    return number(appliance, key) or None


class CycleConsumption:
    """Water (litres) and energy (kWh) of the cycle under way, else of the
    last one: kept when the machine zeroes them after the cycle, until the
    next cycle starts."""

    def __init__(self, water: int | float | None = None, energy: int | float | None = None) -> None:
        self.water = water
        self.energy = energy

    def observe(self, appliance: Appliance) -> bool:
        """Take in the machine's state; True if a figure changed."""
        if appliance.get("machMode") not in CYCLE_MODES:
            return False
        changed = False
        for attr, key in (("water", "currentWaterUsed"), ("energy", "currentElectricityUsed")):
            value = number(appliance, key)
            if value is not None and value != getattr(self, attr):
                setattr(self, attr, value)
                changed = True
        return changed
