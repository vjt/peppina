"""Program catalog for the card: names, groups, load and how often each ran.

From the command tree, hOn's public dictionary (names and descriptions per
language) and the machine's own cycle counters. No I/O.
"""
from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict

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
# When names collide, the family tells programs apart; the knob one gets none.
TAG_FAMILIES = ("care", "guided", "download", "featured")


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
        knob = [p for p in programs if p.startswith("hqd_")]
        try:
            counted = int(appliance.get(f"program{position}") or 0)
        except (TypeError, ValueError):
            continue
        if len(knob) == 1:
            result[knob[0]] += max(0, counted - sum(own.get(p, 0) for p in programs))
    return result


def describe(appliance: Appliance, texts: dict[str, str], own: dict[str, int]) -> list[dict]:
    """Every program for the card, by group then by name."""
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
                "load": float(load) if load else None,
                "temp": [temps[0], temps[-1]] if temps else None,
                "spin": spins[-1] if spins else None,
                "usage": counts[program],
            }
        )
        families[program] = command.info("programFamily")
    names = Counter(_fold(p["name"]) for p in programs)
    for p in programs:
        if names[_fold(p["name"])] > 1 and "dashboard" not in families[p["key"]]:
            p["tag"] = next((f for f in TAG_FAMILIES if f in families[p["key"]]), None)
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


def _numbers(command: Command, key: str) -> list[int]:
    param = command.parameters.get(key)
    try:
        return sorted(int(float(c)) for c in param.choices) if param else []
    except ValueError:
        return []


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def _pretty(program: str) -> str:
    """The card's old label, from the program key."""
    for prefix in ("hqd_", "iot_wash_"):
        program = program.removeprefix(prefix)
    text = program.replace("_", " ")
    return text[:1].upper() + text[1:]
