# Automations on top of Peppina

Peppina gives you start, stop, the delayed start and the machine state as
plain entities. Everything below is ordinary Home Assistant YAML built on
them: none of it ships with the integration, it is what the author runs at
home, trimmed to the reusable part. Copy what you need.

Entity ids assume the washer is called **Peppina**; yours carry your
appliance's name instead of `peppina_`. People and phones are placeholders:
`person.alice` / `person.bob`, `notify.mobile_app_alice` / `_bob`.

## The signals

Measured on a Haier washer over a month of loads:

| entity | meaning |
|---|---|
| `binary_sensor.peppina_remote_control` off → on | someone loaded it and pressed remote start: ready to be scheduled |
| `sensor.peppina_mode` `1` | on, idle; `2` washing; `7` finished (then back to `1`, and it powers off within ~3 min) |
| `binary_sensor.peppina_status` | machine powered. Blips off→on for ~1 min are hOn connection drops, not someone at the machine |
| `datetime.peppina_avvio_ritardato` | the delayed start, kept by Home Assistant |
| `button.peppina_avvia`, `button.peppina_annulla_avvio_ritardato` | start now, cancel the delayed start |

`door_status` and `door_lock` are useless for "has it been unloaded": the
machine powers off before anyone opens the door.

## Helpers

Create these in *Settings → Devices & services → Helpers*:

- `input_boolean.peppina_da_stendere`: laundry finished and still in the drum;
- `input_boolean.peppina_attesa_avvio`: a start is scheduled and we are
  waiting to see it happen (give it to the card as its `watch` role);
- `input_datetime.peppina_avvio_previsto` (date and time): when that start
  is due.

## Schedule a load left in remote control

Loaded in the evening, it finishes at 09:00 the next morning, so the laundry
does not sit wet all night; loaded in the morning, it finishes at 13:30;
otherwise it starts now. `for: 2 minutes` rides out hOn blips, and the
template refuses to override a delayed start set by hand. Give this
automation to the card as its `auto` role, with `auto_after: 2`.

```yaml
- id: peppina_programma
  alias: 'Peppina: schedule the load left in remote control'
  triggers:
  # from: 'off', so a restart (unavailable -> on) does not fire it
  - trigger: state
    entity_id: binary_sensor.peppina_remote_control
    from: 'off'
    to: 'on'
    for:
      minutes: 2
  conditions:
  - condition: state
    entity_id: sensor.peppina_mode
    state: '1'
  - condition: template
    value_template: >-
      {% set r = states('datetime.peppina_avvio_ritardato') %}
      {{ r in ['unknown', 'unavailable'] or as_datetime(r) <= now() }}
  actions:
  - variables:
      durata_min: 95   # your usual program, measured; add some margin
      avvio: >-
        {% set n = now() %}
        {% if 5 <= n.hour < 12 %}
          {% set fine = n.replace(hour=13, minute=30, second=0, microsecond=0) %}
        {% elif n.hour < 5 %}
          {% set fine = n.replace(hour=9, minute=0, second=0, microsecond=0) %}
        {% elif n.hour >= 18 %}
          {% set fine = (n + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0) %}
        {% else %}
          {% set fine = none %}
        {% endif %}
        {% set a = fine - timedelta(minutes=durata_min) if fine else n %}
        {{ 'now' if a <= n + timedelta(minutes=2) else a.isoformat() }}
  - if:
    - condition: template
      value_template: "{{ avvio == 'now' }}"
    then:
    - action: button.press
      target:
        entity_id: button.peppina_avvia
    else:
    - action: datetime.set_value
      target:
        entity_id: datetime.peppina_avvio_ritardato
      data:
        datetime: "{{ avvio }}"
    - action: notify.mobile_app_alice
      data:
        message: >-
          Peppina starts at {{ as_datetime(avvio).strftime('%H:%M') }}
  mode: single
```

## Cancel when it cannot work

Remote control switched off before the delayed start: the machine does not
cancel by itself, the start would just fail.

