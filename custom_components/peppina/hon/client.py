"""hOn cloud client: CIAM login, appliance list, commands, context, send.

Protocol ported from gvigroux/hon 0.8.4 (MIT, https://github.com/gvigroux/hon).
Unlike upstream it runs on a session handed in by the caller and keeps TLS
verification on.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

import aiohttp

from .appliance import Appliance, Command

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api-iot.he.services"
APP_VERSION = "2.27.9"
OS = "android"
OS_VERSION = 31
DEVICE_MODEL = "exynos9820"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"
)
# CIAM tokens live ~15 minutes: log in again well before that, like upstream.
SESSION_TIMEOUT = 600


class HonError(Exception):
    """hOn answered something we cannot use."""


class HonAuthError(HonError):
    """hOn refused the credentials."""


class HonClient:
    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._mobile_id = secrets.token_hex(8)
        self._tokens: dict = {}
        self._login_at: float | None = None

    async def login(self) -> None:
        """PKCE: credentials -> session id -> cognito + id tokens."""
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        params = {"username": self._email, "password": self._password, "code_challenge": challenge}
        headers = {"User-Agent": USER_AGENT}
        try:
            async with self._session.get(
                f"{API_URL}/ciam/authorize", params=params, headers=headers
            ) as resp:
                if resp.status >= 500:
                    raise HonError(f"/ciam/authorize answered HTTP {resp.status}")
                session_id = (await resp.json()).get("session_id") if resp.status == 200 else None
        except aiohttp.ClientResponseError as err:
            # Its message carries the URL, and with it the credentials.
            raise HonError(f"/ciam/authorize answered HTTP {err.status}") from None
        if not session_id:
            raise HonAuthError(f"no session id from /ciam/authorize (HTTP {resp.status})")

        async with self._session.post(
            f"{API_URL}/ciam/token",
            json={"session_id": session_id, "code_verifier": verifier},
            headers=headers,
        ) as resp:
            try:
                tokens = (await resp.json())["tokens"]
                self._tokens = {
                    "cognito-token": tokens["cognito_token"],
                    "id-token": tokens["id_token"],
                }
            except (KeyError, TypeError) as err:
                raise HonAuthError(f"no tokens from /ciam/token (HTTP {resp.status})") from err
        self._login_at = time.monotonic()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Authenticated call; logs in again when stale and once on a refusal."""
        if self._login_at is None or time.monotonic() - self._login_at > SESSION_TIMEOUT:
            await self.login()
        try:
            return await self._call(method, path, **kwargs)
        except aiohttp.ClientResponseError as err:
            if err.status not in (401, 403):
                raise
            _LOGGER.debug("hOn refused %s with HTTP %s, logging in again", path, err.status)
        await self.login()
        return await self._call(method, path, **kwargs)

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **self._tokens}
        async with self._session.request(method, f"{API_URL}{path}", headers=headers, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def appliances(self) -> list[dict]:
        data = await self._request(
            "POST", "/unified-api/v1/view/appliance-list", json={"deviceId": "homeassistant"}
        )
        try:
            appliances = data["modules"]["applianceList"]["payload"]["appliances"]
        except (KeyError, TypeError) as err:
            raise HonError(f"unexpected appliance list: {str(data)[:500]}") from err
        return [a for a in appliances if "macAddress" in a and "applianceTypeId" in a]

    async def commands(self, info: dict) -> dict:
        """The appliance's command tree, {} if hOn has none for it."""
        params = {
            "applianceType": info["applianceTypeId"],
            "code": info["code"],
            "applianceModelId": info["applianceModelId"],
            "firmwareId": info["eepromId"],
            "macAddress": info["macAddress"],
            "fwVersion": info["fwVersion"],
            "os": OS,
            "appVersion": APP_VERSION,
            "series": info["series"],
        }
        data = await self._request("GET", "/commands/v1/retrieve", params=params)
        payload = dict(data.get("payload") or {})
        if payload.pop("resultCode", None) != "0":
            return {}
        return payload

    async def context(self, appliance: Appliance) -> dict:
        params = {
            "macAddress": appliance.mac,
            "applianceType": appliance.type_name,
            "category": "CYCLE",
        }
        data = await self._request("GET", "/commands/v1/context", params=params)
        return data.get("payload", {})

    async def send(
        self, appliance: Appliance, command: Command, settings: dict | None = None
    ) -> bool:
        parameters, ancillary = command.payload({**appliance.parameters, **(settings or {})})
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        body = {
            "macAddress": appliance.mac,
            "timestamp": now,
            "commandName": command.name,
            "transactionId": f"{appliance.mac}_{now}",
            "applianceOptions": appliance.options,
            "device": {
                "mobileId": self._mobile_id,
                "mobileOs": OS,
                "osVersion": OS_VERSION,
                "appVersion": APP_VERSION,
                "deviceModel": DEVICE_MODEL,
            },
            "attributes": {"channel": "mobileApp", "origin": "standardProgram", "energyLabel": "0"},
            "ancillaryParameters": ancillary,
            "parameters": parameters,
            "applianceType": appliance.type_name,
        }
        _LOGGER.debug("Sending %s", body)
        data = await self._request("POST", "/commands/v1/send", json=body)
        if (data.get("payload") or {}).get("resultCode") == "0":
            return True
        _LOGGER.error("hOn rejected %s: %s", command.name, data)
        return False
