"""Program catalog for the card: names, groups, load and how often each ran.

From the command tree, hOn's public dictionary (names and descriptions per
language) and the machine's own cycle counters. No I/O.
"""
from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from .appliance import Appliance, Command

# hOn clusters in the order the card lists them. Others follow by name;
# programs without one close the list.
GROUP_ORDER = (
    "traditional",
    "quick",
    "eco",
    "delicate",
    "stains",
    "health",
    "home",
    "sport",
    "baby",
    "pets",
    "ariel",
    "dash",
    "business",
)
CLUSTER_KEY = "GUIDED_WASHING.CLUSTER."
# machMode with a cycle on: running, paused, waiting on the machine's timer.
CYCLE_MODES = ("2", "3", "5")
# Seconds between a start command and the cycle it starts (1.5 measured).
START_WINDOW = 120
# When names collide, the family tells programs apart; the knob one gets none.
TAG_FAMILIES = ("care", "guided", "voice", "download", "featured")
TAG_ALIASES = {"voice": "guided"}


def dictionary_keys(appliance: Appliance) -> list[str]:
    """What to keep of hOn's dictionary for this appliance."""
    keys = set()
    for program in appliance.programs:
        command = appliance.start_command(program)
        keys |= {command.key, f"{command.key}_DESCRIPTION"}
        if cluster := _first(command, "programCluster"):
            keys.add(CLUSTER_KEY + cluster.upper())
    return sorted(keys)


def extract(dictionary: dict, keys: list[str]) -> dict[str, str]:
    """The wanted texts of hOn's dictionary, which nests on the dots."""
    texts = {}
    for key in keys:
        node = dictionary
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, str) and node:
            texts[key] = node
    return texts


def usage(appliance: Appliance, own: dict[str, int]) -> dict[str, int]:
    """Cycles per program: Peppina's own starts, plus whatever the machine
    counted on a knob position beyond them. That goes to the position's knob
    program (the hqd_ one), where starts from the knob or the hOn app land."""
    result = {program: own.get(program, 0) for program in appliance.programs}
    positions = defaultdict(list)
    for program in appliance.programs:
        if position := _first(appliance.start_command(program), "prPosition"):
            positions[position].append(program)
    for position, programs in positions.items():
        try:
            counted = int(float(appliance.get(f"program{position}") or 0))
        except (TypeError, ValueError):
            continue
        if owner := knob(appliance, programs):
            result[owner] += max(0, counted - sum(own.get(p, 0) for p in programs))
    return result


def program_codes(appliance: Appliance, code: object, position: object = None) -> list[str]:
    """Programs with this program code (and knob position, if given)."""
    found = []
    for program in appliance.programs:
        command = appliance.start_command(program)
        param = command.parameters.get("prCode")
        if param is None or param.typology != "fixed" or str(param.default) != str(code):
            continue
        if position is None or str(position) in command.info("prPosition"):
            found.append(program)
    return found


def running_program(appliance: Appliance) -> str | None:
    """The program the current cycle runs, None without a cycle or a sure answer.

    hOn keeps no programName for Peppina's starts (measured 2026-10-11), but
    its context keeps the command that started the cycle: Peppina's own
    "program" parameter, or the one program whose fixed values it carries.
    A cycle no command started came from the knob: the knob program of its
    program code.
    """
    if appliance.get("machMode") not in CYCLE_MODES:
        return None
    if (named := appliance.program_name) in appliance.programs:
        return named
    history = appliance.context.get("commandHistory") or {}
    command = history.get("command") or {}
    sent = command.get("parameters") or {}
    code = appliance.get("prCode")
    if (
        command.get("commandName") == "startProgram"
        and str(sent.get("prCode")) == str(code)
        and _started(history, appliance.context.get("activity") or {})
    ):
        if sent.get("program") in appliance.programs:
            return sent["program"]
        fits = [p for p in program_codes(appliance, code) if _fits(appliance.start_command(p), command)]
        return fits[0] if len(fits) == 1 else None
    return knob(appliance, program_codes(appliance, code))


