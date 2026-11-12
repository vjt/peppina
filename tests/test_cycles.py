"""Cycles from the machine's mode, live and from the recorder history."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hon.cycles import FINISHED, INTERRUPTED, KEEP_MAX, CycleWatch, from_history, keep

FIXTURES = Path(__file__).parent / "fixtures"
ROLES = {
    "sensor.peppina_mode": "mode",
    "sensor.peppina_program_name": "program",
    "sensor.peppina_temperature": "temp",
    "sensor.peppina_spin_speed": "spin",
    "sensor.peppina_last_cycle_end": "end",
}
T0 = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def run(watch: CycleWatch, looks: list[tuple]) -> list[dict]:
    """Feed (minutes, mode, program, temp, spin[, started]) looks; the records."""
    records = []
    for minutes, *look in looks:
        if record := watch.observe(at(minutes), *look):
            records.append(record)
    return records


@pytest.fixture
def watch():
    watch = CycleWatch()
    watch.observe(at(-10), "1")
    return watch


@pytest.fixture(scope="module")
def history():
    """The fixture as the integration hands it over: role -> [(when, state)]."""
    data = json.loads((FIXTURES / "history.json").read_text())["history"]
    return {
        ROLES[series[0]["entity_id"]]: [
            (datetime.fromisoformat(s["last_changed"]), s["state"]) for s in series
        ]
        for series in data
    }


def test_a_cycle_runs_to_done(watch):
    records = run(watch, [
        (0, "2", "hqd_smart", "40", "1200"),
        (30, "3", "hqd_smart", "40", "1200"),
        (35, "2", "hqd_smart", "40", "1200"),
        (91.5, "7", None, "40", "1200"),
        (93.5, "1", None, "40", "0"),
    ])
    assert records == [{
        "start": "2026-11-10T10:00:00+00:00",
        "end": "2026-11-10T11:31:30+00:00",
        "minutes": 92,
        "program": "hqd_smart",
        "outcome": FINISHED,
        "temp": 40,
        "spin": 1200,
    }]


def test_a_stop_interrupts(watch):
    # As in the history: four minutes of running, then ready.
    (record,) = run(watch, [(0, "2", "hqd_cottons", "30", "800"), (4, "1", None, "30", "0")])
    assert (record["outcome"], record["minutes"], record["spin"]) == (INTERRUPTED, 4, 800)


def test_an_error_carries_on(watch):
    # In error the spin sensor shows 0: the cycle keeps the one it ran with.
    records = run(watch, [
        (0, "2", "hqd_smart", "40", "1200"),
        (10, "6", None, "40", "0"),
        (12, "2", "hqd_smart", "40", "1200"),
        (60, "6", None, "40", "0"),
        (61, "7", None, "40", "0"),
    ])
    assert [(r["outcome"], r["minutes"], r["spin"]) for r in records] == [(FINISHED, 61, 1200)]


def test_an_error_alone_is_no_cycle(watch):
    assert run(watch, [(0, "6"), (5, "1"), (10, "7"), (12, "1")]) == []


def test_waiting_is_no_cycle(watch):
    # A delayed start waits in ready (Peppina's) or timer (the machine's):
    # the cycle starts when it runs.
    records = run(watch, [(0, "5", None), (60, "2", "hqd_smart"), (150, "7"), (152, "1")])
    assert [(r["start"], r["minutes"]) for r in records] == [("2026-11-10T11:00:00+00:00", 90)]
    assert run(watch, [(200, "5"), (260, "1")]) == []


def test_the_program_is_the_last_seen_running(watch):
    # As in the history: the old program for a second, then the one running; a
    # program named half an hour in; none at all.
    (flip,) = run(watch, [(0, "2", "hqd_smart"), (0.03, "2", "hqd_eco_40_60_degrees"), (157, "7")])
    (late,) = run(watch, [(200, "2", None), (227, "2", "hqd_synthetic_and_coloured"), (359, "7")])
    (none,) = run(watch, [(400, "2", None), (481, "7", None)])
    assert (flip["program"], late["program"], none["program"]) == (
        "hqd_eco_40_60_degrees", "hqd_synthetic_and_coloured", None)


def test_an_echo_after_done_is_no_cycle(watch):
    # As in the history: done, running again a second later with the old program,
    # ready two minutes after.
    records = run(watch, [
        (0, "2", "hqd_eco_40_60_degrees"),
        (161, "7", None),
        (161.016, "2", None),
        (161.017, "2", "hqd_eco_40_60_degrees"),
        (163, "1", None),
    ])
    assert [(r["outcome"], r["minutes"]) for r in records] == [(FINISHED, 161)]


def test_another_program_right_after_done_is_a_cycle(watch):
    records = run(watch, [(0, "2", "hqd_smart"), (90, "7"), (90.5, "2", "hqd_rinse"), (110, "7")])
    assert [r["program"] for r in records] == ["hqd_smart", "hqd_rinse"]


def test_a_cycle_already_running_starts_when_hon_says():
    # First look after a restart: the start is hOn's, or there is no record.
    watch = CycleWatch()
    records = run(watch, [
        (0, "2", "hqd_smart", "40", "1200", "2026-11-10T09:15:00Z"),
        (45, "7", None, "40", "1200", "2026-11-10T09:15:00Z"),
    ])
    assert [(r["start"], r["minutes"]) for r in records] == [("2026-11-10T09:15:00+00:00", 90)]
    blind = CycleWatch()
    assert run(blind, [(0, "2", "hqd_smart"), (45, "7")]) == []


def test_a_stale_hon_start_is_not_taken():
    # The activity of the cycle before, or one longer than a day.
    watch = CycleWatch()
    watch.last_end = at(-60)
    assert run(watch, [(0, "3", "hqd_smart", None, None, at(-90)), (40, "7")]) == []
    watch = CycleWatch()
    assert run(watch, [(0, "2", "hqd_smart", None, None, at(-25 * 60)), (40, "7")]) == []


def test_a_restart_in_the_middle_carries_on(watch):
    records = run(watch, [
        (0, "2", "hqd_smart"),
        (30, None),
        (30.2, "2", "hqd_smart"),
        (90, "7"),
    ])
    assert [r["minutes"] for r in records] == [90]


def test_unseen_with_an_end_reported():
    # As in the history: unavailable for two hours mid-cycle; when it came back,
    # ready, and the last cycle end said when it finished.
    watch = CycleWatch([at(-600), at(115)])
    watch.observe(at(-10), "1")
    records = run(watch, [(0, "2", "iot_wash_bed_linen", "60", "1000"), (20, None), (127, "1")])
    assert [(r["end"], r["minutes"], r["outcome"]) for r in records] == [
        ("2026-11-10T11:55:00+00:00", 115, FINISHED)]


def test_unseen_and_back_running(watch):
    # The same program: the same cycle. Another one: neither cycle was seen whole.
    same = run(watch, [(0, "2", "hqd_smart"), (20, None), (60, "2", "hqd_smart"), (90, "7")])
    assert [r["minutes"] for r in same] == [90]
    other = run(watch, [(100, "1"), (110, "2", "hqd_smart"), (120, None), (200, "2", "hqd_rinse"),
                        (230, "7")])
    assert other == []


def test_unseen_and_back_done_or_ready(watch):
    # Done lasts a minute or two: it ended about then. Ready says nothing.
    done = run(watch, [(0, "2", "hqd_smart"), (20, None), (91, "7"), (93, "1")])
    assert [(r["minutes"], r["outcome"]) for r in done] == [(91, FINISHED)]
    assert run(watch, [(100, "2", "hqd_smart"), (120, None), (200, "1")]) == []


def test_the_history_of_six_weeks(history):
    cycles = from_history(history)
    assert len(cycles) == 30
    assert [c["outcome"] for c in cycles].count(INTERRUPTED) == 1
    assert cycles[0] == {
        "start": "2025-08-27T20:10:25+00:00",
        "end": "2025-08-27T22:49:21+00:00",
        "minutes": 159,
        "program": "hqd_eco_40_60_degrees",
        "outcome": FINISHED,
        "temp": 40,
        "spin": 1400,
    }
    by_start = {c["start"]: c for c in cycles}
    # Stopped after four minutes.
    assert by_start["2025-09-06T13:46:47+00:00"]["outcome"] == INTERRUPTED
    # Named half an hour in.
    assert by_start["2025-09-06T16:46:04+00:00"]["program"] == "hqd_synthetic_and_coloured"
    # Started as the program set before.
    assert by_start["2025-09-10T19:58:59+00:00"]["program"] == "hqd_eco_40_60_degrees"
    # The echo after this one is not a cycle.
    assert by_start["2025-09-19T12:25:50+00:00"]["end"] == "2025-09-19T15:06:52+00:00"
    assert not [c for c in cycles if "2025-09-19T15:06" <= c["start"] <= "2025-09-19T16"]
    # Two hours unavailable, the end from the last cycle end sensor.
    gap = by_start["2025-10-05T20:43:46+00:00"]
    assert (gap["end"], gap["minutes"], gap["outcome"]) == ("2025-10-05T22:38:41+00:00", 115, FINISHED)
    # Still running when the history ends: not over yet, no record.
    assert cycles[-1]["start"] == "2025-10-06T16:12:03+00:00"


def test_the_history_without_the_end_sensor(history):
    # Before Peppina kept the last cycle end, the two hours in the dark
    # cannot say how that cycle went.
    cycles = from_history({role: states for role, states in history.items() if role != "end"})
    assert len(cycles) == 29
    assert "2025-10-05T20:43:46+00:00" not in {c["start"] for c in cycles}


def test_a_window_that_opens_mid_cycle(history):
    # The recorder gives the state at the start of the window: a cycle
    # already running then has no start.
    start = datetime(2025, 9, 6, 17, 0, tzinfo=timezone.utc)
    cut = {}
    for role, states in history.items():
        before = [state for when, state in states if when <= start][-1:]
        cut[role] = [(start, state) for state in before] + [(w, s) for w, s in states if w > start]
    cycles = from_history(cut)
    assert cycles[0]["start"] == "2025-09-07T19:03:04+00:00"


def test_keep_merges_once(history):
    cycles = from_history(history)
    now = datetime(2025, 10, 7, tzinfo=timezone.utc)
    kept = keep([], cycles, now)
    assert kept == cycles
    assert keep(kept, from_history(history), now) == kept
    # A live record of a cycle the history also has, seconds apart: one cycle.
    live = {**cycles[5], "start": "2025-09-04T12:03:50+00:00"}
    assert keep(kept, [live], now) == kept
    newer = {**cycles[-1], "start": "2025-10-07T08:00:00+00:00", "end": "2025-10-07T09:30:00+00:00"}
    assert keep(kept, [newer], now)[-1] == newer
    older = {**cycles[0], "start": "2025-08-01T08:00:00+00:00", "end": "2025-08-01T09:30:00+00:00"}
    assert keep(kept, [older], now)[0] == older


def test_keep_bounds():
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    old = {"start": "2025-11-10T08:00:00+00:00", "end": "2025-11-10T09:00:00+00:00"}
    recent = {"start": "2025-11-14T08:00:00+00:00", "end": "2025-11-14T09:00:00+00:00"}
    assert keep([old, recent], [], now) == [recent]
    many = [
        {"start": (now - timedelta(hours=3 * i)).isoformat(), "end": (now - timedelta(hours=3 * i - 1)).isoformat()}
        for i in range(1, KEEP_MAX + 51)
    ]
    kept = keep([], many, now)
    assert len(kept) == KEEP_MAX
    assert kept[-1] == many[0] and kept[0] == many[KEEP_MAX - 1]
    assert keep([], [{"start": "nope", "end": None}], now) == []
