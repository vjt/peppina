"""Status sensors.

Ids, units and value conversions follow the hon integration (0.8.4) entities
these replace, so their recorder history carries on.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import REVOLUTIONS_PER_MINUTE, UnitOfTemperature, UnitOfTime

from . import DOMAIN
from .entity import PeppinaEntity
from .hon import WASH_DRYER, WASHING_MACHINE, Appliance
from .hon.programs import running_program


@dataclass(frozen=True, kw_only=True)
class PeppinaSensorDescription(SensorEntityDescription):
    value: Callable[[Appliance], Any]


def _text(key: str) -> Callable[[Appliance], str | None]:
    return lambda a: None if a.get(key) is None else f"{a.get(key)}"


def _idle(a: Appliance) -> bool:
    return a.type_id == WASHING_MACHINE and a.get("machMode") in ("1", "6")


def _remaining(a: Appliance) -> int:
    remaining, delay = a.get_int("remainingTimeMM"), a.get_int("delayTime")
    if a.type_id == WASHING_MACHINE:
        return 0 if _idle(a) else remaining
    if a.type_id == WASH_DRYER and a.get_int("machMode") == 7:
        return delay
    return delay + remaining


def _end(a: Appliance) -> datetime | None:
    remaining = a.get_int("remainingTimeMM")
    if remaining == 0 or not a.is_on:
        return None
    minutes = a.get_int("delayTime") + remaining
    return datetime.now(timezone.utc).replace(second=0) + timedelta(minutes=minutes)


SENSORS = (
    PeppinaSensorDescription(
        key="mode", name="Mode", icon="mdi:washing-machine", value=_text("machMode")
    ),
    PeppinaSensorDescription(
        key="program_phase",
        name="Program phase",
        icon="mdi:washing-machine",
        value=lambda a: a.get("prPhase"),
    ),
    PeppinaSensorDescription(
        key="program_name",
        name="Program name",
        icon="mdi:playlist-play",
        value=lambda a: running_program(a) or "No program",
    ),
    PeppinaSensorDescription(
        key="remaining_time",
        name="Remaining time",
        icon="mdi:progress-clock",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=_remaining,
    ),
    PeppinaSensorDescription(
        key="end_time",
        name="End time",
        icon="mdi:clock-end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_end,
    ),
    PeppinaSensorDescription(
        key="error", name="Error", icon="mdi:math-log", value=_text("errors")
    ),
    PeppinaSensorDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda a: a.get("temp"),
    ),
    PeppinaSensorDescription(
        key="spin_speed",
        name="Spin speed",
        icon="mdi:speedometer",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        value=lambda a: 0 if _idle(a) else a.get_int("spinSpeed"),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    washers = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PeppinaSensor(washer, description) for washer in washers for description in SENSORS
    )
    async_add_entities(PeppinaLastEndSensor(washer) for washer in washers)


class PeppinaSensor(PeppinaEntity, SensorEntity):
    entity_description: PeppinaSensorDescription

    def __init__(self, washer, description: PeppinaSensorDescription) -> None:
        super().__init__(washer, description.key, description.name)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self._washer.appliance)


class PeppinaLastEndSensor(PeppinaEntity, RestoreSensor):
    """When the last cycle ended. Unlike the last_changed of anything that
    follows the end, it survives a restart: hOn keeps it, and so does the
    recorder."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:flag-checkered"

    def __init__(self, washer) -> None:
        super().__init__(washer, "last_cycle_end", "Last cycle end")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) and isinstance(
            last.native_value, datetime
        ):
            self._washer.restore_end(last.native_value)

    @property
    def native_value(self) -> datetime | None:
        return self._washer.last_end
