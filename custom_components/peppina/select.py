"""Program, temperature and spin pickers."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity

from . import DOMAIN
from .entity import PeppinaEntity

# hOn key -> (unique_id tail, label, icon)
SETTINGS = {
    "temp": ("set_temperature", "Temperatura", "mdi:thermometer"),
    "spinSpeed": ("set_spin_speed", "Centrifuga", "mdi:rotate-right"),
}


async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for washer in hass.data[DOMAIN][entry.entry_id]:
        entities.append(PeppinaProgram(washer))
        entities += [PeppinaSetting(washer, key) for key in SETTINGS]
    async_add_entities(entities)


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
        self._washer.select_program(option)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        programs = self._washer.programs
        if last is not None and last.state in programs:
            self._washer.program = last.state
        elif programs:
            self._washer.program = programs[0]


class PeppinaSetting(PeppinaEntity, SelectEntity, RestoreEntity):
    """One start setting. The state is what a start sends now, the
    `preferred` attribute what the user picked, kept across restarts."""

    def __init__(self, washer, key: str) -> None:
        tail, label, icon = SETTINGS[key]
        super().__init__(washer, tail, label)
        self._key = key
        self._attr_icon = icon

    @property
    def options(self) -> list[str]:
        return self._washer.choices(self._key) or [o for o in [self.current_option] if o]

    @property
    def current_option(self) -> str | None:
        return self._washer.setting(self._key)

    @property
    def extra_state_attributes(self) -> dict:
        return {"preferred": self._washer.settings.get(self._key)}

    async def async_select_option(self, option: str) -> None:
        self._washer.set_setting(self._key, option)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and (preferred := last.attributes.get("preferred")):
            self._washer.settings[self._key] = str(preferred)
