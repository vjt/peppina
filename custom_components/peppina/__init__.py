"""Peppina: hOn washing machines, with a stop button.

Logs in to hOn by itself (see hon/) and, for every appliance that knows both
the startProgram and stopProgram commands, adds its status sensors plus
program, start, stop and delayed start controls. State changes arrive by push;
polling stays as the fallback, every minute while the push is down.
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

from .catalog import Durations, Usage, async_texts
from .hon import Appliance, Command, HonAuthError, HonClient, HonError
from .hon.durations import DurationWatch, activity_duration, activity_end
from .hon.programs import describe, dictionary_keys
from .hon.push import HonPush

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
# While the push is up, polling only guards against a push that went quiet.
PUSH_UPDATE_INTERVAL = timedelta(minutes=10)
USAGE = f"{DOMAIN}_usage"
DURATIONS = f"{DOMAIN}_durations"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from .dashboard import async_setup_dashboard

    await async_setup_dashboard(hass)
    usage = Usage(hass)
    await usage.async_load()
    hass.data[USAGE] = usage
    durations = Durations(hass)
    await durations.async_load()
    hass.data[DURATIONS] = durations
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
                washers.append(
                    Washer(hass, entry, client, appliance, hass.data[USAGE], hass.data[DURATIONS])
                )
    except HonAuthError as err:
        raise ConfigEntryError(f"hOn refused the credentials: {err}") from err
    except (aiohttp.ClientError, TimeoutError, HonError) as err:
        raise ConfigEntryNotReady(f"hOn is unreachable: {err}") from err
    _LOGGER.info("Peppina found %d appliance(s)", len(washers))

    for washer in washers:
        await washer.coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = washers
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _start_push(hass, entry, client, washers)
    if washers:
        entry.async_create_background_task(
            hass, _load_texts(hass, client, washers), f"{DOMAIN} texts"
        )
        for washer in washers:
            entry.async_create_background_task(
                hass, washer.async_seed_duration(), f"{DOMAIN} last activity"
            )

    from .dashboard import async_save_dashboard

    await async_save_dashboard(hass)
    return True


def _start_push(
    hass: HomeAssistant, entry: ConfigEntry, client: HonClient, washers: list[Washer]
) -> None:
    """One push connection for the account; the entry cancels it on unload."""
    by_topic = {topic: washer for washer in washers for topic in washer.appliance.topics}
    if not by_topic:
        return

    @callback
    def on_message(topic: str, payload: dict) -> None:
        by_topic[topic].push(topic, payload)

    @callback
    def on_state(granted: set[str]) -> None:
        for washer in set(by_topic.values()):
            washer.push_state(washer.appliance.status_topic in granted)

    push = HonPush(client, list(by_topic), on_message, on_state)
    entry.async_create_background_task(hass, push.run(), f"{DOMAIN} push")


async def _load_texts(hass: HomeAssistant, client: HonClient, washers: list[Washer]) -> None:
    """Program names and descriptions, in the background: the card makes do
    with the program keys until they land."""
    keys = sorted({key for washer in washers for key in dictionary_keys(washer.appliance)})
    texts = await async_texts(hass, client, keys)
    for washer in washers:
        washer.set_texts(texts)


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
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HonClient,
        appliance: Appliance,
        usage: Usage,
        durations: Durations,
    ) -> None:
        self.hass = hass
        self.client = client
        self.appliance = appliance
        self.usage = usage
        self.durations = durations
        self._watch = DurationWatch()
        # Program names and descriptions from hOn's dictionary, {} until loaded.
        self.texts: dict[str, str] = {}
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
        # When the last cycle ended: seen here, else hOn's or the restored one.
        self.last_end: datetime | None = None
        self._unsub_delayed: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        # Pushes that land while a context is on its way, None otherwise.
        self._held: list[tuple[str, dict]] | None = None

    @callback
    def push(self, topic: str, payload: dict) -> None:
        if self._held is not None:
            self._held.append((topic, payload))
            return
        complete = self.appliance.load_event(topic, payload)
        self._observe()
        # Not async_set_updated_data: that would put off the fallback poll
        # and drop a refresh already asked for.
        self.coordinator.async_update_listeners()
        if not complete:
            self.hass.async_create_task(self.coordinator.async_request_refresh())

    @callback
    def push_state(self, live: bool) -> None:
        """live: hOn pushes this appliance's status."""
        self.coordinator.update_interval = PUSH_UPDATE_INTERVAL if live else UPDATE_INTERVAL
        # Catch up on what happened while the push was down; the refresh also
        # reschedules polling at the new interval.
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def _async_update(self) -> dict:
        self._held = []
        try:
            self.appliance.load_context(await self.client.context(self.appliance))
        except (aiohttp.ClientError, TimeoutError, HonError) as err:
            raise UpdateFailed(f"{self.name}: {err}") from err
        finally:
            # They may be newer than the context: they go on top of it, or of
            # the old state if it did not come.
            held, self._held = self._held, None
            for topic, payload in held:
                self.appliance.load_event(topic, payload)
        self._observe()
        return self.appliance.parameters

    def _observe(self) -> None:
        """Keep the machine's duration estimate, when the state shows one."""
        if reading := self._watch.observe(self.appliance):
            self.durations.keep(self.mac, reading)
        self._ended(self._watch.ended)

    def _ended(self, when: datetime | None) -> bool:
        """Keep the latest end of a cycle; True if it moved."""
        if when is None or (self.last_end is not None and when <= self.last_end):
            return False
        self.last_end = when
        return True

    def restore_end(self, when: datetime | None) -> None:
        if self._ended(when):
            self._notify()

    async def async_seed_duration(self) -> None:
        """What hOn kept of the last cycle (estimate, real duration, end),
        where the machine has not told us since."""
        try:
            activity = await self.client.last_activity(self.appliance)
        except (aiohttp.ClientError, TimeoutError, HonError) as err:
            _LOGGER.debug("%s: no last activity from hOn (%s)", self.name, err)
            return
        self.restore_end(activity_end(activity))
        reading = activity_duration(self.appliance, activity)
        if not reading:
            return
        known = self.durations.get(self.mac).get(reading["program"], {})
        missing = {k: v for k, v in reading.items() if k == "program" or k not in known}
        if len(missing) > 1 and self.durations.keep(self.mac, missing):
            self._notify()

    @property
    def programs(self) -> list[str]:
        return self.appliance.programs

    def program_list(self) -> list[dict]:
        """Every program as the card shows it: name, group, load, usage."""
        return describe(
            self.appliance, self.texts, self.usage.counts(self.mac), self.durations.get(self.mac)
        )

    def set_texts(self, texts: dict[str, str]) -> None:
        self.texts = texts
        self._notify()

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
        self.usage.count(self.mac, program)
        self._watch.started(program)
        self._notify()
        await self.coordinator.async_request_refresh()

    async def stop(self) -> None:
        self.cancel_delayed_start()
        await self._send(self.appliance.stop_command(), "stop")
        await self.coordinator.async_request_refresh()

    async def _send(self, command: Command, what: str, settings: dict | None = None) -> None:
        try:
            accepted = await self.client.send(self.appliance, command, settings)
        except (aiohttp.ClientError, TimeoutError, HonError) as err:
            raise HomeAssistantError(f"{self.name}: {what} failed: {err}") from err
        if not accepted:
            raise HomeAssistantError(f"{self.name}: hOn rejected {what}")

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
            try:
                listener()
            except Exception:  # one broken entity must not hold up a stop
                _LOGGER.exception("%s: updating an entity failed", self.name)
