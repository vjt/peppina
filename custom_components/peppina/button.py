"""Start, stop, cancel a pending delayed start, and cleanings done."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from . import DOMAIN
from .entity import MAINTENANCE, PeppinaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    entities = []
    for washer in hass.data[DOMAIN][entry.entry_id]:
        entities += [PeppinaStart(washer), PeppinaStop(washer), PeppinaCancelDelay(washer)]
        entities += [PeppinaMaintenanceDone(washer, key) for key in MAINTENANCE]
    async_add_entities(entities)


class PeppinaStart(PeppinaEntity, ButtonEntity):
    _attr_icon = "mdi:play"

    def __init__(self, washer) -> None:
        super().__init__(washer, "start", "Avvia")

    async def async_press(self) -> None:
        await self._washer.start()


class PeppinaStop(PeppinaEntity, ButtonEntity):
    _attr_icon = "mdi:stop"

    def __init__(self, washer) -> None:
        super().__init__(washer, "stop", "Stop")

    async def async_press(self) -> None:
        await self._washer.stop()


class PeppinaCancelDelay(PeppinaEntity, ButtonEntity):
    _attr_icon = "mdi:timer-off-outline"

    def __init__(self, washer) -> None:
        super().__init__(washer, "cancel_delayed_start", "Annulla avvio ritardato")

    async def async_press(self) -> None:
        self._washer.cancel_delayed_start()


class PeppinaMaintenanceDone(PeppinaEntity, ButtonEntity):
    """Cleaned: the counter starts again from here."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, washer, key: str) -> None:
        label, _icon = MAINTENANCE[key]
        super().__init__(washer, f"{key}_done", f"{label} done")
        self._key = key

    async def async_press(self) -> None:
        self._washer.maintenance_done(self._key)
