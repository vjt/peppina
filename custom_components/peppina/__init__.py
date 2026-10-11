"""Peppina: hOn washing machines, with a stop button.

Logs in to hOn by itself (see hon/) and, for every appliance that knows both
the startProgram and stopProgram commands, adds its status sensors plus
program, start, stop and delayed start controls.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .hon import Appliance, Command, HonAuthError, HonClient, HonError

_LOGGER = logging.getLogger(__name__)

DOMAIN = "peppina"
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.DATETIME,
]
UPDATE_INTERVAL = timedelta(seconds=60)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from .dashboard import async_setup_dashboard

    await async_setup_dashboard(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = HonClient(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    washers = []
    try:
        for info in await client.appliances():
            appliance = Appliance(info)
            appliance.load_commands(await client.commands(info))
            if appliance.is_washer:
                washers.append(Washer(hass, entry, client, appliance))
    except HonAuthError as err:
        raise ConfigEntryError(f"hOn refused the credentials: {err}") from err
    except (aiohttp.ClientError, TimeoutError, HonError) as err:
        raise ConfigEntryNotReady(f"hOn is unreachable: {err}") from err
    _LOGGER.info("Peppina found %d appliance(s)", len(washers))

    for washer in washers:
        await washer.coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = washers
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    from .dashboard import async_save_dashboard

    await async_save_dashboard(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    # The entities are gone by now: dropping the timer leaves their restored
    # state alone, so a pending delayed start comes back after a reload.
    for washer in hass.data[DOMAIN].pop(entry.entry_id):
        washer.cancel_delayed_start()

    from .dashboard import async_save_dashboard

    await async_save_dashboard(hass)
    return True


class Washer:
    """One hOn appliance: its client, its poller and the Peppina-side state."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: HonClient, appliance: Appliance
    ) -> None:
        self.hass = hass
        self.client = client
        self.appliance = appliance
        self.mac = appliance.mac
        self.name = appliance.name
        info = appliance.info
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.mac)},
            name=self.name,
            manufacturer=info.get("brand"),
            model=info.get("modelName"),
            sw_version=info.get("fwVersion"),
            serial_number=info.get("serialNumber"),
        )
        self.coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.name}",
            update_interval=UPDATE_INTERVAL,
            update_method=self._async_update,
        )
        self.program: str | None = None
        # Temperature and spin the user picked, by hOn key. They outlive
        # program changes: a program that does not allow one falls back.
        self.settings: dict[str, str] = {}
        self.delayed_start: datetime | None = None
        self._unsub_delayed: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []

    async def _async_update(self) -> dict:
        try:
            self.appliance.load_context(await self.client.context(self.appliance))
        except (aiohttp.ClientError, TimeoutError, HonError) as err:
            raise UpdateFailed(f"{self.name}: {err}") from err
        return self.appliance.parameters

    @property
    def programs(self) -> list[str]:
        return self.appliance.programs

    def select_program(self, program: str) -> None:
        if program != self.program:
            self.program = program
            self._notify()

    def choices(self, key: str) -> list[str]:
        """Values the selected program allows for one setting."""
        if self.program not in self.programs:
            return []
        param = self.appliance.start_command(self.program).parameters.get(key)
        return param.choices if param else []

    def setting(self, key: str) -> str | None:
        """The value a start would send now."""
        if self.program not in self.programs:
            return None
        command = self.appliance.start_command(self.program)
        return command.value(key, {**self.appliance.parameters, **self.settings})

    def set_setting(self, key: str, value: str) -> None:
        if value not in self.choices(key):
            raise HomeAssistantError(f"{self.name}: {key}={value!r} not allowed by {self.program}")
        self.settings[key] = value
        self._notify()

    async def start(self) -> None:
        program = self.program
        if program not in self.programs:
            raise HomeAssistantError(f"{self.name}: unknown program {program!r}")
        await self._send(
            self.appliance.start_command(program), f"start of {program}", self.settings
        )

    async def stop(self) -> None:
        self.cancel_delayed_start()
        await self._send(self.appliance.stop_command(), "stop")

    async def _send(self, command: Command, what: str, settings: dict | None = None) -> None:
        try:
            accepted = await self.client.send(self.appliance, command, settings)
        except (aiohttp.ClientError, TimeoutError, HonError) as err:
            raise HomeAssistantError(f"{self.name}: {what} failed: {err}") from err
        if not accepted:
            raise HomeAssistantError(f"{self.name}: hOn rejected {what}")
        await self.coordinator.async_request_refresh()

    def schedule_start(self, when: datetime) -> None:
        self.cancel_delayed_start()
        self.delayed_start = when
        self._unsub_delayed = async_track_point_in_time(self.hass, self._delayed_fire, when)
        self._notify()

    def cancel_delayed_start(self) -> None:
        if self._unsub_delayed is not None:
            self._unsub_delayed()
            self._unsub_delayed = None
        if self.delayed_start is not None:
            self.delayed_start = None
            self._notify()

    async def _delayed_fire(self, _now: datetime) -> None:
        self._unsub_delayed = None
        self.delayed_start = None
        self._notify()
        try:
            await self.start()
        except HomeAssistantError as err:
            _LOGGER.error("Delayed start failed: %s", err)

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()
