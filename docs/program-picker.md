# Plan: a program picker that says what each program is

Status: **implemented** on `program-picker` (2026-10-11), not released.

## Why

The card's program list is a native `<select>` with 92 entries named after
hOn keys (`Hqd cottons`, `Iot wash wine stains`), with no description and no
order other than hOn's. Finding the program you use every day means
scrolling past ones you never use.

## What hOn gives (measured 2026-10-11, vjt's washer)

- **Command tree** (`/commands/v1/retrieve`, already downloaded): for each
  program, an English `description`, and among the ancillary parameters:
  - `programCluster`: traditional, quick, eco, delicate, stains, health,
    home, sport, baby, pets, ariel, dash, business, steam. It is sometimes an
    enum: the first value is the primary one.
  - `programFamily`: dashboard (on the knob), guided, voice, download, care,
    featured, hidden, maintenance, diagnostic.
  - `remoteVisible`: 0 for the 27 programs the hOn app hides.
  - `prPosition`: the knob position the program runs on.
  - `suggestedLoadW`: kg.

  The temperature and spin choices come from the parameters, as for the
  selects.
- **Dictionary**, anonymous: `POST /app-config` with `languageCode` gives a
  `jsonPath` (`https://assets.he-cdn.services/languages/language-it-4368.json`,
  6.9 MB, versioned). Every program has a name and a description:
  - `PROGRAMS.WM_WD.HQD_COTTONS` = "Cotone";
  - `..._DESCRIPTION` = "Ciclo realizzato per…";
  - `GUIDED_WASHING.CLUSTER.TRADITIONAL` = "Tradizionali".

  All 92 programs and all clusters are covered in Italian.
- **Machine counters**: the shadow parameters `program1`..`program25` count
  cycles per knob position. Position 1 (Smart) is at 192, and it went to 193
  at the end of the cycle on 2026-10-11. Every position has exactly one
  `HQD_*` program (the knob one) plus zero or more `IOT_WASH_*` variants that
  run on it.

## Design

### Data, in the integration

- **Catalog** (`hon/`, no Home Assistant): for each program, its key, primary
  cluster, family, `remoteVisible`, knob position, suggested load,
  temperature choices and spin choices, read from the command tree.
- **Names**: `HonClient` fetches the dictionary for Home Assistant's language
  (`it` from `it-IT`, `en` if hOn has none).
  - Only the keys for the appliance's programs and the cluster labels are
    kept, about 13 KB.
  - They are cached in `.storage` with the dictionary version, so the 6.9 MB
    only come down again when hOn publishes a new version.
  - The fetch runs in the background after setup.
  - Until it lands, or if it fails: the prettified key and the English
    description from the command tree.
- **Usage**:
  - Peppina counts the starts hOn accepts, per program (button, delayed
    start, automation: everything through `Washer.start`), in `.storage`.
  - For the card, usage = own starts, plus, for the `HQD_*` program of each
    position, `max(0, counter - own starts of the programs on that
    position)`. Starts made from the knob or the hOn app land on the knob
    program; nothing is counted twice.
- **To the card**: a `programs` attribute on the program select. For each
  program: key, name, description, group (key and label), tag, load,
  temperature range, top spin and usage. About 30 KB for 92 programs, above
  the recorder's 16 KB limit, so it is left out of the recorder.

### Card

- **The field**: a button styled like the other selects, showing the name of
  the selected program. Under it, the description (two lines) and chips:
  `max 9 kg`, `20–60°C`, `1400 giri`.
- **The sheet**: a tap opens it, from the bottom on narrow screens, centered on
  wide ones.
  - **Search**: on name and description, case and accents ignored.
  - **Most used**: up to 10 programs with usage above 0, most used first.
  - **Groups**: then one group per cluster, in a fixed order (Tradizionali,
    Rapidi, Eco, Delicati, Macchie, Salute, Casa, Sport, Baby, Pets, Ariel,
    Dash, Business; clusters not in this list follow, by label; programs
    without a cluster close). Alphabetical inside each group. The most used
    programs also stay in their group.
  - **Rows**: the name, a tag when another program has the same name
    ("guidato" for guided/voice, "cura capi" for care), one line of
    description, and on the right the usage (`192×`) or the load.
  - **Picking**: a tap on a row selects the program (`select.select_option`)
    and closes the sheet. ✕, Esc or the backdrop close it without changing
    anything.
- **All 92 programs** are listed, `remoteVisible` included.
- **One file**: it stays in `peppina-card.js`, as a separate custom element.
  The card is served with `?v=<mtime>` and a second module imported from it
  would not be.
- **Strings**: the card's new strings go in one table, Italian for now (see
  below).