```yaml
- id: peppina_annulla
  alias: 'Peppina: cancel the start if remote control goes off'
  triggers:
  - trigger: state
    entity_id: binary_sensor.peppina_remote_control
    from: 'on'
    to: 'off'
  conditions:
  - condition: state
    entity_id: sensor.peppina_mode
    state: '1'
  - condition: template
    value_template: >-
      {% set r = states('datetime.peppina_avvio_ritardato') %}
      {{ r not in ['unknown', 'unavailable'] and as_datetime(r) > now() }}
  actions:
  - action: button.press
    target:
      entity_id: button.peppina_annulla_avvio_ritardato
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.peppina_attesa_avvio
  mode: single
```

## Start watchdog

Any delayed start in the future, set by the automation above or by hand,
arms a watchdog; washing disarms it; five minutes past the planned start
and still not washing (door open, hOn refusing, Home Assistant down at the
wrong moment) sends a critical push. A delayed start fires within a minute
of its time, measured.

```yaml
- id: peppina_watchdog_arma
  alias: 'Peppina: arm the start watchdog'
  triggers:
  - trigger: state
    entity_id: datetime.peppina_avvio_ritardato
  conditions:
  - condition: template
    value_template: >-
      {% set r = trigger.to_state.state %}
      {{ r not in ['unknown', 'unavailable'] and as_datetime(r) > now() }}
  actions:
  - action: input_datetime.set_datetime
    target:
      entity_id: input_datetime.peppina_avvio_previsto
    data:
      timestamp: "{{ as_datetime(trigger.to_state.state).timestamp() }}"
  - action: input_boolean.turn_on
    target:
      entity_id: input_boolean.peppina_attesa_avvio
  mode: single

- id: peppina_partita
  alias: 'Peppina: washing, disarm the watchdog'
  triggers:
  - trigger: state
    entity_id: sensor.peppina_mode
    to: '2'
  actions:
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.peppina_attesa_avvio
  mode: single

- id: peppina_avvio_fallito
  alias: 'Peppina: the start failed'
  triggers:
  - trigger: template
    value_template: >-
      {{ is_state('input_boolean.peppina_attesa_avvio', 'on')
         and now().timestamp() >=
             state_attr('input_datetime.peppina_avvio_previsto', 'timestamp') | float(0) + 300 }}
  conditions:
  - condition: not
    conditions:
    - condition: state
      entity_id: sensor.peppina_mode
      state: '2'
  actions:
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.peppina_attesa_avvio
  - action: notify.mobile_app_alice
    data:
      message: Peppina did NOT start, the laundry is sitting there
      data:
        push:
          interruption-level: critical
          sound:
            name: default
            critical: 1
            volume: 1.0
  mode: single
```

## The nag

When the cycle ends, a push every hour (07:00-23:00) and one the moment
someone walks in, until someone taps "Hung" or powers the machine on again.
It goes only to whoever is home: away, nobody can hang the laundry, and it
should not interrupt a lecture. After 6 hours wet in the drum it turns
critical and reaches everyone, home or away.

