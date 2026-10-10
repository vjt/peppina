"""Power, door and remote control state, as the hon integration (0.8.4) had them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from . import DOMAIN
from .entity import PeppinaEntity
from .hon import Appliance


@dataclass(frozen=True, kw_only=True)
class PeppinaBinarySensorDescription(BinarySensorEntityDescription):
    is_on: Callable[[Appliance], bool]


BINARY_SENSORS = (
    PeppinaBinarySensorDescription(
        key="status",
        name="Status",
        device_class=BinarySensorDeviceClass.POWER,
        is_on=lambda a: a.is_on,
    ),
    PeppinaBinarySensorDescription(
        key="door_status",
        name="Door status",
        device_class=BinarySensorDeviceClass.DOOR,
        is_on=lambda a: a.get("doorStatus") == "1",
    ),
    PeppinaBinarySensorDescription(
        key="remote_control",
        name="Remote control",
        icon="mdi:remote",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on=lambda a: a.get("remoteCtrValid") == "1",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        PeppinaBinarySensor(washer, description)
        for washer in hass.data[DOMAIN][entry.entry_id]
        for description in BINARY_SENSORS
    )


class PeppinaBinarySensor(PeppinaEntity, BinarySensorEntity):
    entity_description: PeppinaBinarySensorDescription

    def __init__(self, washer, description: PeppinaBinarySensorDescription) -> None:
        super().__init__(washer, description.key, description.name)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on(self._washer.appliance)
