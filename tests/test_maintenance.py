"""Maintenance counters and the offsets Peppina's *done* keeps."""
import asyncio

from hon import HonClient
from hon.maintenance import DUE_REMAINING, Counter, Maintenance, counters

# maintenance-cycle on 2026-11-01.
PAYLOAD = {
    "filterCleaning": {"tot": 100, "count": 44, "remaining": 56, "percentage": 44},
    "drumCleaning": {"tot": 100, "count": 43, "remaining": 57, "percentage": 43},
    "drawerCleaning": {"tot": 100, "count": 44, "remaining": 56, "percentage": 44},
    "lastCheckup": None,
}


def at(**counts):
    """PAYLOAD with some counts changed, by Peppina's key."""
    names = {"filter": "filterCleaning", "drum": "drumCleaning", "drawer": "drawerCleaning"}
    payload = {k: dict(v) if isinstance(v, dict) else v for k, v in PAYLOAD.items()}
    for key, count in counts.items():
        payload[names[key]]["count"] = count
    return payload


def test_client_reads_the_counters():
    client = HonClient(None, "user@example.com", "hunter2")
    appliance = type("A", (), {"mac": "aa-bb-cc-dd-ee-ff"})()

    async def request(method, path, **kwargs):
        assert (method, path) == ("GET", "/commands/v1/maintenance-cycle")
        assert kwargs["params"] == {"macAddress": "aa-bb-cc-dd-ee-ff"}
        return answer

    client._request = request
    answer = {"payload": {"resultCode": "0", **PAYLOAD}}
    assert asyncio.run(client.maintenance(appliance)) == PAYLOAD
    answer = {"payload": {"resultCode": "1"}}
    assert asyncio.run(client.maintenance(appliance)) == {}
    answer = {}
    assert asyncio.run(client.maintenance(appliance)) == {}


def test_parsing():
    assert counters(PAYLOAD) == {
        "filter_cleaning": Counter(100, 44),
        "drum_cleaning": Counter(100, 43),
        "drawer_cleaning": Counter(100, 44),
    }
    # Missing, null, junk or no total: no counter rather than a wrong one.
    assert counters({}) == {}
    assert counters({"filterCleaning": None, "drumCleaning": {"tot": 0, "count": 3},
                     "drawerCleaning": {"tot": "x", "count": 1}}) == {}
    assert counters({"filterCleaning": {"tot": "100", "count": "7"}}) == {
        "filter_cleaning": Counter(100, 7)
    }


def test_nothing_known_before_hon_answers():
    m = Maintenance()
    assert (m.count("filter_cleaning"), m.percentage("filter_cleaning")) == (None, None)
    assert m.due("filter_cleaning") is None
    assert m.done("filter_cleaning") is False
    assert m.offsets == {}


def test_due_when_the_count_reaches_the_total():
    m = Maintenance()
    m.load(PAYLOAD)
    assert (m.count("drum_cleaning"), m.remaining("drum_cleaning")) == (43, 57)
    assert m.percentage("drum_cleaning") == 43
    assert m.due("drum_cleaning") is False
    m.load(at(drum=100 - DUE_REMAINING - 1))
    assert m.due("drum_cleaning") is False
    m.load(at(drum=100 - DUE_REMAINING))
    assert m.due("drum_cleaning") is True
    m.load(at(drum=105))
    assert (m.due("drum_cleaning"), m.remaining("drum_cleaning")) == (True, -5)


def test_done_keeps_an_offset():
    m = Maintenance()
    m.load(at(filter=100))
    assert m.due("filter_cleaning")
    assert m.done("filter_cleaning")
    assert m.offsets == {"filter_cleaning": 100}
    assert (m.count("filter_cleaning"), m.percentage("filter_cleaning")) == (0, 0)
    assert m.due("filter_cleaning") is False
    # The machine keeps counting on its own count: Peppina's runs from the offset.
    m.load(at(filter=130))
    assert (m.count("filter_cleaning"), m.remaining("filter_cleaning")) == (30, 70)
    m.load(at(filter=200))
    assert m.due("filter_cleaning")
    # The other counters are untouched.
    assert m.count("drawer_cleaning") == 44


def test_the_machine_restarting_the_count_drops_the_offset():
    m = Maintenance()
    m.load(at(drum=100))
    m.done("drum_cleaning")
    m.load(at(drum=103))
    assert m.count("drum_cleaning") == 3
    # A maintenance cycle on the machine: back to 0, 1.
    m.load(at(drum=1))
    assert m.offsets == {}
    assert m.count("drum_cleaning") == 1
    m.load(at(drum=50))
    assert m.count("drum_cleaning") == 50


def test_restored_offsets():
    # Restored before hOn answers: kept until the counters say otherwise.
    m = Maintenance()
    m.restore("filter_cleaning", 40)
    assert m.offsets == {"filter_cleaning": 40}
    m.load(PAYLOAD)
    assert m.count("filter_cleaning") == 4
    # Restored after: a count already below it was reset while Home Assistant was down.
    m = Maintenance()
    m.load(PAYLOAD)
    m.restore("drum_cleaning", 90)
    assert m.offsets == {}
    assert m.count("drum_cleaning") == 43
