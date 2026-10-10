# Peppina

Home Assistant integration for hOn (Haier / Candy / Hoover) washing machines,
with the one control the hOn integrations lack: a stop button.

Peppina logs in to hOn by itself (its own small client, ported from
[gvigroux/hon](https://github.com/gvigroux/hon)) and polls every appliance
that supports both `startProgram` and `stopProgram` once a minute. For each
one it adds a device with:

| Entity | What it does |
|---|---|
| `binary_sensor.peppina_status` | power |
| `sensor.peppina_mode` | raw hOn mode: 1 ready, 2 running, 3 paused, 5 timer, 6 error, 7 done |
| `sensor.peppina_program_name` / `sensor.peppina_program_phase` | running program and its phase |
| `sensor.peppina_remaining_time` / `sensor.peppina_end_time` | minutes left, and when it ends |
| `sensor.peppina_temperature` / `sensor.peppina_spin_speed` | settings of the running program |
| `binary_sensor.peppina_door_status` / `binary_sensor.peppina_remote_control` | door open, remote control enabled |
| `sensor.peppina_error` | hOn error code (`00` = none) |
| `select.<name>_programma` | pick the program to run (remembered across restarts; defaults to the first one) |
| `button.<name>_avvia` | start the selected program now |
| `button.<name>_stop` | stop the running program (and drop any pending delayed start) |
| `datetime.<name>_avvio_ritardato` | start the selected program at that instant |
| `button.<name>_annulla_avvio_ritardato` | drop the pending delayed start |

It also adds a **Peppina** sidebar dashboard: one full-page card per appliance
with the machine drawn in SVG (the drum turns while it washes, the whole thing
shakes on the spin) and the controls next to it.

The delayed start is scheduled by Home Assistant, not by the appliance: a
still-future start survives a restart, a missed one is dropped.

The status entities use the same ids and states as the hon integration's,
so their history and the automations using them carry over when you switch.
A second washer gets the same ids with a `_2` suffix.

## Install

1. Copy `custom_components/peppina` into your `custom_components/`
   (or add this repository to HACS as a custom integration).
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → Peppina, and log in with
   your hOn app email and password.

The hon integration is not needed. If it is installed, remove it first:
otherwise its entities hold the ids above. Coming from Peppina 0.2, drop the
`peppina:` line from `configuration.yaml`.

The appliance needs remote control enabled on its panel, same as for the hOn app.

## License

MIT