## Duration (added after 0.5.0)

vjt asked for each program's estimated duration, taken from hOn and never
made up.

- **No static duration anywhere in hOn**, checked on 2026-10-11:
  - the command tree has only `mainWashTime` (the main wash: 3 minutes for
    Express 15'), `rinseIterationTime`, `dryTime`, `delayTime`;
  - the dictionary has no duration keys;
  - `appliance-model` comes back empty;
  - `statistics`, `maintenance-cycle` and `program-list-rules` have none;
  - `history` and `favourite` hold only the parameters that were sent.
- **The machine's own estimate exists**, as `remainingTimeMM`, at three
  moments:
  - **Idle**, for the program on its knob. Ready again after the cycle of
    2026-10-11, it showed prCode 136 (Eco 40-60) and 170 minutes.
  - **When a cycle starts**, for that cycle.
  - **In `retrieve-last-activity`**, for the last cycle: the Smart cycle of
    that morning, 81 minutes at its start. It took 81.5 (activityStarted
    08:55:19Z, activityEnded 10:16:46Z).
- **What Peppina does with them** (`hon/durations.py`):
  - It reads them off every update, pushed or polled: idle, for the knob
    program of the current program code; at a start (not a resume, not a
    first look at a cycle already running), for the program Peppina just
    sent, or the only program with that code, once the machine shows it.
  - At setup it takes the last cycle's estimate from
    `retrieve-last-activity`, for a program that has none yet.
  - It keeps the last estimate per program, with the temperature and spin
    it was made for, in `.storage/peppina.durations`. 0.5.0's
    `peppina.usage` is untouched.
- **In the card:**
  - The picker shows the estimate next to each program that has one
    (`1 h 21 min · 192×`).
  - The selected program gets a `≈ 1 h 21 min` chip, and a line saying it
    is the machine's estimate and at which temperature and spin.
  - A program the machine never estimated shows no duration.
- **Not measured:**
  - The value at the very start of a cycle, seen live: the cycles watched
    so far were already running.
  - Idle estimates for programs other than Eco 40-60.

## Running program (added after 0.5.0)

vjt saw `sensor.peppina_program_name` = "No program" during a cycle he
had started remotely at 13:29 (mode 2).

- **Measured live on that cycle:**
  - hOn's context has no `programName`, neither in `activity.attributes`
    nor in `commandHistory.command`.
  - It keeps the start command whole: its `program` parameter (Peppina's
    own) was `hqd_synthetic_and_coloured`.
  - The command was executed at 11:29:02.5Z, the activity started at
    11:29:04Z.
  - prCode 116 alone fits 21 programs. Matching the command's fixed values
    against the command tree leaves one, the same one.
- **What Peppina does** (`running_program` in `hon/programs.py`), while a
  cycle is on (mode 2, 3 or 5), in this order:
  1. hOn's programName, when it has one.
  2. The command that started this cycle: executed at most two minutes
     before the activity, with the same program code. It gives its
     `program` parameter, or the one program its fixed values fit; nothing
     if several fit.
  3. For a cycle no command started (the knob), the knob program of the
     program code.
- **The card** names it in the status line with the dictionary name
  ("Sintetici · finisce alle 15:40"), instead of a chip with the raw key.
- **Starts now send `programName`** (`PROGRAMS.WM_WD.HQD_...`), as the hOn
  app and pyhOn do. Not measured: whether hOn then reports it. That needs
  a start.

## Keyboard on iPhone (added after 0.5.0)

vjt saw the search field end up under the keyboard in the Home Assistant
app on iPhone.

- **Measured:** Home Assistant's frontend (20260826.7, the one in 2026.9.4)
  declares `width=device-width,user-scalable=no,viewport-fit=cover,initial-scale=1`.
  There is no `interactive-widget`, so the keyboard shrinks only the visual
  viewport: on iOS always, and in Chrome too. `vh` and `dvh` do not follow it.
- **Fix:** while the sheet is open it pins itself to `visualViewport`
  (top = `offsetTop`, height = `height`, on resize and scroll). Its box
  takes at most 85% of that. The search field is at least 16 px, so iOS
  does not zoom the page on focus.
- **Not measured: the app's webview itself.** The checks ran in jsdom, with
  a simulated `visualViewport`. To measure on the phone, open the
  dashboard with `?peppina_viewport` at the end of the URL: a box shows the
  window size, the visual viewport (size, offset, scale), `100vh`, `dvh`,
  `svh` and `lvh` in pixels, and the viewport meta, live, keyboard up or
  down.

## Start at / finish at (added after 0.5.0)

- **The row:** a choice, "Avvia alle" or "Finisci alle", remembered on the
  device. Then the time field, and a second column whose label tells the
  other time: "Fine ≈ 15:21", or "Avvio alle 16:39". Both columns carry a
  label and sit level; the time field no longer spills over the button on
  iOS (`min-width: 0`, no native appearance).
- **The arithmetic:** with "Finisci alle" the start is the end minus the
  program's duration. A program with no duration known shows "Durata non
  nota"; an end too close for the duration shows "Troppo presto". Both
  disable the button. Peppina still sends the start itself at that moment.
- **The duration:** the real one of the program's last cycle when known,
  else the machine's estimate. Peppina keeps the real one at the end of
  each cycle (from hOn's activity start to the end the washer reports), and
  at setup from `retrieve-last-activity` (activityStarted to activityEnded).
  The chip and its line say which one it is.
- **hOn's app does the same**, judging by its dictionary
  (`WASHING_CMD&CTRL.SCHEDULE_CYCLE`): "Inizia alle" / "Finisce alle",
  "Durata %{duration}", "Inizio alle %{start} fine alle %{end}", within 24
  hours. It warns that the times "potrebbero subire variazioni a seconda
  del carico reale". Not measured: whether its delayTime counts to the start
  or to the end. Every start in hOn's history has delayTime 0, and finding
  out means scheduling a real wash. Peppina does not use delayTime.

## Not in this change
- **The card in other languages**: program names, descriptions and groups
  already follow Home Assistant's language, through the dictionary. The rest
  of the card is still Italian. The new strings sit in one table, so
  translating the card later means filling one table per language.

## Measured (2026-10-11)

- **Dictionary:** Italian is version 4368, downloaded and parsed in 0.2 s
  through `HonClient`. For a language it lacks, hOn answers with English
  (version 6222).
- **vjt's washer:**
  - All 92 programs get a name from the dictionary.
  - Groups: Tradizionali 20, Delicati 16, Sport 9, Rapidi 8, Casa 8,
    Macchie 6, Salute 6, Pets 3, Ariel 3, Dash 3, Eco 2, Baby 1,
    Business 1; 6 without a cluster.
  - The `programs` attribute is 29.5 KB.
- **Usage from the machine counters alone:** Smart A.I. 192, Eco 40-60 38,
  Baby Care 5, Cotone 4, Sintetici 4.
- **Card, checked in jsdom** against those 92 programs: 13 checks in
  `tests/card` (`npm install && npm test`).
  - field and chips;
  - the order of the sections, and the tags;
  - accent-insensitive search;
  - pick and close, Esc;
  - no rebuild on unrelated updates;
  - behaviour while unavailable;
  - the fallback without the attribute;
  - dictionary text never parsed as markup.
- **Home Assistant 2026.9.4 test** (outside the repo, which stays HA-free;
  11 checks):
  - the cache per dictionary version, shared by config entries, the
    language fallback, and no caching of an empty extraction;
  - counts persisted, only on accepted starts, before the refresh;
  - a broken entity does not hold up a stop;
  - the attribute and its exclusion from the recorder.
- **Not measured:**
  - **The look of the card in a real browser**: headless browsers cannot
    run in the sandbox the work was done in. Neither has the card been
    seen inside Home Assistant on a phone.
  - **Starts from Peppina and the machine's counters.** That a program
    started remotely, a variant included, moves its knob position's counter
    is assumed: the 192 → 193 of 2026-10-11 does not tell who started that
    cycle.
  - **Rough edges of the counting:**
    - Peppina counts a start when hOn accepts it, the machine counts a
      cycle when it ends. While a variant started by Peppina runs, its
      knob program shows one less.
    - A start that is accepted and then stopped keeps one count away from
      the knob program for good.

## Costs and follow-ups

- **The `programs` attribute (~30 KB):**
  - It is kept out of the recorder.
  - It is still in `core.restore_state` (the select restores its state),
    rewritten every 15 minutes.
  - It is in the select's attributes in the more-info dialog.
  - It goes to every `state_changed` consumer when it changes: at the end
    of a cycle (counters) and when the names land.
  - **Follow-up:** a `peppina/programs` websocket command that the card
    calls would avoid all three.
- **Android back** leaves the page instead of closing the sheet; handling
  it means going through the history API.
- **The rest of the card in other languages** (see "Not in this change").

## Testing

- **pytest** (`tests/`): the catalog against real trimmed data, the edge
  cases real data does not have, extraction from a dictionary fixture, the
  usage merge and the client's dictionary fetch.
- **jsdom** (`tests/card/`): the picker against the 92 real programs.
- **Home Assistant**, outside the repo: storage, counting, cache, the
  attribute.
- **Live**: the real dictionary download, and usage seeded from the real
  counters.
