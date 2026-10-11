"""Water and energy, per cycle and over the machine's life, against the push
events of a real Smart cycle (tests/fixtures/push_events.json)."""
import json
from pathlib import Path

import pytest

from hon import Appliance
from hon.consumption import CycleConsumption, number, total

FIXTURES = Path(__file__).parent / "fixtures"
EVENTS = json.loads((FIXTURES / "push_events.json").read_text())
MAC = "aa-bb-cc-dd-ee-ff"
STATUS = f"haier/things/{MAC}/event/appliancestatus/update"


def status(**params):
    return {"parameters": [{"parName": k, "parOldVal": None, "parNewVal": v} for k, v in params.items()]}


@pytest.fixture
def washer():
    appliance = Appliance({"macAddress": MAC, "applianceTypeId": 1})
    # The state before the first event: each parameter's first old value.
    for event in EVENTS:
        for change in (event["payload"].get("parameters") or []):
            appliance.parameters.setdefault(change["parName"], change["parOldVal"])
    appliance.parameters["machMode"] = "2"
    return appliance


def replay(appliance, consumption, until=None):
    """Feed the events up to the one received at `until`; what was seen at
    each mode."""
    seen = {}
    for event in EVENTS:
        appliance.load_event(event["topic"], event["payload"])
        consumption.observe(appliance)
        seen[appliance.get("machMode")] = (consumption.water, consumption.energy)
        if event["received"] == until:
            break
    return seen


def test_the_cycle_figures_follow_the_cycle(washer):
    consumption = CycleConsumption()
    replay(washer, consumption, until="11:52:13.269")
    assert (consumption.water, consumption.energy) == (27, 0.69)


def test_the_cycle_figures_are_there_when_it_ends(washer):
    consumption = CycleConsumption()
    seen = replay(washer, consumption, until="12:16:46.687")
    assert washer.get("machMode") == "7"
    assert seen["7"] == (52, 0.77)


def test_the_cycle_figures_outlive_the_machine_zeroing_them(washer):
    consumption = CycleConsumption()
    replay(washer, consumption)
    # Ready again, the machine says 0 L and 0 kWh: the last cycle stays.
    assert washer.get("machMode") == "1"
    assert washer.get("currentWaterUsed") == "0"
    assert (consumption.water, consumption.energy) == (52, 0.77)


def test_a_new_cycle_starts_from_zero(washer):
    consumption = CycleConsumption()
    replay(washer, consumption)
    washer.load_event(STATUS, status(machMode="2"))
    assert consumption.observe(washer)
    assert (consumption.water, consumption.energy) == (0, 0)
    washer.load_event(STATUS, status(currentElectricityUsed="0.03", currentWaterUsed="2"))
    consumption.observe(washer)
    assert (consumption.water, consumption.energy) == (2, 0.03)


def test_waiting_or_paused(washer):
    consumption = CycleConsumption(water=52, energy=0.77)
    washer.parameters.update(machMode="5", currentWaterUsed="0", currentElectricityUsed="0.00")
    assert not consumption.observe(washer)  # a timer waiting: still the last cycle
    assert (consumption.water, consumption.energy) == (52, 0.77)
    washer.parameters.update(machMode="3", currentWaterUsed="12", currentElectricityUsed="0.30")
    assert consumption.observe(washer)  # paused mid-cycle: this cycle's
    assert (consumption.water, consumption.energy) == (12, 0.3)
    assert not consumption.observe(washer)


def test_a_machine_that_does_not_report_keeps_what_was_known():
    appliance = Appliance({"macAddress": MAC, "applianceTypeId": 1})
    appliance.parameters = {"machMode": "2"}
    consumption = CycleConsumption(water=52, energy=0.77)
    assert not consumption.observe(appliance)
    assert (consumption.water, consumption.energy) == (52, 0.77)


def test_totals_after_the_cycle(washer):
    replay(washer, CycleConsumption())
    assert total(washer, "totalWaterUsed") == 19771
    assert total(washer, "totalElectricityUsed") == 241.48
    assert total(washer, "totalWashCycle") == 308


def test_a_total_of_zero_is_no_total():
    # Home Assistant would take a drop to 0 for a new meter, and count the
    # whole life of the machine again once the real figure comes back.
    appliance = Appliance({"macAddress": MAC, "applianceTypeId": 1})
    appliance.parameters = {"totalWaterUsed": "0", "totalElectricityUsed": "0.00"}
    assert total(appliance, "totalWaterUsed") is None
    assert total(appliance, "totalElectricityUsed") is None
    assert total(appliance, "totalWashCycle") is None


def test_numbers_read_as_hon_sends_them():
    appliance = Appliance({"macAddress": MAC, "applianceTypeId": 1})
    appliance.parameters = {"a": "52", "b": "0.70", "c": "1.00", "d": "", "e": "n/a"}
    assert [number(appliance, k) for k in "abcdef"] == [52, 0.7, 1, None, None, None]
    assert isinstance(number(appliance, "a"), int)
