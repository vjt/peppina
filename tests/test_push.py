"""Push: events against scrubbed real payloads, and the connection loop
against a stand-in for paho."""
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from hon import Appliance, HonClient, HonError
from hon import push as push_module
from hon.push import HonPush

MAC = "aa-bb-cc-dd-ee-ff"
STATUS = f"haier/things/{MAC}/event/appliancestatus/update"
CONNECTED = f"$aws/events/presence/connected/{MAC}"
DISCONNECTED = f"$aws/events/presence/disconnected/{MAC}"
DISCOVERY = f"haier/things/{MAC}/event/discovery/update"
TOPICS = [DISCONNECTED, CONNECTED, STATUS, DISCOVERY]
EVENTS = json.loads((Path(__file__).parent / "fixtures" / "push_events.json").read_text())


@pytest.fixture
def washer():
    appliance = Appliance(
        {
            "macAddress": MAC,
            "applianceTypeId": 1,
            "applianceTypeName": "WM",
            "topics": {"subscribe": TOPICS},
        }
    )
    appliance.load_context(
        {
            "shadow": {"parameters": {"remainingTimeMM": {"parNewVal": "75"}}},
            "lastConnEvent": {"category": "CONNECTED", "timestampEvent": 1_000},
        }
    )
    return appliance


def status_events():
    return [e["payload"] for e in EVENTS if e["topic"] == STATUS]


def test_topics(washer):
    assert washer.topics == TOPICS
    assert Appliance({"macAddress": MAC, "applianceTypeId": 1}).topics == []


def test_status_events_chain(washer):
    # A whole cycle as hOn sent it: no gaps, the context wanted only when
    # the mode changes.
    events = status_events()
    assert len(events) >= 2
    washer.parameters = {c["parName"]: c["parOldVal"] for c in events[0]["parameters"]}
    for event in events:
        mode = any(c["parName"] == "machMode" for c in event["parameters"])
        assert washer.load_event(STATUS, event) is not mode
    for change in events[-1]["parameters"]:
        assert washer.get(change["parName"]) == change["parNewVal"]


def test_end_of_cycle(washer):
    end = next(e for e in status_events() if any(c["parName"] == "machMode" for c in e["parameters"]))
    washer.parameters.update(remoteCtrValid="1", machMode="2")
    washer.load_event(STATUS, end)
    assert washer.get("remoteCtrValid") == "0"
    assert washer.get("machMode") == "7"


def test_missed_status_event(washer):
    first, _, third = status_events()[:3]
    washer.parameters = {c["parName"]: c["parOldVal"] for c in first["parameters"]}
    assert washer.load_event(STATUS, first)
    assert not washer.load_event(STATUS, third)
    for change in third["parameters"]:
        assert washer.get(change["parName"]) == change["parNewVal"]


def test_status_event_keeps_other_parameters(washer):
    # A key the context did not have is news, not a gap.
    change = {"parName": "remoteCtrValid", "parOldVal": "1", "parNewVal": "0"}
    assert washer.load_event(STATUS, {"parameters": [change]})
    assert washer.get("remoteCtrValid") == "0"
    assert washer.get("remainingTimeMM") == "75"


def test_mode_change_wants_the_context(washer):
    # The running program is only in the context.
    washer.parameters["machMode"] = "1"
    change = {"parName": "machMode", "parOldVal": "1", "parNewVal": "2"}
    assert not washer.load_event(STATUS, {"parameters": [change]})
    assert washer.get("machMode") == "2"


def test_status_topic(washer):
    assert washer.status_topic == STATUS
    assert Appliance({"macAddress": MAC, "applianceTypeId": 1}).status_topic is None


def test_presence(washer):
    assert washer.is_on
    assert washer.load_event(DISCONNECTED, {"eventType": "disconnected", "timestamp": 2_000})
    assert not washer.is_on
    # AWS may deliver presence late: an older event changes nothing.
    assert washer.load_event(CONNECTED, {"eventType": "connected", "timestamp": 1_500})
    assert not washer.is_on
    assert washer.load_event(CONNECTED, {"eventType": "connected", "timestamp": 3_000})
    assert washer.is_on


def test_presence_as_seen(washer):
    # The washer switching itself off after a cycle, as AWS reported it.
    event = next(e for e in EVENTS if e["topic"] == DISCONNECTED)
    washer.context["lastConnEvent"]["timestampEvent"] = event["payload"]["timestamp"] - 1
    assert washer.load_event(DISCONNECTED, event["payload"])
    assert not washer.is_on


def test_other_topics_change_nothing(washer):
    assert washer.load_event(DISCOVERY, {"anything": 1})
    assert washer.parameters == {"remainingTimeMM": "75"}


