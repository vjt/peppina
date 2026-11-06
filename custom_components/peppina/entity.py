"""Shared base for Peppina entities."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, Washer

# Maintenance counter -> icon. The sensor, its due binary_sensor and its done
# button are keyed after the counter.
MAINTENANCE = {
    "filter_cleaning": "mdi:filter-outline",
    "drum_cleaning": "mdi:washing-machine",
    "drawer_cleaning": "mdi:tray-full",
}


class PeppinaEntity(CoordinatorEntity):
    """Attached to the appliance's device and named after it, then after its
    key in Home Assistant's language (translations/)."""

    _attr_has_entity_name = True

    def __init__(self, washer: Washer, key: str, object_id: str | None = None) -> None:
        super().__init__(washer.coordinator)
        self._washer = washer
        self._attr_unique_id = f"{DOMAIN}_{washer.mac}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = washer.device_info
        # Pinned rather than slugged from the names, whatever the language:
        # the status entities take over the ids the hon integration had
        # (recorder history and automations key on them), and the controls
        # keep the ids they were first given. Platform modules are named after
        # their domain. Registered entities keep whatever id they already have.
        domain = type(self).__module__.rsplit(".", 1)[-1]
        self.entity_id = f"{domain}.{DOMAIN}_{object_id or key}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._washer.add_listener(self.async_write_ha_state))
