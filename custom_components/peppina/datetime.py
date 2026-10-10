"""Delayed start: set a future instant and the selected program starts then.

The delay is kept by Home Assistant, not by the appliance, and survives a
restart: a still-future instant is rescheduled, a missed one is dropped.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import DOMAIN
from .entity import PeppinaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(PeppinaDelayedStart(w) for w in hass.data[DOMAIN][entry.entry_id])


class PeppinaDelayedStart(PeppinaEntity, DateTimeEntity, RestoreEntity):
    _attr_icon = "mdi:timer-play-outline"

    def __init__(self, washer) -> None:
        super().__init__(washer, "delayed_start", "Avvio ritardato")

    @property
    def native_value(self) -> datetime | None:
        return self._washer.delayed_start

    async def async_set_value(self, value: datetime) -> None:
        if value <= dt_util.utcnow():
            raise HomeAssistantError("L'avvio ritardato va messo nel futuro")
        self._washer.schedule_start(value)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        when = dt_util.parse_datetime(last.state)
        if when is not None and when > dt_util.utcnow():
            self._washer.schedule_start(when)
