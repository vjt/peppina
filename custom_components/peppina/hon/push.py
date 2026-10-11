"""hOn push: the appliance events hOn publishes on its AWS IoT broker.

The broker speaks MQTT over a websocket and lets in whoever brings an hOn id
token and its signature (a custom authorizer). Both expire, so every
connection fetches fresh ones. paho-mqtt does the protocol, on a thread of its
own for each connection; reconnecting is done here, with backoff. Endpoint and
authorizer as in Andre0512/pyhOn 0.17 (MIT).
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import ssl
import threading
import time
import urllib.parse
from typing import Callable

import aiohttp
import paho.mqtt.client as mqtt

from .client import HonClient, HonError

_LOGGER = logging.getLogger(__name__)

HOST = "a30f6tqw0oh1x0-ats.iot.eu-west-1.amazonaws.com"
AUTHORIZER = "candy-iot-authorizer"
KEEPALIVE = 60
CONNECT_TIMEOUT = 60
# AWS IoT takes at most 8 topic filters in one SUBSCRIBE.
SUBSCRIBE_MAX = 8
# Retries back off from 5 seconds to 5 minutes; a connection that held for
# STABLE seconds (so it got past CONNECT_TIMEOUT) starts the count again.
RETRY_MIN = 5
RETRY_MAX = 300
STABLE = 120
# How long a teardown waits for paho's thread. One stuck in a handshake is
# left to its socket timeout: it has been told to stop and cannot call back.
JOIN_TIMEOUT = 5


class PushError(Exception):
    """The broker refused or dropped the connection."""


class HonPush:
    """One connection for all the account's topics, kept up until cancelled.

    on_state gets the topics the broker granted when the connection is up,
    and an empty set when it is gone.
    """

    def __init__(
        self,
        client: HonClient,
        topics: list[str],
        on_message: Callable[[str, dict], None],
        on_state: Callable[[set[str]], None],
    ) -> None:
        self._client = client
        self._topics = topics
        self._on_message = on_message
        self._on_state = on_state
        self._ssl: ssl.SSLContext | None = None
        self.connected = False

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        if self._ssl is None:  # reads the CA bundle from disk
            self._ssl = await loop.run_in_executor(None, ssl.create_default_context)
        failures = 0
        while True:
            started = time.monotonic()
            try:
                await self._connection(loop)
            except aiohttp.ClientResponseError as err:
                reason = f"HTTP {err.status}"  # its message carries the URL
            except (aiohttp.ClientError, TimeoutError, HonError, PushError) as err:
                reason = str(err) or type(err).__name__
            except Exception:  # a bug must not end the push for good
                _LOGGER.exception("hOn push failed")
                reason = "unexpected error"
            if self.connected:
                self.connected = False
                self._on_state(set())
            if time.monotonic() - started >= STABLE:
                failures = 0
            delay = min(RETRY_MAX, RETRY_MIN * 2**failures)
            log = _LOGGER.warning if failures == 0 else _LOGGER.debug
            log("hOn push down (%s), retrying in %d s", reason, delay)
            failures += 1
            await asyncio.sleep(delay)

    async def _connection(self, loop: asyncio.AbstractEventLoop) -> None:
        """Connect, subscribe, deliver messages; raises once the connection is gone."""
        token, signature = await self._client.push_credentials()
        closed: asyncio.Future[str] = loop.create_future()
        stopped = threading.Event()

        # On the event loop, in the order paho called back: subscribed, then
        # messages, then gone.
        def close(reason: str) -> None:
            if not closed.done():
                closed.set_result(reason)

        def subscribed(refused: set[str]) -> None:
            timeout.cancel()
            if closed.done():
                return
            granted = set(self._topics) - refused
            if not granted:
                close("broker refused every subscription")
                return
            if refused:
                _LOGGER.warning("hOn push: broker refused %s", ", ".join(sorted(refused)))
            _LOGGER.info("hOn push connected, %d topic(s)", len(granted))
            self.connected = True
            self._on_state(granted)

        # On paho's thread, the only one that touches the client.
        pending: dict[int, list[str]] = {}
        refused: set[str] = set()

        def post(callback: Callable, *args) -> None:
            if not stopped.is_set():
                loop.call_soon_threadsafe(callback, *args)

        def on_connect(client, _userdata, _flags, reason, _properties) -> None:
            if reason.is_failure:
                post(close, f"broker refused the connection: {reason}")
                return
            # SUBACKs are read on this thread after this returns: pending is
            # complete by then.
            for start in range(0, len(self._topics), SUBSCRIBE_MAX):
                chunk = self._topics[start : start + SUBSCRIBE_MAX]
                pending[client.subscribe([(topic, 1) for topic in chunk])[1]] = chunk

        def on_subscribe(_client, _userdata, mid, reasons, _properties) -> None:
            chunk = pending.pop(mid, [])
            refused.update(t for t, r in zip(chunk, reasons) if r.is_failure)
            if not pending:
                post(subscribed, set(refused))

        def on_message(_client, _userdata, message) -> None:
            post(self._dispatch, message.topic, message.payload)

        def on_disconnect(_client, _userdata, _flags, reason, _properties) -> None:
            post(close, f"disconnected: {reason}")

        def drive() -> None:
            reason = "connection closed"
            try:
                client.connect(HOST, 443, KEEPALIVE)
                while not stopped.is_set():
                    if client.loop(1.0) != mqtt.MQTT_ERR_SUCCESS:
                        break
                else:
                    client.disconnect()
            except Exception as err:  # the connect failed, or paho broke
                reason = f"connection failed: {err}"
            post(close, reason)

        client = self._new_client()
        client.username_pw_set(
            f"?x-amz-customauthorizer-name={AUTHORIZER}"
            f"&x-amz-customauthorizer-signature={urllib.parse.quote(signature, safe='')}"
            f"&token={token}"
        )
        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        timeout = loop.call_later(CONNECT_TIMEOUT, close, "no answer from the broker")
        thread = threading.Thread(target=drive, name="peppina-push", daemon=True)
        thread.start()
        try:
            raise PushError(await closed)
        finally:
            timeout.cancel()
            stopped.set()
            await loop.run_in_executor(None, thread.join, JOIN_TIMEOUT)

    def _new_client(self) -> mqtt.Client:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"peppina_{secrets.token_hex(8)}",
            transport="websockets",
        )
        client.ws_set_options(path="/mqtt")
        client.tls_set_context(self._ssl)
        return client

    def _dispatch(self, topic: str, raw: bytes) -> None:
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            _LOGGER.warning("hOn push: no JSON object on %s: %r", topic, raw[:200])
            return
        self._on_message(topic, payload)
