"""Config flow: one entry per hOn account, checked by a real login.

When hOn refuses the stored password the entry raises ConfigEntryAuthFailed
and Home Assistant starts the reauth steps here, which ask for the new one.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN
from .hon import HonAuthError, HonClient, HonError

SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class PeppinaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            error = await self._login(email, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title=email, data={**user_input, CONF_EMAIL: email}
                )
            errors["base"] = error
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        """The account stays the same: only the password is asked again."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            error = await self._login(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def _login(self, email: str, password: str) -> str | None:
        """None if hOn takes the credentials, else the form's error key."""
        client = HonClient(async_get_clientsession(self.hass), email, password)
        try:
            await client.login()
        except HonAuthError:
            return "invalid_auth"
        except (aiohttp.ClientError, TimeoutError, HonError):
            return "cannot_connect"
        return None
