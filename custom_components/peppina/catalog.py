"""Program names from hOn's dictionary (cached) and the starts Peppina sent."""
from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .hon import HonClient, HonError
from .hon.programs import extract

_LOGGER = logging.getLogger(__name__)


async def async_texts(hass: HomeAssistant, client: HonClient, keys: list[str]) -> dict[str, str]:
    """The wanted dictionary texts, in Home Assistant's language.

    Cached with hOn's dictionary version, so the multi-MB file comes down
    again only when hOn publishes a new one. Whatever is cached when hOn
    cannot be reached; {} if nothing is.
    """
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
        if (cached.get("language"), cached.get("version")) == (language, version) and set(
            keys
        ) <= set(cached.get("keys", [])):
            return cached["texts"]
        texts = extract(await client.dictionary(url), keys)
    except (aiohttp.ClientError, TimeoutError, ValueError, HonError) as err:
        _LOGGER.warning("hOn dictionary unavailable (%s), program names from the cache", err)
        return cached.get("texts", {})
    await store.async_save({"language": language, "version": version, "keys": keys, "texts": texts})
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
