"""hOn appliance model: command tree, programs and context, no I/O.

Protocol ported from gvigroux/hon 0.8.4 (MIT, https://github.com/gvigroux/hon),
itself derived from Andre0512/pyhOn (MIT). Only what a washing machine needs.
"""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

START = "startProgram"
STOP = "stopProgram"
WASHING_MACHINE = 1
WASH_DRYER = 2
DEFAULT_NAMES = {WASHING_MACHINE: "Washing Machine", WASH_DRYER: "Wash Dryer"}


class Parameter:
    """One command parameter: a default plus the rule a new value must pass."""

    def __init__(self, attrs: dict) -> None:
        self.typology = attrs["typology"]
        if self.typology == "fixed":
            fixed = attrs.get("fixedValue")
            self.default = fixed if fixed is not None else "0"
        elif self.typology == "enum":
            self.values = sorted(str(v) for v in attrs.get("enumValues") or [])
            self.default = attrs.get("defaultValue") or "0"
        else:  # range
            keys = ("minimumValue", "maximumValue", "incrementValue")
            raw = [attrs[k] for k in keys] + [attrs.get("defaultValue", attrs["minimumValue"])]
            try:
                numbers = [int(v) for v in raw]
            except (TypeError, ValueError):
                numbers = [float(str(v).replace(",", ".")) for v in raw]
            self.min, self.max, self.step, self.default = numbers

    def coerce(self, value: Any) -> Any:
        """The value as the command would carry it, or None if it is not allowed."""
        if self.typology == "enum":
            return value if value in self.values else None
        if self.typology != "range":
            return None
        try:
            if isinstance(value, str):
                value = float(value.replace(",", "."))
                if not isinstance(self.step, float):
                    value = int(value)
            if self.min <= value <= self.max and not value % self.step:
                return value
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        return None

    @property
    def choices(self) -> list[str]:
        """Every value the parameter can take, low to high."""
        if self.typology == "enum":
            return sorted(self.values, key=_number)
        if self.typology == "range":
            count = int(round((self.max - self.min) / self.step)) + 1
            return [str(self.min + i * self.step) for i in range(count)]
        return [str(self.default)]


def _number(value: str) -> float:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return float("inf")


def _parameters(attrs: dict) -> dict[str, Parameter]:
    return {
        key: Parameter(value)
        for key, value in attrs.items()
        if value.get("typology") in ("fixed", "enum", "range")
    }


class Command:
    """A command, or one program of a multi-program command like startProgram."""

    def __init__(self, name: str, attrs: dict, program: str | None = None) -> None:
        self.name = name
        self.program = program
        self.parameters = _parameters(attrs.get("parameters", {}))
        self.ancillary = _parameters(attrs.get("ancillaryParameters", {}))

    def payload(self, current: dict) -> tuple[dict, dict]:
        """(parameters, ancillaryParameters) to send.

        Like upstream, the appliance's current settings override the program
        defaults wherever the program allows them.
        """
        params = {key: p.default for key, p in self.parameters.items()}
        for key, param in self.parameters.items():
            if key in current and (value := param.coerce(current[key])) is not None:
                params[key] = value
        if self.program is not None:
            params["program"] = self.program
        return params, {key: p.default for key, p in self.ancillary.items()}

    def value(self, key: str, current: dict) -> str | None:
        """What the command would send for one parameter, as a string."""
        if key not in self.parameters:
            return None
        return str(self.payload(current)[0][key])


class Appliance:
    """One appliance from the account's appliance list."""

    def __init__(self, info: dict) -> None:
        self.info = info
        self.mac: str = info["macAddress"]
        self.type_id = int(info["applianceTypeId"])
        self.type_name: str = info.get("applianceTypeName", "")
        self.name: str = info.get("nickName") or DEFAULT_NAMES.get(
            self.type_id, f"Device ID: {self.type_id}"
        )
        self.commands: dict[str, Command | dict[str, Command]] = {}
        self.options: dict = {}
        self.context: dict = {}
        self.parameters: dict[str, Any] = {}

    def load_commands(self, payload: dict) -> None:
        """Parse a /commands/v1/retrieve payload."""
        payload = dict(payload)
        model = payload.pop("applianceModel", None)
        if model is None:
            _LOGGER.error("%s: no applianceModel in the command tree", self.name)
            return
        self.options = model.get("options", {})
        for name, attrs in payload.items():
            if name in ("options", "dictionaryId") or not isinstance(attrs, dict):
                continue
            if "parameters" in attrs:
                self.commands[name] = Command(name, attrs)
                continue
            first = next(iter(attrs.values()), None)
            if isinstance(first, dict) and "parameters" in first:
                self.commands[name] = {
                    key.split(".")[-1].lower(): Command(name, sub, key.split(".")[-1].lower())
                    for key, sub in attrs.items()
                    if isinstance(sub, dict)
                }

    def load_context(self, payload: dict | None) -> None:
        """Parse a /commands/v1/context payload."""
        self.context = dict(payload or {})
        shadow = self.context.pop("shadow", None) or {}
        parameters = shadow.get("parameters") or {}
        if not parameters:
            _LOGGER.warning("%s: no parameters in the context: %s", self.name, self.context)
        self.parameters = {key: value.get("parNewVal") for key, value in parameters.items()}

    @property
    def is_washer(self) -> bool:
        return isinstance(self.commands.get(START), dict) and isinstance(
            self.commands.get(STOP), Command
        )

    @property
    def programs(self) -> list[str]:
        programs = self.commands.get(START)
        return list(programs) if isinstance(programs, dict) else []

    def start_command(self, program: str) -> Command:
        return self.commands[START][program]

    def stop_command(self) -> Command:
        return self.commands[STOP]

    def get(self, key: str) -> Any:
        return self.parameters.get(key)

    def get_int(self, key: str) -> int:
        return int(self.parameters.get(key) or 0)

    @property
    def is_on(self) -> bool:
        if self.get("onOffStatus") is not None:
            return self.get("onOffStatus") == "1"
        event = self.context.get("lastConnEvent") or {}
        return event.get("category") == "CONNECTED"

    @property
    def program_name(self) -> str | None:
        """Running program, from wherever the context carries it."""
        candidates = (
            (self.context.get("activity") or {}).get("attributes", {}).get("programName"),
            self.context.get("programName"),
            (self.context.get("commandHistory") or {}).get("command", {}).get("programName"),
        )
        name = next((c for c in candidates if c), None)
        if name is None:
            return None
        parts = name.lower().split(".")
        return parts[2] if len(parts) == 3 else name.lower()
