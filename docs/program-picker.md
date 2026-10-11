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
  - **Most used**: up to 5 programs with usage above 0, most used first.
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

## Not in this change

- **Total duration**: hOn does not give it. `mainWashTime` is the main wash
  only.
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
- **Card, checked in jsdom against those 92 programs** (12 checks, outside
  the repo):
  - field and chips;
  - the order of the sections, and the tags;
  - accent-insensitive search;
  - pick and close;
  - no rebuild on unrelated updates;
  - the fallback without the attribute;
  - dictionary text never parsed as markup.
- **Home Assistant 2026.9.4 test** (outside the repo):
  - the cache per dictionary version and the language fallback;
  - counts persisted and only on accepted starts;
  - the attribute and its exclusion from the recorder.
- **Not measured:**
  - The look of the card in a real browser: headless browsers cannot run
    in the sandbox the work was done in.
  - The card inside Home Assistant on a phone.

## Testing

- **pytest**: the catalog against the dump fixtures, extraction from a
  dictionary fixture (a few keys of the public file), the usage merge, and
  the count on start.
- **Card**: a page outside the repo mounts the card with a fake `hass`, in
  headless Chrome, with phone and desktop screenshots.
- **Live**: the real dictionary download, and usage seeded from the real
  counters.
