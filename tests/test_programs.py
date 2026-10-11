"""Program catalog for the card, against real (trimmed) hOn data."""
import json
from pathlib import Path

import pytest

from hon import Appliance
from hon.appliance import Parameter
from hon.programs import describe, dictionary_keys, extract, running_program, usage

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
        "duration": None,
    }


def test_describe_durations(washer, texts):
    measured = {"hqd_eco_40_60_degrees": {"minutes": 170, "temp": "40", "spin": "1400"}}
    programs = {p["key"]: p for p in describe(washer, texts, {}, measured)}
    assert programs["hqd_eco_40_60_degrees"]["duration"] == {"minutes": 170, "temp": "40", "spin": "1400"}
    assert programs["hqd_cottons"]["duration"] is None  # never estimated: nothing


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


def program(cluster="traditional", families=("download",), position="2", load=None, **extra):
    """One synthetic program for the edge cases real data does not have."""
    enum = lambda values: {"typology": "enum", "enumValues": list(values)}  # noqa: E731
    ancillary = {
        "programCluster": enum([cluster]),
        "programFamily": enum(families),
        "prPosition": {"typology": "fixed", "fixedValue": position},
    }
    if load is not None:
        ancillary["suggestedLoadW"] = load
    return {"parameters": {}, "ancillaryParameters": ancillary, **extra}


def appliance_with(programs, **parameters):
    appliance = Appliance({"macAddress": "aa-bb-cc-dd-ee-ff", "applianceTypeId": 1})
    appliance.load_commands(
        {
            "applianceModel": {"options": {}},
            "startProgram": {f"PROGRAMS.WM_WD.{key.upper()}": p for key, p in programs.items()},
            "stopProgram": {"parameters": {}},
        }
    )
    appliance.parameters = parameters
    return appliance


def test_odd_values_never_break_the_catalog():
    appliance = appliance_with(
        {
            "iot_wash_comma": program(load={"typology": "fixed", "fixedValue": "4,5"}),
            "iot_wash_empty": program(load={"typology": "fixed"}),
            "iot_wash_junk": program(load={"typology": "fixed", "fixedValue": "lots"}),
        }
    )
    loads = {p["key"]: p["load"] for p in describe(appliance, {}, {})}
    assert loads == {"iot_wash_comma": 4.5, "iot_wash_empty": None, "iot_wash_junk": None}


def test_names_in_other_scripts_keep_their_letters():
    appliance = appliance_with({"hqd_a": program(families=("dashboard",)), "iot_wash_b": program()})
    texts = {"PROGRAMS.WM_WD.HQD_A": "Хлопок", "PROGRAMS.WM_WD.IOT_WASH_B": "Синтетика"}
    programs = describe(appliance, texts, {})
    assert [p["name"] for p in programs] == ["Синтетика", "Хлопок"]
    assert all(p["tag"] is None for p in programs)  # different names: no tags


def test_voice_namesakes_read_as_guided():
    appliance = appliance_with(
        {"hqd_mix": program(families=("dashboard",)), "iot_wash_mix": program(families=("voice",))}
    )
    tags = {p["key"]: p["tag"] for p in describe(appliance, {"PROGRAMS.WM_WD.HQD_MIX": "Misti",
                                                            "PROGRAMS.WM_WD.IOT_WASH_MIX": "Misti"}, {})}
    assert tags == {"hqd_mix": None, "iot_wash_mix": "guided"}


def test_knob_program_by_family_first():
    # Two hqd_ programs on one position: the one on the knob (dashboard) takes
    # the machine's count. Counters may come as "7.0".
    appliance = appliance_with(
        {"hqd_knob": program(families=("dashboard",)), "hqd_hidden": program(families=("hidden",))},
        program2="7.0",
    )
    assert usage(appliance, {}) == {"hqd_knob": 7, "hqd_hidden": 0}


def test_knob_program_by_prefix_when_no_family_says():
    appliance = appliance_with(
        {"hqd_duvet": program(families=("hidden",)), "iot_wash_jackets": program()}, program2="1"
    )
    assert usage(appliance, {}) == {"hqd_duvet": 1, "iot_wash_jackets": 0}


RUNNING = json.loads((FIXTURES / "context_running.json").read_text())


def running(appliance, context=None, **shadow):
    appliance.context = json.loads(json.dumps(context if context is not None else RUNNING))
    del appliance.context["shadow"]
    appliance.parameters = {**RUNNING["shadow"], **shadow}
    return appliance


def test_running_program_from_the_start_command(washer):
    # Live, 2026-10-11: no programName anywhere, Peppina's own "program" parameter.
    assert running_program(running(washer)) == "hqd_synthetic_and_coloured"


def test_running_program_from_hon_name(washer):
    context = json.loads(json.dumps(RUNNING))
    context["commandHistory"]["command"]["programName"] = "PROGRAMS.WM_WD.IOT_WASH_WINE_STAINS"
    assert running_program(running(washer, context)) == "iot_wash_wine_stains"


def test_running_program_only_while_a_cycle_is_on(washer):
    assert running_program(running(washer, machMode="1")) is None
    assert running_program(running(washer, machMode="7")) is None
    assert running_program(running(washer, machMode="3")) == "hqd_synthetic_and_coloured"


def test_cycle_from_the_knob(washer):
    # The last command started an older cycle: this one came from the knob.
    context = json.loads(json.dumps(RUNNING))
    context["activity"]["activityStarted"] = "2026-10-11T15:00:00Z"
    assert running_program(running(washer, context, prCode="136")) == "hqd_eco_40_60_degrees"
    # Same if hOn has no activity, or the code changed since the command.
    del context["activity"]
    assert running_program(running(washer, context, prCode="136")) == "hqd_eco_40_60_degrees"
    assert running_program(running(washer, None, prCode="136")) == "hqd_eco_40_60_degrees"


def test_start_command_without_program_matches_fixed_values():
    appliance = appliance_with(
        {
            # On position 8, like the live command.
            "hqd_one": program(families=("dashboard",), position="8"),
            "iot_wash_two": program(position="8"),
        }
    )
    for key, rinse in (("hqd_one", "2"), ("iot_wash_two", "3")):
        appliance.start_command(key).parameters["rinseIterations"] = Parameter(
            {"typology": "fixed", "fixedValue": rinse}
        )
        appliance.start_command(key).parameters["prCode"] = Parameter(
            {"typology": "fixed", "fixedValue": "116"}
        )
    context = json.loads(json.dumps(RUNNING))
    sent = context["commandHistory"]["command"]["parameters"]
    del sent["program"]
    sent["rinseIterations"] = "3"
    assert running_program(running(appliance, context)) == "iot_wash_two"
    sent["rinseIterations"] = "9"  # fits neither: better nothing than a guess
    assert running_program(running(appliance, context)) is None
