"""Program names from hOn's dictionary (cached), the starts Peppina sent and
the machine's duration estimates."""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .hon import HonClient, HonError
from .hon.programs import extract

_LOGGER = logging.getLogger(__name__)
TEXTS_LOCK = "peppina_texts_lock"


async def async_texts(hass: HomeAssistant, client: HonClient, keys: list[str]) -> dict[str, str]:
    """The wanted dictionary texts, in Home Assistant's language.

    Cached with hOn's dictionary version, so the multi-MB file comes down
    again only when hOn publishes a new one. Whatever is cached when hOn
    cannot be reached; {} if nothing is. One at a time: config entries share
    the cache, each adding its own keys.
    """
    async with hass.data.setdefault(TEXTS_LOCK, asyncio.Lock()):
        return await _async_texts(hass, client, keys)


async def _async_texts(hass: HomeAssistant, client: HonClient, keys: list[str]) -> dict[str, str]:
    store = Store(hass, 1, "peppina.texts")
    cached = await store.async_load() or {}
    language = (hass.config.language or "en").split("-")[0].lower()
    try:
        found = await client.dictionary_version(language)
        if found is None and language != "en":
            language, found = "en", await client.dictionary_version("en")
        if found is None:
            return cached.get("texts", {})
        version, url = found
        same = (cached.get("language"), cached.get("version")) == (language, version)
        known = set(cached.get("keys", [])) if same else set()
        if set(keys) <= known:
            return cached["texts"]
        wanted = sorted(known | set(keys))
        texts = extract(await client.dictionary(url), wanted)
    except (aiohttp.ClientError, TimeoutError, ValueError, HonError) as err:
        _LOGGER.warning("hOn dictionary unavailable (%s), program names from the cache", err)
        return cached.get("texts", {})
    if not texts:
        # A dictionary laid out differently: better the old names than none.
        _LOGGER.warning("hOn dictionary %s v%s has no program names we know", language, version)
        return cached.get("texts", {})
    await store.async_save(
        {"language": language, "version": version, "keys": wanted, "texts": texts}
    )
    return texts


class Usage:
    """Starts Peppina sent, per appliance and program, kept in .storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, 1, "peppina.usage")
        self._counts: dict[str, dict[str, int]] = {}

    async def async_load(self) -> None:
        self._counts = await self._store.async_load() or {}

    def counts(self, mac: str) -> dict[str, int]:
        return self._counts.get(mac, {})

    def count(self, mac: str, program: str) -> None:
        programs = self._counts.setdefault(mac, {})
        programs[program] = programs.get(program, 0) + 1
        self._store.async_delay_save(lambda: self._counts, 10)


class Durations:
    """Per appliance and program, kept in .storage (see hon/durations.py):
    the machine's last estimate (minutes), how long the last cycle really
    took (actual), and the temperature and spin they are for."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, 1, "peppina.durations")
        self._data: dict[str, dict[str, dict]] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    def get(self, mac: str) -> dict[str, dict]:
        return self._data.get(mac, {})

    def keep(self, mac: str, reading: dict) -> bool:
        """Merge a reading {program, minutes and/or actual, temp, spin};
        False if it changed nothing."""
        programs = self._data.setdefault(mac, {})
        old = programs.get(reading["program"], {})
        new = {**old, **{k: reading[k] for k in ("minutes", "actual", "temp", "spin") if k in reading}}
        if new == old:
            return False
        programs[reading["program"]] = new
        self._store.async_delay_save(lambda: self._data, 10)
        return True
