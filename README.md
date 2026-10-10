# Peppina

Home Assistant controls for hOn (Haier / Candy / Hoover) washing machines,
built on top of the [gvigroux/hon](https://github.com/gvigroux/hon) integration.

hon reads the appliance fine but offers no way to stop a washing machine
program. Peppina reuses hon's live connection (no second login) and adds, for
every hon appliance that supports both `startProgram` and `stopProgram`:

| Entity | What it does |
|---|---|
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

## Install

1. Install and configure [hon](https://github.com/gvigroux/hon).
2. Copy `custom_components/peppina` into your `custom_components/`
   (or add this repository to HACS as a custom integration).
3. Add to `configuration.yaml`:

   ```yaml
   peppina:
   ```

4. Restart Home Assistant.

The appliance needs remote control enabled on its panel, same as for the hOn app.

## License

MIT
