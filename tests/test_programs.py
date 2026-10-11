"""Program catalog for the card, against real (trimmed) hOn data."""
import json
from pathlib import Path

import pytest

from hon import Appliance
from hon.programs import describe, dictionary_keys, extract, usage

FIXTURES = Path(__file__).parent / "fixtures"
COMMANDS = json.loads((FIXTURES / "commands.json").read_text())
DICTIONARY = json.loads((FIXTURES / "dictionary_it.json").read_text())
# Cycle counters per knob position, as the machine had them on 2026-10-11.
COUNTERS = {
    "program1": "192",
    "program2": "0",
    "program7": "4",
    "program8": "4",
    "program13": "38",
    "program18": "5",
}


@pytest.fixture
def washer():
    appliance = Appliance({"macAddress": "aa-bb-cc-dd-ee-ff", "applianceTypeId": 1})
    appliance.load_commands(COMMANDS)
    appliance.parameters = dict(COUNTERS)
    return appliance


@pytest.fixture
def texts(washer):
    return extract(DICTIONARY, dictionary_keys(washer))


def test_dictionary_keys(washer):
    keys = dictionary_keys(washer)
    assert len(keys) == 24 + 5
    assert {"PROGRAMS.WM_WD.HQD_COTTONS", "PROGRAMS.WM_WD.HQD_COTTONS_DESCRIPTION"} <= set(keys)
    # Primary clusters only: Smart lists eco then traditional, and so on.
    assert {k for k in keys if "CLUSTER" in k} == {
        f"GUIDED_WASHING.CLUSTER.{c}" for c in ("TRADITIONAL", "QUICK", "ECO", "STAINS", "HEALTH")
    }


def test_extract(texts):
    assert texts["PROGRAMS.WM_WD.HQD_COTTONS"] == "Cotone"
    assert texts["GUIDED_WASHING.CLUSTER.TRADITIONAL"] == "Tradizionali"
    assert extract(DICTIONARY, ["PROGRAMS.WM_WD.NOPE", "PROGRAMS", "NOPE.X"]) == {}


def test_usage_from_machine_counters(washer):
    counts = usage(washer, {})
    assert counts["hqd_smart"] == 192  # alone on position 1
    assert counts["hqd_eco_40_60_degrees"] == 38
    assert counts["hqd_cottons"] == 4  # the knob program of position 7
    assert counts["iot_wash_cotton"] == 0
    assert counts["hqd_babycare"] == 5


def test_usage_merges_own_starts(washer):
    # One of position 7's four cycles was the guided Cotone, started by Peppina.
    counts = usage(washer, {"iot_wash_cotton": 1})
    assert counts["iot_wash_cotton"] == 1
    assert counts["hqd_cottons"] == 3


def test_usage_never_counts_twice(washer):
    counts = usage(washer, {"hqd_cottons": 6})  # more than the machine counted
    assert counts["hqd_cottons"] == 6
    assert counts["iot_wash_cotton"] == 0


def test_usage_without_counters(washer):
    washer.parameters = {}
    assert usage(washer, {"hqd_smart": 2})["hqd_smart"] == 2


def test_describe(washer, texts):
    cotton = next(p for p in describe(washer, texts, {}) if p["key"] == "hqd_cottons")
    assert cotton == {
        "key": "hqd_cottons",
        "name": "Cotone",
        "description": DICTIONARY["PROGRAMS"]["WM_WD"]["HQD_COTTONS_DESCRIPTION"],
        "group": "traditional",
        "group_name": "Tradizionali",
        "tag": None,
        "load": 9.0,
        "temp": [0, 90],
        "spin": 1400,
        "usage": 4,
    }


def test_describe_order(washer, texts):
    assert [p["key"] for p in describe(washer, texts, {})] == [
        # Tradizionali, by name, the knob program first among namesakes
        "iot_wash_colored",
        "iot_wash_coloured",
        "hqd_cottons",
        "iot_wash_cotton",
        "hqd_synthetic_and_coloured",
        # Rapidi
        "hqd_quick_15",
        "iot_wash_rapid_14",
        # Eco
        "hqd_eco_40_60_degrees",
        "hqd_smart",
        # Macchie, Salute, then no cluster
        "iot_wash_wine_stains",
        "iot_wash_baby_sanitizer",
        "hqd_babycare",
    ]


def test_describe_tags_duplicate_names(washer, texts):
    tags = {p["key"]: p["tag"] for p in describe(washer, texts, {})}
    assert tags["hqd_cottons"] is None
    assert tags["iot_wash_cotton"] == "guided"
    assert tags["iot_wash_colored"] == "care"
    assert tags["iot_wash_coloured"] == "guided"
    assert tags["iot_wash_wine_stains"] is None


def test_describe_without_dictionary(washer):
    programs = {p["key"]: p for p in describe(washer, {}, {})}
    cotton = programs["hqd_cottons"]
    assert cotton["name"] == "Cottons"
    assert cotton["description"].startswith("Cycle designed")
    assert cotton["group_name"] == "Traditional"
    eco = programs["hqd_eco_40_60_degrees"]
    assert (eco["temp"], eco["spin"]) == ([40, 40], 1400)