def test_push_credentials():
    client = HonClient(None, "user", "secret")
    client._tokens = {"id-token": "id.token", "cognito-token": "c"}

    async def request(method, path, **kwargs):
        assert (method, path) == ("GET", "/auth/v1/introspection")
        return answer

    client._request = request
    answer = {"payload": {"tokenSigned": "sig"}}
    assert asyncio.run(client.push_credentials()) == ("id.token", "sig")
    answer = {"payload": {}}
    with pytest.raises(HonError):
        asyncio.run(client.push_credentials())


OK = SimpleNamespace(is_failure=False)
REFUSED = SimpleNamespace(is_failure=True)


class FakeMqtt:
    """Plays a script of broker packets, one per loop(), on the push's thread.

    Steps: "connack", "refuse", ("message", topic, payload), "drop". Script
    None: the broker cannot be reached.
    """

    def __init__(self, script):
        self.script = list(script) if script is not None else None
        self.subscriptions = []
        self.unacked = []
        self.disconnected = False

    def username_pw_set(self, username):
        self.username = username

    def connect(self, host, port, keepalive):
        self.target = (host, port, keepalive)
        if self.script is None:
            raise OSError("unreachable")

    def subscribe(self, topics):
        self.subscriptions.append(topics)
        self.unacked.append((len(self.subscriptions), topics))
        return 0, len(self.subscriptions)

    def loop(self, timeout):
        if not self.script:
            time.sleep(0.01)
            return 0
        step = self.script.pop(0)
        if step in ("connack", "refuse"):
            self.on_connect(self, None, None, OK if step == "connack" else REFUSED, None)
            for mid, topics in self.unacked:
                self.on_subscribe(self, None, mid, [OK] * len(topics), None)
        elif step == "drop":
            self.on_disconnect(self, None, None, OK, None)
            return 7
        else:
            _, topic, payload = step
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.on_message(self, None, SimpleNamespace(topic=topic, payload=raw))
        return 0

    def disconnect(self):
        self.disconnected = True


def run_push(monkeypatch, scripts, until, topics=TOPICS):
    """Run the push, one fake connection per script, until until(log) holds."""
    monkeypatch.setattr(push_module, "RETRY_MIN", 0)
    fakes, log = [], []

    class Client:
        credentials = 0

        async def push_credentials(self):
            Client.credentials += 1
            return f"id.token{Client.credentials}", "s/g+="

    async def main():
        done = asyncio.Event()

        def record(*entry):
            log.append(entry)
            if until(log):
                done.set()

        push = HonPush(Client(), topics, lambda t, p: record("message", t, p), lambda g: record("state", g))

        def new_client():
            fakes.append(FakeMqtt(scripts[min(len(fakes), len(scripts) - 1)]))
            return fakes[-1]

        push._new_client = new_client
        task = asyncio.create_task(push.run())
        await asyncio.wait_for(done.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    return fakes, log


def test_push_session(monkeypatch):
    event = EVENTS[0]["payload"]
    script = ["connack", ("message", STATUS, event), ("message", STATUS, b"not json"), "drop"]
    fakes, log = run_push(monkeypatch, [script, ["connack"]], lambda log: len(log) >= 4)
    assert log == [
        ("state", set(TOPICS)),
        ("message", STATUS, event),
        ("state", set()),
        ("state", set(TOPICS)),
    ]
    first, second = fakes
    assert first.target == (push_module.HOST, 443, push_module.KEEPALIVE)
    assert first.subscriptions == [[(topic, 1) for topic in TOPICS]]
    # Every connection brings fresh credentials, the signature URL-encoded.
    assert first.username == (
        "?x-amz-customauthorizer-name=candy-iot-authorizer"
        "&x-amz-customauthorizer-signature=s%2Fg%2B%3D&token=id.token1"
    )
    assert second.username.endswith("&token=id.token2")
    # Cancelled: the live connection says goodbye, on its own thread.
    for _ in range(100):
        if second.disconnected:
            break
        time.sleep(0.01)
    assert second.disconnected


def test_push_subscribes_in_chunks(monkeypatch):
    topics = [f"haier/things/{i}/event/appliancestatus/update" for i in range(10)]
    fakes, log = run_push(monkeypatch, [["connack"]], lambda log: log, topics)
    assert [len(chunk) for chunk in fakes[0].subscriptions] == [8, 2]
    assert log == [("state", set(topics))]


def test_push_refused(monkeypatch):
    fakes, log = run_push(monkeypatch, [["refuse"], ["refuse"], ["connack"]], lambda log: log)
    assert log == [("state", set(TOPICS))]
    assert [bool(f.subscriptions) for f in fakes] == [False, False, True]


def test_push_unreachable(monkeypatch):
    fakes, log = run_push(monkeypatch, [None, ["connack"]], lambda log: log)
    assert log == [("state", set(TOPICS))]
    assert len(fakes) == 2
