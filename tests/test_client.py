"""Client error paths that must not leak the credentials."""
import asyncio
import json

import aiohttp
import pytest
import yarl

from hon import HonClient, HonError


class FailingSession:
    """/ciam/authorize answering an HTML error page, as in maintenance."""

    def get(self, url, params, headers):

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def json(self):
                info = aiohttp.RequestInfo(yarl.URL(url).with_query(params), "GET", {}, yarl.URL(url))
                raise aiohttp.ContentTypeError(info, (), status=200, message="text/html")

        return Response()


def test_login_errors_keep_the_password_out():
    client = HonClient(FailingSession(), "user@example.com", "hunter2")
    with pytest.raises(HonError) as raised:
        asyncio.run(client.login())
    assert "hunter2" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


class Answer:
    def __init__(self, data):
        self.data = data
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    async def json(self, content_type="application/json"):
        return self.data

    async def read(self):
        return json.dumps(self.data).encode()


class ConfigSession:
    """hOn's anonymous configuration endpoint and the CDN behind it."""

    def __init__(self, language):
        self.language = language
        self.calls = []

    def post(self, url, json, headers):
        self.calls.append((url, json, headers))
        found = {"version": 4368, "jsonPath": URL} if json["languageCode"] == self.language else {}
        return Answer({"payload": {"language": found}})

    def get(self, url, headers):
        self.calls.append((url, None, headers))
        return Answer({"PROGRAMS": {"WM_WD": {"HQD_COTTONS": "Cotone"}}})


URL = "https://assets.he-cdn.services/languages/language-it-4368.json"


def test_dictionary_version():
    session = ConfigSession("it")
    client = HonClient(session, "user@example.com", "hunter2")
    assert asyncio.run(client.dictionary_version("it")) == (4368, URL)
    url, body, headers = session.calls[0]
    assert url.endswith("/app-config")
    assert body["languageCode"] == "it"
    assert headers["x-api-key"].endswith("-configuration")
    assert asyncio.run(client.dictionary_version("xx")) is None


def test_dictionary():
    client = HonClient(ConfigSession("it"), "user@example.com", "hunter2")
    data = asyncio.run(client.dictionary(URL))
    assert data["PROGRAMS"]["WM_WD"]["HQD_COTTONS"] == "Cotone"


def test_last_activity():
    client = HonClient(None, "user@example.com", "hunter2")
    appliance = type("A", (), {"mac": "aa-bb-cc-dd-ee-ff"})()

    async def request(method, path, **kwargs):
        assert (method, path) == ("GET", "/commands/v1/retrieve-last-activity")
        assert kwargs["params"] == {"macAddress": "aa-bb-cc-dd-ee-ff"}
        return answer

    client._request = request
    answer = {"macAddress": "aa-bb-cc-dd-ee-ff", "attributes": {"prCode": "124", "remainingTimeMM": "81"}}
    assert asyncio.run(client.last_activity(appliance)) == {"prCode": "124", "remainingTimeMM": "81"}
    answer = {}
    assert asyncio.run(client.last_activity(appliance)) == {}


def test_start_carries_the_program_name():
    # As the hOn app and pyhOn send it: hOn's context had no program name for
    # Peppina's starts without it (2026-10-11).
    from hon import Appliance

    appliance = Appliance({"macAddress": "aa-bb-cc-dd-ee-ff", "applianceTypeId": 1})
    appliance.load_commands(
        {
            "applianceModel": {"options": {}},
            "startProgram": {"PROGRAMS.WM_WD.HQD_COTTONS": {"parameters": {}}},
            "stopProgram": {"parameters": {}},
        }
    )
    client = HonClient(None, "user@example.com", "hunter2")
    bodies = []

    async def request(method, path, **kwargs):
        bodies.append(kwargs["json"])
        return {"payload": {"resultCode": "0"}}

    client._request = request
    assert asyncio.run(client.send(appliance, appliance.start_command("hqd_cottons")))
    assert asyncio.run(client.send(appliance, appliance.stop_command()))
    assert bodies[0]["programName"] == "PROGRAMS.WM_WD.HQD_COTTONS"
    assert "programName" not in bodies[1]
