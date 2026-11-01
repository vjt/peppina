# Plan: maintenance reminders (filter, drum, detergent drawer)

Status: **plan, not built**, for review.

## What hOn exposes (measured)

`GET /commands/v1/maintenance-cycle?macAddress=<mac>` answers, on a Haier
washer:

```json
{"payload": {"resultCode": "0",
  "filterCleaning": {"tot": 100, "count": 44, "remaining": 56, "percentage": 44},
  "drumCleaning":   {"tot": 100, "count": 43, "remaining": 57, "percentage": 43},
  "drawerCleaning": {"tot": 100, "count": 44, "remaining": 56, "percentage": 44},
  "lastCheckup": null}}
```

Three counters, each `count` out of `tot`, plus `remaining` and `percentage`.
Peppina reads none of them today. Not known yet, to be measured before coding:

- **what `count` counts**: cycles since the last reset is the obvious guess,
  but `totalWashCycle` is 323 and `count` is 44, so something reset it
  (the hOn app's "done" button, an autoclean cycle, or a firmware rule);
- **who resets them**: whether an `hqd_autoclean` / `iot_wash_quick_drum_cleaner`
  cycle zeroes `drumCleaning` by itself, and whether the hOn app has a reset
  call for the filter and the drawer (the machine cannot know they were
  cleaned by hand);
- **when it is "due"**: `remaining == 0`, `percentage >= 100`, or a threshold
  the app shows earlier.

Method: poll the endpoint after each cycle for a couple of weeks, and capture
the hOn app's traffic when someone taps its "done" button.

## Integration (ships with Peppina, generic)

- Poll `maintenance-cycle` at start-up and at each cycle end (it changes only
  then), not on a timer.
- Per counter, one `sensor` (percentage, with `count` / `tot` / `remaining`
  as attributes) and one `binary_sensor` *due* (`device_class: problem`).
  Ids: `filter_cleaning`, `drum_cleaning`, `drawer_cleaning`.
- Per counter, a `button` *done*: it calls hOn's reset if there is one, so the
  hOn app agrees; otherwise Peppina keeps its own offset (restored across
  restarts) and the *due* sensor reads against it.
- Drum: the alert can offer "start the drum clean", which is
  `button.peppina_avvia` with `hqd_autoclean` (or the quick drum cleaner).
  If that cycle does not reset the counter by itself, its end does.

## Dashboard (ships with Peppina)

On Peppina's SVG:

- filter due → the filter hatch at the bottom front blinks, with a little
  "clean me";
- drawer due → the detergent drawer slides half out and blinks;
- drum due → bubbles/sparkles in the drum, "autoclean?".

Tapping one asks for confirmation ("Did you clean the filter?") and on yes
presses its *done* button. The drum also offers "start autoclean".

## Automations (ours, in ha-config; documented in automations.md as examples)

1. **At start, one notification.** When `sensor.peppina_mode` goes to `2`
   (from the app, a button or the knob) and at least one counter is due:
   **one** notification listing all of them ("started, but the filter and
   the drawer were due"), with a *done* action per item. Once per cycle.
   Only to whoever is home.
2. **On entering the laundry room.** When a known person's room goes to
   `laundry_room` and something is due: the same list, to that person only,
   with the *done* actions. At most once every few hours per person, so
   walking in and out does not spam.
3. *Done* from the notification or the dashboard presses the integration's
   button, and the open notifications are cleared, as for "Stesa".

No reminder on a timer with the machine idle: only at start and on entering
the room (vjt, 2026-11-01).

## Open questions

1. Rate limit for the room reminder: every 4 h? Once per day per item?
2. The laundry room AP is set low (it must cover only its own room): presence
   there shows up rarely (2 room changes in the last 7 days). Good enough,
   or does the room trigger need a check first?
3. The hOn "done" call: worth reverse engineering, or is a local offset
   enough?
