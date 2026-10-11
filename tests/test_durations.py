"""The machine's own duration estimates, against real (trimmed) hOn data."""
import json
from pathlib import Path

import pytest

from hon import Appliance
from hon.durations import DurationWatch, activity_duration

FIXTURES = Path(__file__).parent / "fixtures"
COMMANDS = json.loads((FIXTURES / "commands.json").read_text())


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def washer():
    appliance = Appliance({"macAddress": "aa-bb-cc-dd-ee-ff", "applianceTypeId": 1})
    appliance.load_commands(COMMANDS)
    return appliance


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def watch(clock):
    return DurationWatch(clock)


def shadow(appliance, **parameters):
    appliance.parameters = {"temp": "40", "spinSpeed": "1400", **parameters}
    return appliance


def test_idle_machine_shows_the_knob_program(washer, watch):
    # As on 2026-10-11 after the cycle: ready, Eco 40-60 on the knob, 170'.
    seen = watch.observe(shadow(washer, machMode="1", prCode="136", remainingTimeMM="170"))
    assert seen == {"program": "hqd_eco_40_60_degrees", "minutes": 170, "temp": "40", "spin": "1400"}


def test_idle_shared_code_means_the_knob_program(washer, watch):
    # prCode 115 is Cotone on the knob and the guided Cotone: idle, it is the knob.
    seen = watch.observe(shadow(washer, machMode="1", prCode="115", remainingTimeMM="95"))
    assert seen["program"] == "hqd_cottons"


def test_idle_without_time_says_nothing(washer, watch):
    assert watch.observe(shadow(washer, machMode="1", prCode="136", remainingTimeMM="0")) is None
    assert watch.observe(shadow(washer, machMode="1", prCode="999", remainingTimeMM="50")) is None


def test_start_sent_by_peppina(washer, watch):
    watch.observe(shadow(washer, machMode="1", prCode="136", remainingTimeMM="170"))
    watch.started("iot_wash_cotton")
    seen = watch.observe(shadow(washer, machMode="2", prCode="115", remainingTimeMM="95"))
    assert seen == {"program": "iot_wash_cotton", "minutes": 95, "temp": "40", "spin": "1400"}
    # Only once: the countdown that follows is not an estimate.
    assert watch.observe(shadow(washer, machMode="2", prCode="115", remainingTimeMM="94")) is None


def test_start_waits_for_the_program_to_show(washer, watch):
    # The first running update may still carry the idle program's values.
    watch.observe(shadow(washer, machMode="1", prCode="136", remainingTimeMM="170"))
    watch.started("iot_wash_cotton")
    assert watch.observe(shadow(washer, machMode="2", prCode="136", remainingTimeMM="170")) is None
    seen = watch.observe(shadow(washer, machMode="2", prCode="115", remainingTimeMM="95"))
    assert (seen["program"], seen["minutes"]) == ("iot_wash_cotton", 95)


def test_start_from_elsewhere_needs_an_unambiguous_code(washer, watch):
    watch.observe(shadow(washer, machMode="1", prCode="136", remainingTimeMM="170"))
    assert watch.observe(shadow(washer, machMode="2", prCode="115", remainingTimeMM="95")) is None
    watch.observe(shadow(washer, machMode="1", prCode="124", remainingTimeMM="81"))
    seen = watch.observe(shadow(washer, machMode="2", prCode="124", remainingTimeMM="81"))
    assert seen["program"] == "hqd_smart"


def test_an_old_start_explains_nothing(washer, watch, clock):
    watch.observe(shadow(washer, machMode="1", prCode="136", remainingTimeMM="170"))
    watch.started("iot_wash_cotton")
    clock.now += 3600
    assert watch.observe(shadow(washer, machMode="2", prCode="115", remainingTimeMM="95")) is None


def test_resume_and_restart_mid_cycle_are_not_starts(washer, watch):
    # Home Assistant restarting mid-cycle: the first look is already running.
    assert watch.observe(shadow(washer, machMode="2", prCode="124", remainingTimeMM="40")) is None
    watch.observe(shadow(washer, machMode="3", prCode="124", remainingTimeMM="40"))
    assert watch.observe(shadow(washer, machMode="2", prCode="124", remainingTimeMM="40")) is None


def test_last_activity(washer):
    # retrieve-last-activity on 2026-10-11: the Smart cycle, 81' at its start,
    # 81.5 in fact (08:55:19 to 10:16:46).
    attributes = {"prCode": "124", "prPosition": "1", "remainingTimeMM": "81", "temp": "40",
                  "spinSpeed": "1200"}
    activity = {"attributes": attributes, "activityStarted": "2026-10-11T08:55:19Z",
                "activityEnded": "2026-10-11T10:16:46Z"}
    assert activity_duration(washer, activity) == {
        "program": "hqd_smart", "minutes": 81, "actual": 81, "temp": "40", "spin": "1200",
    }
    no_end = {"attributes": attributes, "activityStarted": "2026-10-11T08:55:19Z"}
    assert "actual" not in activity_duration(washer, no_end)
    other = {**activity, "attributes": {**attributes, "prCode": "115", "prPosition": "7"}}
    assert activity_duration(washer, other) is None
    assert activity_duration(washer, {}) is None


def test_real_duration_at_the_end(washer, clock):
    from datetime import datetime, timezone

    end = datetime(2026, 10, 11, 10, 16, 46, tzinfo=timezone.utc)
    watch = DurationWatch(clock, now=lambda: end)
    washer.context = {"activity": {"activityStarted": "2026-10-11T08:55:19Z"}}
    watch.observe(shadow(washer, machMode="1", prCode="124", remainingTimeMM="81"))
    watch.observe(shadow(washer, machMode="2", prCode="124", remainingTimeMM="81"))
    watch.observe(shadow(washer, machMode="2", prCode="124", remainingTimeMM="3"))
    seen = watch.observe(shadow(washer, machMode="7", prCode="124", remainingTimeMM="0"))
    assert seen == {"program": "hqd_smart", "actual": 81, "temp": "40", "spin": "1400"}
    # Ending again without a cycle in between says nothing.
    assert watch.observe(shadow(washer, machMode="7", prCode="124")) is None
    # A cycle whose activity hOn did not report has no real duration.
    washer.context = {}
    watch.observe(shadow(washer, machMode="2", prCode="124", remainingTimeMM="50"))
    assert watch.observe(shadow(washer, machMode="7", prCode="124")) is None
