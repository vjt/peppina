# Plan: Peppina without the hon integration

Status: **draft for review** — nothing below is implemented yet.

## Why

Peppina today does not talk to hOn by itself: it rides on the runtime of the
gvigroux/hon integration (`hass.data["hon"]` connections, `device.start_command`,
`device.stop_command`, `get_programs`) and its dashboard reads hon's sensors.
The hon integration exposes ~40 entities per washer, most of them noise, and
we want it gone.

## Library choice (measured 2026-10-10)

- **pyhOn (Andre0512) is not an option.** Last release 0.17.5, 2024-08-14. It
  logs in through the Salesforce Aura/OAuth2 flow, which Haier retired in
  2026-06 (see the docstring of `async_authorize` in gvigroux/hon 0.8.4).
- **gvigroux/hon 0.8.4** (MIT, last push 2026-09-07) already speaks the new
  CIAM login. Its client, though, is not a library: `hon.py`, `device.py` and
  `base.py` import `DataUpdateCoordinator`, `ConfigEntry`, the device
  registry. A fork-as-dependency would still mean carving the client out.

**Decision: vendor the client, stripped of Home Assistant**, into
`custom_components/peppina/hon/` with the MIT notice and the upstream commit
it was taken from. When Haier changes the API again, diff upstream and port.

## What gets vendored (and what does not)

| upstream | keep | notes |
|---|---|---|
| `hon.py` `HonConnection` | auth, appliance list, `load_commands`, `async_get_context`, `send_command` | drop `async_set` (googleHome path), `load_statistics`, coordinator bookkeeping, `get_device` |
| `command.py`, `parameter.py` | as is | pure Python already |
| `device.py` `HonDevice` | attribute/command handling, `start_command`, `stop_command`, `load_context` | no longer a `CoordinatorEntity` |
| `const.py` | `API_URL`, `APP_VERSION`, `OS*`, `DEVICE_MODEL` | everything climate/sensor-related goes |

Auth, as upstream does it: PKCE `GET /ciam/authorize` (email, password,
challenge) → `session_id`; `POST /ciam/token` → `cognito_token` + `id_token`;
`POST /unified-api/v1/view/appliance-list`. Tokens live ~15 min; upstream
re-runs the full login after 10 min and so will we, plus one retry on an
auth failure. Two changes from upstream:

- Use HA's shared `aiohttp` session (`async_get_clientsession`) instead of a
  private one.
- Upstream disables TLS verification (`TCPConnector(ssl=False)`). We keep it
  on; to be checked against `api-iot.he.services` before relying on it.

## Integration shape

- **Config flow** (email + password), validated by a real CIAM login. Moves
  Peppina from YAML/discovery to a config entry; the YAML `peppina:` line in
  `configuration.yaml` goes away.
- **One `DataUpdateCoordinator` per washer**, polling `/commands/v1/context`
  every 60 s (upstream's interval). Washer = appliance whose commands include
  both `startProgram` and `stopProgram`.
- **Own device** in the device registry; entities get `device_info`.
- Controls stay as they are (program select, start, stop, delayed start,
  cancel), now backed by the vendored client.

## Sensors — to be decided by vjt

Proposed set, raw hOn key → entity:

| keep? | entity | hOn key |
|---|---|---|
| yes | `binary_sensor.peppina_status` | `onOffStatus` |
| yes | `sensor.peppina_mode` | `machMode` |
| yes | `sensor.peppina_program_phase` | `prPhase` |
| yes | `sensor.peppina_program_name` | derived from `prCode` via the command tree |
| yes | `sensor.peppina_remaining_time` | `remainingTimeMM` |
| yes | `sensor.peppina_end_time` | computed: now + remaining while running |
| yes | `binary_sensor.peppina_door_status` | `doorStatus` |
| yes | `binary_sensor.peppina_remote_control` | `remoteCtrValid` |
| yes | `sensor.peppina_error` | `errors` |
| ? | `sensor.peppina_temperature` | `temp` |
| ? | `sensor.peppina_spin_speed` | `spinSpeed` |
| no | `binary_sensor.peppina_paused` | `pause` — hOn keeps it `on` even in mode 1, useless |
| no | the rest (water/energy totals, detergent, lock, steam, night wash, ...) | |

## Keeping entity ids (and history)

The recorder keys history by `entity_id`. Automations reference
`sensor.peppina_mode`, `binary_sensor.peppina_status`,
`binary_sensor.peppina_remote_control`. The new entities must land on the
**same entity ids with the same state encoding** (mode is the raw string
`"1"`, `"2"`, `"7"`; binaries `on`/`off`), so five weeks of history and the
automations survive untouched.

## Cutover

1. Turn the automation kill switch off.
2. Remove the hon config entry (its entities leave the registry, freeing the
   ids).
3. Install Peppina 0.3.0, add it through the config flow.
4. Check every entity id above exists and reports a sane state; check
   history for `sensor.peppina_mode` is continuous.
5. Kill switch on. Remove hon from HACS.

Rollback: reinstall hon + Peppina 0.2.0 (tag before merging).

## Testing

- Offline: unit tests for context parsing and program extraction against a
  recorded `/commands/v1/retrieve` + `/context` payload (scrubbed of MAC and
  tokens).
- Live, read-only: login, appliance list, context poll.
- Live, write: `stopProgram` on an idle machine; `startProgram` only with vjt
  at the machine.

## Out of scope

Dryers, multi-zone appliances, MQTT push, statistics.