```yaml
- id: peppina_finita
  alias: 'Peppina: finished, to hang'
  triggers:
  - trigger: state
    entity_id: sensor.peppina_mode
    to: '7'
  actions:
  - action: input_boolean.turn_on
    target:
      entity_id: input_boolean.peppina_da_stendere
  mode: single

- id: peppina_stendi
  alias: 'Peppina: nag until it is hung'
  triggers:
  - trigger: state
    entity_id: input_boolean.peppina_da_stendere
    to: 'on'
  - trigger: state
    entity_id: [person.alice, person.bob]
    to: home
    not_from: [unknown, unavailable]
  - trigger: time_pattern
    hours: /1
    minutes: 0
  conditions:
  - condition: state
    entity_id: input_boolean.peppina_da_stendere
    state: 'on'
  - condition: time
    after: '07:00:00'
    before: '23:00:00'
  variables:
    # Not the last_changed of the boolean: a restart resets it.
    finita: >-
      {{ states('sensor.peppina_last_cycle_end')
         | as_datetime(states.input_boolean.peppina_da_stendere.last_changed) }}
    critical: "{{ now() - (finita | as_datetime) >= timedelta(hours=6) }}"
    destinatari: >-
      {% set ns = namespace(l=[]) %}
      {% for p, svc in [('person.alice', 'mobile_app_alice'),
                        ('person.bob', 'mobile_app_bob')] %}
        {% if critical or is_state(p, 'home') %}
          {% set ns.l = ns.l + [svc] %}
        {% endif %}
      {% endfor %}
      {{ ns.l }}
  actions:
  - repeat:
      for_each: "{{ destinatari }}"
      sequence:
      - action: "notify.{{ repeat.item }}"
        data:
          message: >-
            Peppina finished at
            {{ (finita | as_datetime | as_local).strftime('%H:%M') }}:
            hang the laundry
          data:
            tag: peppina_stendere
            actions:
            - action: PEPPINA_STESA
              title: Hung
            push:
              interruption-level: "{{ 'critical' if critical else 'active' }}"
              sound:
                name: default
                critical: "{{ 1 if critical else 0 }}"
                volume: 1.0
  mode: single

# "Hung" tapped, or the machine powered on again after 5+ minutes off
# (someone is at it: hOn blips last ~1 minute). Clears the push everywhere.
- id: peppina_stesa
  alias: 'Peppina: hung'
  triggers:
  - trigger: event
    event_type: mobile_app_notification_action
    event_data:
      action: PEPPINA_STESA
  - trigger: state
    entity_id: binary_sensor.peppina_status
    from: 'off'
    to: 'on'
  conditions:
  - condition: state
    entity_id: input_boolean.peppina_da_stendere
    state: 'on'
  - condition: template
    value_template: >-
      {{ trigger.platform == 'event'
         or now() - trigger.from_state.last_changed > timedelta(minutes=5) }}
  actions:
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.peppina_da_stendere
  - repeat:
      for_each: [mobile_app_alice, mobile_app_bob]
      sequence:
      - action: "notify.{{ repeat.item }}"
        data:
          message: clear_notification
          data:
            tag: peppina_stendere
  mode: single
```

Critical pushes need the iOS companion app's critical alerts permission;
on Android use `channel` / `priority: high` instead of `push:`.

## Cleaning reminders

Peppina reads the machine's filter, drum and detergent drawer counters after
every cycle and turns each into `binary_sensor.peppina_<x>_cleaning_due`
(`filter`, `drawer`, `drum`), with `button.peppina_<x>_cleaning_done` to say
it was done. Nothing nags on a timer with the machine idle: these two remind
when someone can act on it, at the start of a cycle and on walking into the
laundry room. Both share the list of what is due (a YAML anchor), with a
"cleaned" action per item.

