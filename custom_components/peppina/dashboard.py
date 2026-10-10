"""Sidebar dashboard: one full-page washing machine card per appliance.

Same approach as ha-verisure-italy: register a storage-mode Lovelace panel and
rewrite its config on every load from what the entity registry holds. It rides
on Lovelace internals (LovelaceStorage), so a failure is logged and swallowed:
the controls keep working without the page.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import DOMAIN, HON, Washer

_LOGGER = logging.getLogger(__name__)

URL = "peppina"
TITLE = "Peppina"
ICON = "mdi:washing-machine"
CARD_URL = "/peppina/peppina-card.js"
CARD_FILE = Path(__file__).parent / "www" / "peppina-card.js"

# Card role -> tail of the hon unique_id (after the mac).
STATUS = {
    "status": "on_off_status",
    "mode": "mach_mode",
    "phase": "pr_phase",
    "program": "program_name",
    "remaining": "remaining_time_m_m",
    "end": "end time",
    "temp": "temp",
    "spin": "spin_speed",
    "door": "door_status",
    "remote": "remote_ctr_valid",
    "paused": "pause",
    "error": "errors",
}
# Card role -> tail of our own unique_id.
CONTROLS = {
    "select": "program",
    "start": "start",
    "stop": "stop",
    "delayed": "delayed_start",
    "cancel": "cancel_delayed_start",
}


async def async_setup_dashboard(hass: HomeAssistant, washers: list[Washer]) -> None:
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    # mtime busts the browser cache when the card changes
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={int(CARD_FILE.stat().st_mtime)}")
    frontend.async_register_built_in_panel(
        hass,
        component_name="lovelace",
        sidebar_title=TITLE,
        sidebar_icon=ICON,
        frontend_url_path=URL,
        config={"mode": "storage"},
        require_admin=False,
        update=True,
    )
    try:
        await _save(hass, washers)
    except (AttributeError, KeyError, TypeError, ImportError, OSError):
        _LOGGER.exception("Dashboard setup failed, Lovelace internals may have changed")


async def _save(hass: HomeAssistant, washers: list[Washer]) -> None:
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return
    storage = lovelace.dashboards.get(URL)
    if not isinstance(storage, LovelaceStorage):
        storage = LovelaceStorage(
            hass,
            {
                "id": URL,
                "url_path": URL,
                "title": TITLE,
                "icon": ICON,
                "show_in_sidebar": True,
                "require_admin": False,
            },
        )
        lovelace.dashboards[URL] = storage

    registry = er.async_get(hass)
    views = []
    for washer in washers:
        entities = {}
        for role, key in STATUS.items():
            for domain in ("sensor", "binary_sensor"):
                entity_id = registry.async_get_entity_id(domain, HON, f"{washer.mac}_{key}")
                if entity_id:
                    entities[role] = entity_id
        for role, key in CONTROLS.items():
            for domain in ("select", "button", "datetime"):
                unique_id = f"{DOMAIN}_{washer.mac}_{key}"
                entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
                if entity_id:
                    entities[role] = entity_id
        views.append(
            {
                "title": washer.name,
                "path": "default" if not views else washer.mac,
                "icon": ICON,
                "type": "panel",
                "cards": [
                    {"type": "custom:peppina-card", "name": washer.name, "entities": entities}
                ],
            }
        )

    await storage.async_save({"views": views})