def _started(history: dict, activity: dict) -> bool:
    """Whether the command was executed right before the activity started."""
    try:
        executed = datetime.fromisoformat(history["timestampExecuted"].replace("Z", "+00:00"))
        started = datetime.fromisoformat(activity["activityStarted"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        return False
    return 0 <= (started - executed).total_seconds() <= START_WINDOW


def _fits(command: Command, sent: dict) -> bool:
    """Whether every fixed value of the program is the one the command carried."""
    for params, values in (
        (command.parameters, sent.get("parameters") or {}),
        (command.ancillary, sent.get("ancillaryParameters") or {}),
    ):
        for key, param in params.items():
            if param.typology == "fixed" and key in values and str(param.default) != str(values[key]):
                return False
    return True


def knob(appliance: Appliance, programs: list[str]) -> str | None:
    """Which of these programs is printed on the knob: hOn's dashboard family,
    else the one hqd_ program; None when that is not one program."""
    for found in (
        [p for p in programs if "dashboard" in appliance.start_command(p).info("programFamily")],
        [p for p in programs if p.startswith("hqd_")],
    ):
        if len(found) == 1:
            return found[0]
    return None


def describe(
    appliance: Appliance,
    texts: dict[str, str],
    own: dict[str, int],
    durations: dict[str, dict] | None = None,
) -> list[dict]:
    """Every program for the card, by group then by name.

    durations: the machine's last estimate per program (see durations.py),
    {minutes, temp, spin}; a program it never estimated gets None.
    """
    durations = durations or {}
    counts = usage(appliance, own)
    programs, families = [], {}
    for program in appliance.programs:
        command = appliance.start_command(program)
        cluster = _first(command, "programCluster")
        temps, spins = _numbers(command, "temp"), _numbers(command, "spinSpeed")
        load = _first(command, "suggestedLoadW")
        programs.append(
            {
                "key": program,
                "name": texts.get(command.key) or _pretty(program),
                "description": texts.get(f"{command.key}_DESCRIPTION") or command.description,
                "group": cluster,
                "group_name": (texts.get(CLUSTER_KEY + cluster.upper()) or cluster.capitalize())
                if cluster
                else None,
                "tag": None,
                "load": _float(load),
                "temp": [temps[0], temps[-1]] if temps else None,
                "spin": spins[-1] if spins else None,
                "usage": counts[program],
                "duration": durations.get(program),
            }
        )
        families[program] = command.info("programFamily")
    names = Counter(_fold(p["name"]) for p in programs)
    for p in programs:
        if names[_fold(p["name"])] > 1 and "dashboard" not in families[p["key"]]:
            tag = next((f for f in TAG_FAMILIES if f in families[p["key"]]), None)
            p["tag"] = TAG_ALIASES.get(tag, tag)
    return sorted(programs, key=_rank)


def _rank(p: dict) -> tuple:
    group = p["group"]
    if group in GROUP_ORDER:
        place = (0, GROUP_ORDER.index(group), "")
    elif group:
        place = (1, 0, _fold(p["group_name"]))
    else:
        place = (2, 0, "")
    return (*place, _fold(p["name"]), p["tag"] is not None, p["key"])


def _first(command: Command, key: str) -> str | None:
    return next(iter(command.info(key)), None)


def _float(value: str | None) -> float | None:
    try:
        return float(value.replace(",", ".")) if value else None
    except ValueError:
        return None


def _numbers(command: Command, key: str) -> list[int]:
    param = command.parameters.get(key)
    try:
        return sorted(int(float(c)) for c in param.choices) if param else []
    except ValueError:
        return []


def _fold(text: str) -> str:
    """Case and accents off, every script's letters kept."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    ).casefold()


def _pretty(program: str) -> str:
    """The card's old label, from the program key."""
    for prefix in ("hqd_", "iot_wash_"):
        program = program.removeprefix(prefix)
    text = program.replace("_", " ")
    return text[:1].upper() + text[1:]
