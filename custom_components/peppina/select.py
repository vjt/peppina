"""Program picker."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity

from . import DOMAIN
from .entity import PeppinaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(PeppinaProgram(w) for w in hass.data[DOMAIN][entry.entry_id])


class PeppinaProgram(PeppinaEntity, SelectEntity, RestoreEntity):
    _attr_icon = "mdi:washing-machine"

    def __init__(self, washer) -> None:
        super().__init__(washer, "program", "Programma")

    @property
    def options(self) -> list[str]:
        return self._washer.programs or [p for p in [self.current_option] if p]

    @property
    def current_option(self) -> str | None:
        return self._washer.program

    async def async_select_option(self, option: str) -> None:
        self._washer.program = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        programs = self._washer.programs
        if last is not None and last.state in programs:
            self._washer.program = last.state
        elif programs:
            self._washer.program = programs[0]
