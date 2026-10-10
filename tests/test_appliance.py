"""Command tree and context parsing, against synthetic payloads."""
import pytest

from hon import Appliance

INFO = {
    "macAddress": "aa-bb-cc-dd-ee-ff",
    "applianceTypeId": 1,
    "applianceTypeName": "WM",
    "nickName": "Peppina",
}

TEMP = {
    "typology": "range",
    "minimumValue": "20",
    "maximumValue": "60",
    "incrementValue": "10",
    "defaultValue": "40",
}
SPIN = {"typology": "enum", "enumValues": [400, 800, 1200], "defaultValue": "800"}
ANCILLARY = {"remoteActionable": {"typology": "fixed", "fixedValue": "1"}}

COMMANDS = {
    "applianceModel": {"options": {"autoSoftener": "1"}},
    "options": {},
    "dictionaryId": "dict-1",
    "startProgram": {
        "PROGRAMS.WM_WD.HQD_COTTON": {
            "description": "start",
            "parameters": {
                "temp": TEMP,
                "spinSpeed": SPIN,
                "prCode": {"typology": "fixed", "fixedValue": "136"},
                "onOffStatus": {"typology": "fixed", "fixedValue": "1"},
            },
            "ancillaryParameters": ANCILLARY,
        },
        "PROGRAMS.WM_WD.IOT_WASH_QUICK": {
            "description": "start",
            "parameters": {
                "temp": {**TEMP, "maximumValue": "30", "defaultValue": "30"},
                "prCode": {"typology": "fixed", "fixedValue": "61"},
            },
        },
    },
    "stopProgram": {
        "description": "stop",
        "parameters": {"onOffStatus": {"typology": "fixed", "fixedValue": "0"}},
    },
}


def context(**params):
    return {
        "shadow": {"parameters": {k: {"parNewVal": v, "lastUpdate": "x"} for k, v in params.items()}},
        "lastConnEvent": {"category": "CONNECTED"},
    }


@pytest.fixture
def washer():
    appliance = Appliance(INFO)
    appliance.load_commands(COMMANDS)
    return appliance


def test_programs(washer):
    assert washer.is_washer
    assert washer.programs == ["hqd_cotton", "iot_wash_quick"]
    assert washer.options == {"autoSoftener": "1"}


def test_start_defaults(washer):
    params, ancillary = washer.start_command("hqd_cotton").payload({})
    assert params == {
        "temp": 40,
        "spinSpeed": "800",
        "prCode": "136",
        "onOffStatus": "1",
        "program": "hqd_cotton",
    }
    assert ancillary == {"remoteActionable": "1"}


def test_start_takes_current_settings_when_allowed(washer):
    current = {"temp": "60", "spinSpeed": "1200", "prCode": "999", "onOffStatus": "0"}
    params, _ = washer.start_command("hqd_cotton").payload(current)
    assert params["temp"] == 60
    assert params["spinSpeed"] == "1200"
    assert params["prCode"] == "136"  # fixed values never move
    assert params["onOffStatus"] == "1"


@pytest.mark.parametrize("temp", ["70", "35", "hot", None])
def test_start_ignores_values_out_of_range(washer, temp):
    params, _ = washer.start_command("hqd_cotton").payload({"temp": temp, "spinSpeed": "1000"})
    assert params["temp"] == 40
    assert params["spinSpeed"] == "800"


def test_program_ranges_differ(washer):
    params, _ = washer.start_command("iot_wash_quick").payload({"temp": "60"})
    assert params == {"temp": 30, "prCode": "61", "program": "iot_wash_quick"}


def test_float_range():
    appliance = Appliance(INFO)
    load = {
        "typology": "range",
        "minimumValue": "0,5",
        "maximumValue": "8",
        "incrementValue": "0,5",
    }
    appliance.load_commands(
        {"applianceModel": {}, "stopProgram": {"parameters": {"weight": load}}}
    )
    command = appliance.stop_command()
    assert command.payload({})[0] == {"weight": 0.5}
    assert command.payload({"weight": "2,5"})[0] == {"weight": 2.5}
    assert command.payload({"weight": "2,7"})[0] == {"weight": 0.5}


def test_stop(washer):
    assert washer.stop_command().payload({"onOffStatus": "1"}) == ({"onOffStatus": "0"}, {})


def test_no_appliance_model_means_no_commands():
    appliance = Appliance(INFO)
    appliance.load_commands({"startProgram": COMMANDS["startProgram"]})
    assert appliance.commands == {}
    assert not appliance.is_washer
    assert appliance.programs == []


def test_name_falls_back_to_type():
    info = {k: v for k, v in INFO.items() if k != "nickName"}
    assert Appliance(info).name == "Washing Machine"
    assert Appliance({**info, "applianceTypeId": 99}).name == "Device ID: 99"


def test_context(washer):
    washer.load_context(context(machMode="2", onOffStatus="1", remainingTimeMM="45"))
    assert washer.get("machMode") == "2"
    assert washer.get_int("remainingTimeMM") == 45
    assert washer.get("doorStatus") is None
    assert washer.get_int("delayTime") == 0
    assert washer.is_on
    assert "shadow" not in washer.context


def test_is_on_falls_back_to_connection(washer):
    washer.load_context(context(machMode="1"))
    assert washer.is_on
    washer.load_context({"shadow": {"parameters": {}}, "lastConnEvent": {"category": "DISCONNECTED"}})
    assert not washer.is_on
    washer.load_context(context(onOffStatus="0"))
    assert not washer.is_on


def test_context_without_shadow(washer):
    washer.load_context({"lastConnEvent": {"category": "CONNECTED"}})
    assert washer.parameters == {}
    washer.load_context(None)
    assert washer.parameters == {}


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({"activity": {"attributes": {"programName": "PROGRAMS.WM.HQD_COTTON"}}}, "hqd_cotton"),
        ({"programName": "IOT_WASH_QUICK"}, "iot_wash_quick"),
        ({"commandHistory": {"command": {"programName": "PROGRAMS.WM.HQD_MIX"}}}, "hqd_mix"),
        (
            {
                "activity": {"attributes": {}},
                "commandHistory": {"command": {"programName": "PROGRAMS.WM.HQD_MIX"}},
            },
            "hqd_mix",
        ),
        ({}, None),
    ],
)
def test_program_name(washer, extra, expected):
    washer.load_context({**context(machMode="2"), **extra})
    assert washer.program_name == expected
