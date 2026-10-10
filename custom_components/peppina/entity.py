"""Shared base for Peppina entities."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import DOMAIN, Washer


class PeppinaEntity(CoordinatorEntity):
    """Named after the appliance, attached to its device."""

    def __init__(self, washer: Washer, key: str, label: str) -> None:
        super().__init__(washer.coordinator)
        self._washer = washer
        self._attr_unique_id = f"{DOMAIN}_{washer.mac}_{key}"
        self._attr_name = f"{washer.name} {label}"
        self._attr_device_info = washer.device_info
        # Pinned rather than slugged from the appliance name: the status
        # entities take over the ids the hon integration had (recorder history
        # and automations key on them). Platform modules are named after
        # their domain. Registered entities keep whatever id they already have.
        domain = type(self).__module__.rsplit(".", 1)[-1]
        self.entity_id = f"{domain}.{DOMAIN}_{slugify(label)}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._washer.add_listener(self.async_write_ha_state))
