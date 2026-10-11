# Push: hOn events over MQTT

Status: released in 0.4.0. Until 0.3.5 Peppina asked hOn for
the state every 60 seconds, and a change that came and went within a minute
was never seen: remote control switched off and on again, for one, so the
"load left in remote" automation did not fire.

## How it works

hOn publishes appliance events on an AWS IoT broker
(`a30f6tqw0oh1x0-ats.iot.eu-west-1.amazonaws.com`, MQTT 3.1.1 over a
websocket on 443, path `/mqtt`). It lets in clients with a custom authorizer,
`candy-iot-authorizer`. The MQTT username carries the hOn id token and its
signature, `tokenSigned` from `GET /auth/v1/introspection`. The topics come
with each appliance in the appliance list, under `topics.subscribe`:

| Topic | What arrives |
|---|---|
| `haier/things/<mac>/event/appliancestatus/update` | the shadow parameters that changed |
| `$aws/events/presence/connected/<mac>` | the appliance came online |
| `$aws/events/presence/disconnected/<mac>` | the appliance went offline |
| `haier/things/<mac>/event/discovery/update` | ignored |

A status event carries only the changes, each with the value it replaces:

```json
{"parameters": [{"parName": "remainingTimeMM", "parOldVal": "74", "parNewVal": "73"}],
 "macAddress": "...", "applianceTypeName": "WM", "eventId": "...",
 "timestamp": "2026-10-11T09:03:20.6Z", "transactionId": "..."}
```

`hon/push.py` keeps one connection per account with paho-mqtt. paho does the
protocol, and pyhOn 0.17 uses the same endpoint with awscrt instead.

- **Credentials:** fresh ones on every connect, since the id token expires.
- **Retries:** back off from 5 seconds to 5 minutes.
- **Threading:** each connection has a thread of its own, and only that thread
  touches the paho client.

The integration (`__init__.py`) does the rest:

- **Status events** go into the appliance parameters, the same ones
  `load_context` fills, and the entities update at once.
- **When it asks hOn for the whole context:** when a `parOldVal` is not the
  value held (a message went missing), or when `machMode` changes (the running
  program is only in the context).
- **Presence events** set `lastConnEvent`, which the power sensor falls back to.
- **Polling stays** as the safety net: every 10 minutes while hOn pushes the
  washer's status, every minute while the push is down, and once on every
  up/down change.
- **Pushes during a fetch:** a push that lands while the context is being
  fetched is applied on top of it.

## Measured (2026-10-11, vjt's account, one washing machine, one cycle)

- The broker accepted the connection, and all four subscriptions were granted
  with QoS 1.
- During the cycle, one status event a minute: remaining time, energy and
  water. `prPhase` changes (wash, rinse, spin) came as they happened.
- **End of the cycle:** one event at 12:16:46 brought `remoteCtrValid` 1→0
  (the machine drops remote control when it finishes), `machMode` 2→7,
  `prPhase` and `totalWashCycle`. The door unlocked 3 s later. The 60-second
  poll saw all of it 46 s later, in a single snapshot.
- **The washer switching itself off,** three minutes after the end: a
  presence `disconnected` event (`timestamp` in epoch milliseconds,
  `disconnectReason: CLIENT_INITIATED_DISCONNECT`), and the power sensor went
  off with it.
- **Latency:** from the event's own timestamp to arrival, median 0.14 s and
  max 0.25 s, over 85 events.
- **Push against REST:** a 60-second poll running alongside saw the same phase
  changes 20 to 48 s later.
- **Which code ran:** the long run (over an hour, the end of the cycle
  included) used the first revision of `push.py`, with paho's own
  `loop_start` thread. The final revision, with a thread of its own driving
  `client.loop()`, ran live in two runs: 3.5 minutes with the forced reconnect,
  then the end of the cycle and the washer switching off (still connected
  12 minutes in, still running when the branch was pushed).
- **Missed events:** every `parOldVal` matched the value held, so no message
  went missing.
- **Connections:** never dropped by the broker over the whole test, one of
  them held more than an hour. The CIAM id token lives about 15 minutes, so the
  broker does not drop a session when the token expires.
- **Forced reconnect:** a second client was connected with the same client id,
  and AWS dropped the first. Peppina noticed in 0.6 s, came back 6 s later with
  fresh credentials, and the events resumed.
- **Home Assistant 2026.9.4 wiring**, checked with
  pytest-homeassistant-custom-component in a scratch test that is not in the
  repo:
  - a push reaches the entities;
  - remote control off and on within a minute gives both edges;
  - a gap triggers a refresh;
  - the polling interval follows the push;
  - pushes during a fetch land on top of it.

## Not measured

- **Remote control switched off and on by hand within a minute.** This was
  not done on the real machine. `remoteCtrValid` was seen arriving by push (at
  the end of the cycle), and every change is an event of its own, so both
  edges should arrive. The Home Assistant test shows that they reach the
  entities.
- **A presence `connected` event.** The washer did not come back online
  during the test. Only `disconnected` was seen, and the two differ only in
  `eventType`, as AWS documents them.
- **The install on HAOS.** paho-mqtt is a pure-python wheel and Home Assistant
  2026.9.4 pins `paho-mqtt==2.1.0`, but it was not installed on the real
  Home Assistant.
- **Days of uptime.** How long the broker keeps a session, beyond the hour
  seen.
- **More than one appliance.** Subscriptions go out at most 8 topics at a time
  (the AWS limit), but only the unit tests cover that.

## Rolling back

Nothing to migrate: same config entry, same entity ids. In HACS, redownload
Peppina picking v0.3.5 and restart Home Assistant. Peppina is back to polling
every minute.

Short of that, a push that cannot connect leaves Peppina polling every minute
on its own. The log says `hOn push down (...)`.