```yaml
# A cycle starts with something due: one push, to whoever is home. Resuming
# from pause or coming back from unavailable is not a start.
- id: peppina_cleaning_at_start
  alias: 'Peppina: started, and something wants cleaning'
  triggers:
  - trigger: state
    entity_id: sensor.peppina_mode
    to: '2'
    not_from: ['3', unknown, unavailable]
  variables: &peppina_due
    # [name, notification action, its title] of every cleaning due
    due: >-
      {% set ns = namespace(l=[]) %}
      {% for key, name in [('filter', 'the filter'),
                           ('drawer', 'the detergent drawer'),
                           ('drum', 'the drum (autoclean)')] %}
        {% if is_state('binary_sensor.peppina_' ~ key ~ '_cleaning_due', 'on') %}
          {% set ns.l = ns.l + [[name, 'PEPPINA_CLEANED_' ~ key | upper, 'Cleaned ' ~ key]] %}
        {% endif %}
      {% endfor %}
      {{ ns.l }}
    listed: >-
      {% set n = due | map(attribute=0) | list %}
      {{ (n[:-1] | join(', ') ~ ' and ' ~ n[-1]) if n | length > 1 else n | join }}
    buttons: >-
      {% set ns = namespace(l=[]) %}
      {% for name, action, title in due %}
        {% set ns.l = ns.l + [{'action': action, 'title': title}] %}
      {% endfor %}
      {{ ns.l }}
  conditions:
  - condition: template
    value_template: "{{ due | length > 0 }}"
  actions:
  - repeat:
      for_each: >-
        {% set ns = namespace(l=[]) %}
        {% for p, svc in [('person.alice', 'mobile_app_alice'),
                          ('person.bob', 'mobile_app_bob')] %}
          {% if is_state(p, 'home') %}{% set ns.l = ns.l + [svc] %}{% endif %}
        {% endfor %}
        {{ ns.l }}
      sequence:
      - action: "notify.{{ repeat.item }}"
        data:
          message: "Peppina started. To clean: {{ listed }}"
          data:
            tag: peppina_cleaning
            actions: "{{ buttons }}"
  mode: single

# Walking into the laundry room with something due: to that person only, at
# most once a day. One automation per person: `this` keeps each one's last
# run. Room presence here comes from the Wi-Fi access points; any sensor
# that says which room someone is in will do.
- id: peppina_cleaning_laundry_alice
  alias: 'Peppina: something wants cleaning (Alice in the laundry room)'
  triggers:
  - trigger: state
    entity_id: sensor.alice_room
    to: laundry_room
  variables: *peppina_due
  conditions:
  - condition: template
    value_template: >-
      {{ due | length > 0
         and (this.attributes.last_triggered is none
              or as_local(this.attributes.last_triggered).date() != now().date()) }}
  actions:
  - action: notify.mobile_app_alice
    data:
      message: "Peppina: to clean, {{ listed }}"
      data:
        tag: peppina_cleaning
        actions: "{{ buttons }}"
  mode: single

# "Cleaned" tapped: press Peppina's done button for it.
- id: peppina_cleaned
  alias: 'Peppina: cleaned'
  triggers:
  - trigger: event
    event_type: mobile_app_notification_action
  conditions:
  - condition: template
    value_template: "{{ trigger.event.data.action.startswith('PEPPINA_CLEANED_') }}"
  actions:
  - action: button.press
    target:
      entity_id: >-
        button.peppina_{{ trigger.event.data.action[16:] | lower }}_cleaning_done
  mode: queued

# Nothing due any more, however it got done (a push, the dashboard, the
# machine's own maintenance cycle): drop the reminder everywhere.
- id: peppina_cleaned_clear
  alias: 'Peppina: all clean, clear the push'
  triggers:
  - trigger: state
    entity_id:
    - binary_sensor.peppina_filter_cleaning_due
    - binary_sensor.peppina_drawer_cleaning_due
    - binary_sensor.peppina_drum_cleaning_due
    from: 'on'
    to: 'off'
  conditions:
  - condition: template
    value_template: >-
      {{ expand('binary_sensor.peppina_filter_cleaning_due',
                'binary_sensor.peppina_drawer_cleaning_due',
                'binary_sensor.peppina_drum_cleaning_due')
         | selectattr('state', 'eq', 'on') | list | length == 0 }}
  actions:
  - repeat:
      for_each: [mobile_app_alice, mobile_app_bob]
      sequence:
      - action: "notify.{{ repeat.item }}"
        data:
          message: clear_notification
          data:
            tag: peppina_cleaning
  mode: single
```

The dashboard asks too: a cleaning due shows on the machine, and tapping it
asks whether it was done. The drum also offers to start the autoclean.

## Restarting Home Assistant

A restart kills any automation run sitting in a `delay` or `for:`. If you
restart while a load waits in remote control, the `from: 'off'` trigger will
not fire for it (it comes back from `unavailable`): set the start by hand,
or add a `homeassistant` `start` trigger that re-checks after a few minutes.
