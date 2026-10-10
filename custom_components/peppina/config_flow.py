"""Config flow: one entry per hOn account, checked by a real login."""
from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN
from .hon import HonAuthError, HonClient

SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})


class PeppinaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            client = HonClient(async_get_clientsession(self.hass), email, user_input[CONF_PASSWORD])
            try:
                await client.login()
            except HonAuthError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=email, data={**user_input, CONF_EMAIL: email}
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
