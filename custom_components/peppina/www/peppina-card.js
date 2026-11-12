// Peppina card: the washing machine itself, full page, with its controls.
//
// Served by the integration (see dashboard.py) and dropped into the Peppina
// dashboard. The config maps roles to entity ids, e.g.
//   type: custom:peppina-card
//   name: Peppina
//   entities: {status: binary_sensor.x_status, mode: sensor.x_mode, ...}
// Missing roles are simply not shown.
//
// The cleanings (filter, drawer, drum) take three roles each: the counter
// sensor ("filter"), its due binary_sensor ("filter_due") and its done
// button ("filter_done"). A due one shows on the machine; tapped, it asks.
//
// The cycles it ran come with the last cycle end sensor ("cycles"), whose
// attribute holds the last few. `history`, written by the dashboard, is the
// path of the view where a peppina-history-card lists all of them.
//
// It speaks the frontend's language: Italian for Italian, English for any
// other. Program names and descriptions come from hOn, in Home Assistant's.

const SPIN_PHASES = new Set([3, 11]);

// hOn machMode for washers: 1 ready, 2 running, 3 paused, 5 timer, 6 error, 7 done
const MODE_RUNNING = 2;
const MODE_PAUSED = 3;
const MODE_TIMER = 5;
const MODE_DONE = 7;

const prettyProgram = (p) =>
  p.replace(/^(hqd|iot_wash)_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const pad = (n) => String(n).padStart(2, "0");
// HH:MM on 24 hours, as the machine's display and the time field show it.
const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
// Elsewhere times follow the user's profile: its language, and its 12 or 24
// hours when it picks one. hour12: false would make English midnight 24:00.
const timeFormat = (locale) => new Intl.DateTimeFormat(
  locale.time_format === "system" ? undefined : locale.language || undefined,
  { hour: "2-digit", minute: "2-digit", hourCycle: { 12: "h12", 24: "h23" }[locale.time_format] },
);

const duration = (minutes) => {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
};
const times = (n) => `${n}×`;
// How long the program takes: its last cycle when known, else the machine's
// estimate.
const estimate = (d) => `≈ ${duration(d.actual || d.minutes)}`;

// Every text the card shows, one table per language.
const STRINGS = {
  it: {
    description: "La lavatrice.",
    // hOn's program phases, by number.
    phases: {
      0: "Pronto", 1: "Lavaggio", 2: "Lavaggio", 3: "Centrifuga", 4: "Risciacquo",
      5: "Risciacquo", 6: "Risciacquo", 7: "Asciugatura", 8: "Asciugatura",
      9: "Vapore", 10: "Pronto", 11: "Centrifuga", 12: "Pesatura", 13: "Pesatura",
      14: "Lavaggio", 15: "Lavaggio", 16: "Lavaggio", 17: "Risciacquo",
      18: "Risciacquo", 19: "Programmato", 20: "Tumbling", 24: "Refresh",
      25: "Lavaggio", 26: "Riscaldamento", 27: "Lavaggio",
    },
    washing: "Lava",
    // What the machine says about itself, under it.
    sleeps: (name) => `${name} dorme`,
    off: "Spenta",
    error: "Errore",
    code: (code) => `Codice ${code}`,
    paused: "In pausa",
    scheduled: "Programmata",
    setsOff: (time) => `Parte alle ${time}`,
    machineTimer: "Timer della macchina",
    done: "Finita",
    doorOpen: "Sportello aperto",
    toHang: "Da stendere",
    ready: "Pronta",
    remoteOn: "Controllo remoto attivo",
    remoteOff: "Controllo remoto spento",
    remoteNeeded: "Attiva il controllo remoto sulla macchina",
    ends: (time) => `finisce alle ${time}`,
    // The controls.
    program: "Programma",
    temperature: "Temperatura",
    spinSpeed: "Centrifuga",
    start: "Avvia",
    stop: "Ferma",
    schedule: "Programma",
    cancel: "Annulla",
    cold: "Freddo",
    noSpin: "Niente",
    autoStart: "Avvio automatico",
    autoOn: "Attivo",
    autoOff: "Spento",
    startingIn: (left) => `Avvio in ${left}`,
    turnOff: "Spegni",
    turnOn: "Accendi",
    // The program picker.
    search: "Cerca programma",
    close: "Chiudi",
    mostUsed: "Più usati",
    others: "Altri",
    noMatch: "Nessun programma trovato",
    more: "Descrizione completa",
    tags: { guided: "guidato", care: "cura capi", download: "scaricato", featured: "in evidenza" },
    load: (kg) => `max ${kg.toLocaleString("it-IT")} kg`,
    temp: ([lo, hi]) => {
      const cold = "freddo";
      if (lo === hi) return lo === 0 ? cold : `${lo}°C`;
      return `${lo === 0 ? cold : lo}–${hi}°C`;
    },
    spin: (rpm) => `${rpm} giri`,
    // The settings the duration was for.
    estimateNote: ({ actual, temp, spin }) => {
      const at = [
        temp != null && (Number(temp) === 0 ? "a freddo" : `a ${temp}°C`),
        spin != null && (Number(spin) === 0 ? "senza centrifuga" : `${spin} giri`),
      ].filter(Boolean);
      const what = actual ? "Durata dell'ultimo lavaggio" : "Stima della macchina";
      return `${what}${at.length ? `, ${at.join(" e ")}` : ""}`;
    },
    // The schedule.
    startAt: "Avvia alle",
    endAt: "Finisci alle",
    startLabel: "Avvio alle",
    endLabel: "Fine alle",
    endsAround: (time) => `Fine ≈ ${time}`,
    startsAt: (time) => `Avvio alle ${time}`,
    noDuration: "Durata non nota",
    tooSoon: "Troppo presto",
    // The cleanings: what the machine says when one is due, what it asks.
    clean: {
      filter: { hint: "Pulisci il filtro!", ask: "Hai pulito il filtro?" },
      drawer: { hint: "Pulisci il cassetto!", ask: "Hai pulito il cassetto del detersivo?" },
      drum: { hint: "Autoclean?", ask: "Hai pulito il cestello?" },
    },
    cleanCount: (n) => (n === 1 ? "1 lavaggio dall'ultima pulizia" : `${n} lavaggi dall'ultima pulizia`),
    cleanYes: "Sì, fatto",
    cleanNo: "Non ancora",
    autoclean: "Avvia l'autoclean",
    autocleanNeedsRemote: "Per l'autoclean serve il controllo remoto",
    // The cycles it ran: the last one, the few before, the whole history.
    lastCycle: "Ultimo lavaggio",
    allCycles: "Tutti i lavaggi",
    cycles: "Lavaggi",
    cycleCount: (n) => (n === 1 ? "1 lavaggio" : `${n} lavaggi`),
    noCycles: "Nessun lavaggio registrato",
    loading: "Carico i lavaggi…",
    loadFailed: "Non riesco a leggere i lavaggi",
    finished: "Completato",
    interrupted: "Interrotto",
    unknownProgram: "Programma sconosciuto",
    today: "Oggi",
    yesterday: "Ieri",
  },
  en: {
    description: "The washing machine.",
    phases: {
      0: "Ready", 1: "Washing", 2: "Washing", 3: "Spinning", 4: "Rinsing",
      5: "Rinsing", 6: "Rinsing", 7: "Drying", 8: "Drying",
      9: "Steaming", 10: "Ready", 11: "Spinning", 12: "Weighing", 13: "Weighing",
      14: "Washing", 15: "Washing", 16: "Washing", 17: "Rinsing",
      18: "Rinsing", 19: "Scheduled", 20: "Tumbling", 24: "Refreshing",
      25: "Washing", 26: "Heating up", 27: "Washing",
    },
    washing: "Washing",
    sleeps: (name) => `${name} is napping`,
    off: "Switched off",
    error: "Error",
    code: (code) => `Code ${code}`,
    paused: "Paused",
    scheduled: "Scheduled",
    setsOff: (time) => `Sets off at ${time}`,
    machineTimer: "On the machine's timer",
    done: "All done",
    doorOpen: "Door open",
    toHang: "Waiting to be hung out",
    ready: "Ready",
    remoteOn: "Remote control on",
    remoteOff: "Remote control off",
    remoteNeeded: "Enable remote control on the machine",
    ends: (time) => `finishes at ${time}`,
    program: "Program",
    temperature: "Temperature",
    spinSpeed: "Spin",
    start: "Start",
    stop: "Stop",
    schedule: "Schedule",
    cancel: "Cancel",
    cold: "Cold",
    noSpin: "None",
    autoStart: "Auto start",
    autoOn: "On",
    autoOff: "Off",
    startingIn: (left) => `Starting in ${left}`,
    turnOff: "Turn off",
    turnOn: "Turn on",
    search: "Search programs",
    close: "Close",
    mostUsed: "Most used",
    others: "Others",
    noMatch: "No program found",
    more: "Full description",
    tags: { guided: "guided", care: "garment care", download: "downloaded", featured: "featured" },
    load: (kg) => `max ${kg.toLocaleString("en")} kg`,
    temp: ([lo, hi]) => {
      const cold = "cold";
      if (lo === hi) return lo === 0 ? cold : `${lo}°C`;
      return `${lo === 0 ? cold : lo}–${hi}°C`;
    },
    spin: (rpm) => `${rpm} rpm`,
    estimateNote: ({ actual, temp, spin }) => {
      const at = [
        temp != null && (Number(temp) === 0 ? "cold" : `at ${temp}°C`),
        spin != null && (Number(spin) === 0 ? "no spin" : `${spin} rpm`),
      ].filter(Boolean);
      const what = actual ? "How long the last wash took" : "The machine's own estimate";
      return `${what}${at.length ? `, ${at.join(" and ")}` : ""}`;
    },
    startAt: "Start at",
    endAt: "Finish by",
    startLabel: "Starts at",
    endLabel: "Done by",
    endsAround: (time) => `Done ≈ ${time}`,
    startsAt: (time) => `Starts at ${time}`,
    noDuration: "Duration unknown",
    tooSoon: "Too soon",
    clean: {
      filter: { hint: "Clean the filter!", ask: "Did you clean the filter?" },
      drawer: { hint: "Clean the drawer!", ask: "Did you clean the detergent drawer?" },
      drum: { hint: "Autoclean?", ask: "Did you clean the drum?" },
    },
    cleanCount: (n) => (n === 1 ? "1 wash since the last clean" : `${n} washes since the last clean`),
    cleanYes: "Yes, done",
    cleanNo: "Not yet",
    autoclean: "Start the autoclean",
    autocleanNeedsRemote: "The autoclean needs remote control on",
    lastCycle: "Last wash",
    allCycles: "All washes",
    cycles: "Washes",
    cycleCount: (n) => (n === 1 ? "1 wash" : `${n} washes`),
    noCycles: "No washes recorded yet",
    loading: "Loading the washes…",
    loadFailed: "Could not read the washes",
    finished: "Finished",
    interrupted: "Interrupted",
    unknownProgram: "Unknown program",
    today: "Today",
    yesterday: "Yesterday",
  },
};
// Italian for Italian, English for any other language.
const textsFor = (language) => (/^it(-|$)/i.test(language || "") ? STRINGS.it : STRINGS.en);

const MOST_USED = 10;
const CLEANINGS = ["filter", "drawer", "drum"];
// Drum clean programs, the first the machine has wins.
const AUTOCLEAN = ["hqd_autoclean", "iot_wash_quick_drum_cleaner"];

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const fold = (text) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
const tagged = (p, t) => (p.tag ? `${p.name} · ${t.tags[p.tag] || p.tag}` : p.name);
const facts = (p, t) => [
  p.duration && estimate(p.duration),
  p.load && t.load(p.load),
  p.temp && t.temp(p.temp),
  p.spin && t.spin(p.spin),
].filter(Boolean);

// The cycles it ran, as the integration logs them: {program, start, end,
// minutes, outcome, temp, spin}. Programs go by the names the picker shows.
const programLabel = (key, programs, t) => {
  if (!key) return t.unknownProgram;
  const p = programs.find((x) => x.key === key);
  return p ? tagged(p, t) : prettyProgram(key);
};
const cycleSettings = (c, t) => [
  c.temp != null && t.temp([c.temp, c.temp]),
  c.spin ? t.spin(c.spin) : null,
].filter(Boolean);
const outcome = (c, t) => (c.outcome === "interrupted"
  ? el("span", "badge stopped", t.interrupted)
  : el("span", "badge", t.finished));
const dayFormat = (locale) => new Intl.DateTimeFormat(
  locale.language || undefined, { weekday: "short", day: "numeric", month: "short" },
);
const monthFormat = (locale) => new Intl.DateTimeFormat(
  locale.language || undefined, { month: "long", year: "numeric" },
);
// Today, yesterday, else the date.
const dayLabel = (date, t, format) => {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === now.toDateString()) return t.today;
  if (date.toDateString() === yesterday.toDateString()) return t.yesterday;
  return format.format(date).replace(/^\p{Ll}/u, (c) => c.toUpperCase());
};
// To another view of the dashboard, the way the frontend's own links go.
const navigate = (path) => {
  window.history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
};

// ?peppina_viewport in the dashboard URL shows how the browser sizes the
// page, to see what a webview does with the keyboard (docs/program-picker.md).
function viewportProbe(root) {
  if (!new URLSearchParams(location.search).has("peppina_viewport")) return;
  const box = el("div", "vprobe");
  const units = ["vh", "dvh", "svh", "lvh"].map((unit) => {
    const probe = el("div", "vunit");
    probe.style.height = `100${unit}`;
    root.append(probe);
    return [unit, probe];
  });
  const meta = document.querySelector('meta[name="viewport"]');
  const show = () => {
    const vv = window.visualViewport;
    box.textContent = [
      `window ${innerWidth}×${innerHeight}`,
      vv
        ? `visual ${Math.round(vv.width)}×${Math.round(vv.height)} @${Math.round(vv.offsetTop)} ×${vv.scale}`
        : "no visualViewport",
      units.map(([unit, probe]) => `100${unit}=${probe.offsetHeight}`).join(" "),
      `meta ${meta ? meta.content : "-"}`,
    ].join("\n");
  };
  root.append(box);
  show();
  for (const target of [window.visualViewport, window].filter(Boolean)) {
    target.addEventListener("resize", show);
    target.addEventListener("scroll", show);
  }
  document.addEventListener("focusin", show);
}

// The program field and its sheet: search, the most used first, then hOn's
// groups in the order the integration sorted them. Plain DOM in the card's
// shadow root; texts only ever go through textContent.
class ProgramPicker {
  constructor(root, t, onPick) {
    const $ = (sel) => root.querySelector(sel);
    this.t = t;
    this.$ = {
      box: $(".programbox"), field: $(".field"), name: $(".pname"), desc: $(".pdesc"),
      chips: $(".pchips"), note: $(".pnote"), sheet: $(".sheet"), search: $(".search"),
      list: $(".list"),
    };
    this._onPick = onPick;
    this._programs = [];
    this._onKey = (e) => e.key === "Escape" && this.close();
    this._fit = () => this._fitViewport();
    this.$.field.addEventListener("click", () => this.open());
    $(".close").addEventListener("click", () => this.close());
    $(".backdrop").addEventListener("click", () => this.close());
    this.$.search.addEventListener("input", () => {
      this.$.list.scrollTop = 0;
      this._render();
    });
    // The whole description, two lines until tapped.
    this.$.desc.addEventListener("click", () => this.$.desc.classList.toggle("full"));
    this.$.list.addEventListener("click", (e) => {
      const more = e.target.closest(".pexp");
      if (more) {
        const row = more.closest(".prow");
        more.setAttribute("aria-expanded", String(row.classList.toggle("full")));
        return;
      }
      const row = e.target.closest(".prow");
      if (row) this._pick(row);
    });
    this.$.list.addEventListener("keydown", (e) => {
      const row = e.target.classList && e.target.classList.contains("prow") && e.target;
      if (row && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        this._pick(row);
      }
    });
  }

  _pick(row) {
    this.close();
    if (row.dataset.key !== this._value) this._onPick(row.dataset.key);
  }

  // sel: the program select's state, a new object whenever it changes.
  update(sel) {
    this.$.box.classList.toggle("hidden", !sel);
    if (!sel || sel === this._sel) return;
    this._sel = sel;
    // Unavailable, the state has lost its attributes: keep what was shown.
    if (["unavailable", "unknown"].includes(sel.state)) {
      this.$.field.disabled = true;
      this.close();
      return;
    }
    const options = sel.attributes.options || [];
    this._programs = sel.attributes.programs
      || options.map((key) => ({ key, name: prettyProgram(key), description: "", usage: 0 }));
    this._value = sel.state;
    this.$.field.disabled = options.length < 2;
    const p = this._programs.find((x) => x.key === sel.state);
    this.$.name.textContent = p ? tagged(p, this.t) : prettyProgram(sel.state || "");
    this.$.desc.textContent = (p && p.description) || "";
    this.$.desc.classList.remove("full");
    this.$.chips.replaceChildren(...(p ? facts(p, this.t) : []).map((f) => el("span", "chip", f)));
    this.$.note.textContent = p && p.duration ? this.t.estimateNote(p.duration) : "";
    if (this.isOpen) this._render();
  }

  get isOpen() {
    return !this.$.sheet.classList.contains("hidden");
  }

  open() {
    this.$.search.value = "";
    this.$.sheet.classList.remove("hidden");
    document.addEventListener("keydown", this._onKey);
    const vv = window.visualViewport;
    if (vv) {
      vv.addEventListener("resize", this._fit);
      vv.addEventListener("scroll", this._fit);
      this._fitViewport();
    }
    this.$.list.scrollTop = 0;
    this._render();
    const sel = this.$.list.querySelector(".prow.sel");
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest" });
    if (window.matchMedia && matchMedia("(pointer: fine)").matches) this.$.search.focus();
  }

  close() {
    if (!this.isOpen) return;
    this.$.sheet.classList.add("hidden");
    document.removeEventListener("keydown", this._onKey);
    const vv = window.visualViewport;
    if (vv) {
      vv.removeEventListener("resize", this._fit);
      vv.removeEventListener("scroll", this._fit);
    }
    for (const prop of ["top", "bottom", "height"]) this.$.sheet.style.removeProperty(prop);
    this.$.field.focus({ preventScroll: true });
  }

  // The keyboard covers the bottom of the page without shrinking it: on iOS
  // always, and anywhere with Home Assistant's viewport meta, which has no
  // interactive-widget. Pinned to the visual viewport, the sheet stays above.
  _fitViewport() {
    const vv = window.visualViewport;
    const style = this.$.sheet.style;
    style.top = `${vv.offsetTop}px`;
    style.bottom = "auto";
    style.height = `${vv.height}px`;
  }

  _render() {
    const t = this.t;
    const query = fold(this.$.search.value.trim());
    const shown = query
      ? this._programs.filter((p) =>
        fold(`${p.name} ${p.description} ${p.group_name || ""}`).includes(query))
      : this._programs;
    const nodes = [];
    // Searching, the groups say enough: the most used would repeat them.
    const top = query ? [] : shown.filter((p) => p.usage > 0)
      .sort((a, b) => b.usage - a.usage).slice(0, MOST_USED);
    if (top.length) nodes.push(el("div", "group", t.mostUsed), ...top.map((p) => this._row(p)));
    let group;
    for (const p of shown) {
      const name = p.group_name || t.others;
      if (name !== group) nodes.push(el("div", "group", (group = name)));
      nodes.push(this._row(p));
    }
    if (!shown.length) nodes.push(el("div", "empty", t.noMatch));
    const scroll = this.$.list.scrollTop;
    this.$.list.replaceChildren(...nodes);
    this.$.list.scrollTop = scroll;
  }

  _row(p) {
    const t = this.t;
    // Not a button: it holds the button that opens the whole description.
    const row = el("div", p.key === this._value ? "prow sel" : "prow");
    row.setAttribute("role", "button");
    row.tabIndex = 0;
    row.dataset.key = p.key;
    const head = el("span", "ptop");
    head.append(el("span", "pn", p.name));
    if (p.tag) head.append(el("span", "ptag", t.tags[p.tag] || p.tag));
    for (const pill of [p.temp && t.temp(p.temp), p.spin && t.spin(p.spin)]) {
      if (pill) head.append(el("span", "ppill", pill));
    }
    const meta = [
      p.duration && duration(p.duration.actual || p.duration.minutes),
      p.usage > 0 ? times(p.usage) : !p.duration && p.load && t.load(p.load),
    ].filter(Boolean).join(" · ");
    if (meta) head.append(el("span", "pmeta", meta));
    row.append(head);
    if (p.description) {
      const line = el("div", "pdline");
      const more = el("button", "pexp", "▾");
      more.type = "button";
      more.setAttribute("aria-label", t.more);
      more.setAttribute("aria-expanded", "false");
      line.append(el("span", "pd", p.description), more);
      row.append(line);
    }
    return row;
  }
}

// The cycles, on the card and on the history page.
const CYCLE_STYLE = `
  .badge {
    flex: none; font-size: 0.75em; font-weight: 600; padding: 2px 9px; border-radius: 999px;
    white-space: nowrap; background: rgba(54, 226, 127, 0.16); color: var(--success-color, #2e9d5b);
  }
  .badge.stopped { background: rgba(255, 170, 0, 0.18); color: var(--warning-color, #b36b00); }
  .label {
    font-size: 0.72em; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    opacity: 0.55;
  }
  .cchips { display: flex; flex-wrap: wrap; gap: 6px; }
  .cchips:empty { display: none; }
  .cchips .chip { padding: 3px 9px; font-size: 0.8em; }
`;

const STYLE = `
  :host { display: block; height: 100%; }
  .wrap {
    min-height: calc(100vh - var(--header-height, 56px));
    box-sizing: border-box;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 20px; padding: 16px;
    background: radial-gradient(ellipse at 50% 30%, var(--pp-glow) 0%, transparent 60%),
                var(--primary-background-color);
    --pp-glow: rgba(80, 160, 255, 0.10);
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
    color: var(--primary-text-color);
  }
  .wrap.washing { --pp-glow: rgba(80, 160, 255, 0.28); }
  .wrap.spinning { --pp-glow: rgba(120, 200, 255, 0.40); }
  .wrap.error { --pp-glow: rgba(255, 80, 80, 0.25); }

  .stage { width: min(78vw, 56vh, 520px); position: relative; }
  svg { width: 100%; height: auto; display: block; overflow: visible; }

  .machine { transform-origin: 50% 100%; transform-box: fill-box; }
  .washing .machine { animation: wobble 0.9s ease-in-out infinite; }
  .spinning .machine { animation: shake 0.12s linear infinite; }
  @keyframes wobble {
    0%, 100% { transform: translateX(0) rotate(0); }
    25% { transform: translateX(-3px) rotate(-0.8deg); }
    75% { transform: translateX(3px) rotate(0.8deg); }
  }
  @keyframes shake {
    0% { transform: translate(0, 0) rotate(0); }
    25% { transform: translate(-4px, -2px) rotate(-1.2deg); }
    50% { transform: translate(3px, 1px) rotate(0.6deg); }
    75% { transform: translate(-2px, -3px) rotate(1.2deg); }
    100% { transform: translate(0, 0) rotate(0); }
  }

  .drum { transform-origin: 200px 300px; }
  .washing .drum { animation: spin 2.4s linear infinite; }
  .spinning .drum { animation: spin 0.35s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .water { transition: transform 1.2s ease; transform: translateY(160px); }
  .washing .water { transform: translateY(40px); }
  .spinning .water { transform: translateY(110px); }
  .wave { animation: wave 3s linear infinite; }
  .spinning .wave { animation-duration: 0.8s; }
  @keyframes wave { to { transform: translateX(-160px); } }

  .bubble { opacity: 0; }
  .washing .bubble, .spinning .bubble { animation: rise 2.6s ease-in infinite; }
  .bubble:nth-of-type(2) { animation-delay: 0.6s !important; }
  .bubble:nth-of-type(3) { animation-delay: 1.3s !important; }
  .bubble:nth-of-type(4) { animation-delay: 1.9s !important; }
  @keyframes rise {
    0% { opacity: 0; transform: translateY(0); }
    20% { opacity: 0.8; }
    100% { opacity: 0; transform: translateY(-90px); }
  }

  .door { transform-origin: 92px 300px; transition: transform 0.8s ease; }
  .open .door { transform: perspective(600px) rotateY(-62deg); }

  .lcd { font: 700 30px/1 ui-monospace, "SF Mono", Menlo, monospace; fill: #7dffb2; }
  .paused .lcd, .error .lcd { animation: blink 1s steps(2) infinite; }
  .error .lcd { fill: #ff6b6b; }
  @keyframes blink { 50% { opacity: 0.2; } }
  .led { fill: #2a3a33; }
  .washing .led, .spinning .led { fill: #36e27f; filter: drop-shadow(0 0 4px #36e27f); }
  .error .led { fill: #ff4d4d; }

  /* A cleaning due: its part of the machine calls, and a tap asks. */
  .hint { font: 700 13px/1 system-ui, sans-serif; fill: #e07a00; opacity: 0; }
  .due-filter .hint.filter, .due-drawer .hint.drawer, .due-drum .hint.drum { opacity: 1; }
  .due-filter [data-clean=filter], .due-drawer [data-clean=drawer],
  .due-drum [data-clean=drum] { cursor: pointer; }
  @keyframes nudge {
    50% { stroke: #ff9f1c; stroke-width: 3; filter: drop-shadow(0 0 6px #ff9f1c); }
  }
  .due-filter .hatch rect, .due-drawer .drawer .front { animation: nudge 1s ease-in-out infinite; }
  .drawer { transition: transform 0.6s ease; }
  .due-drawer .drawer { transform: translate(-5px, 8px); filter: drop-shadow(0 4px 3px rgba(0,0,0,0.3)); }
  .slot { opacity: 0; transition: opacity 0.6s ease; }
  .due-drawer .slot { opacity: 1; }
  .suds circle { opacity: 0; transform-box: fill-box; transform-origin: center; }
  .due-drum:not(.washing):not(.spinning) .suds circle { animation: fizz 2.4s ease-in-out infinite; }
  .suds circle:nth-child(2) { animation-delay: 0.4s !important; }
  .suds circle:nth-child(3) { animation-delay: 0.9s !important; }
  .suds circle:nth-child(4) { animation-delay: 1.3s !important; }
  .suds circle:nth-child(5) { animation-delay: 1.8s !important; }
  .suds circle:nth-child(6) { animation-delay: 2.1s !important; }
  @keyframes fizz {
    0% { opacity: 0; transform: translateY(0) scale(0.5); }
    30% { opacity: 0.9; }
    100% { opacity: 0; transform: translateY(-50px) scale(1.2); }
  }
  .ask {
    position: fixed; inset: 0; z-index: 10;
    display: flex; align-items: center; justify-content: center; padding: 16px;
  }
  .ask .backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.45); }
  .askbox {
    position: relative; width: min(100%, 380px); box-sizing: border-box;
    display: flex; flex-direction: column; gap: 12px; padding: 20px;
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    border-radius: 20px; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25); text-align: center;
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
  }
  .askq { font-size: 1.2em; font-weight: 600; }
  .asknote { font-size: 0.85em; opacity: 0.7; }
  .asknote:empty { display: none; }

  .shadow { transform-origin: 200px 548px; }
  .spinning .shadow { animation: pulse 0.12s linear infinite; }
  @keyframes pulse { 50% { transform: scaleX(0.94); } }

  .status {
    text-align: center; display: flex; flex-direction: column; gap: 4px;
  }
  .status .big { font-size: 1.6em; font-weight: 600; letter-spacing: 0.01em; }
  .status .small { opacity: 0.7; }

  .panel {
    width: min(100%, 560px); box-sizing: border-box;
    background: var(--card-background-color, #fff);
    border-radius: 20px; padding: 16px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.12);
    display: flex; flex-direction: column; gap: 14px;
  }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
  .chip {
    padding: 6px 12px; border-radius: 999px; font-size: 0.9em;
    background: var(--secondary-background-color, #eee);
  }
  .chip.warn { background: rgba(255, 170, 0, 0.18); color: var(--warning-color, #b36b00); }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .row > * { flex: 1 1 140px; min-width: 0; }
  .sched { align-items: flex-end; }
  .btns { display: flex; gap: 10px; }
  .btns > button { flex: 1; min-width: 0; }
  .seg { display: flex; gap: 6px; }
  .seg button { flex: 1; padding: 6px 10px; font-size: 0.85em; }
  .seg button.on { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
  label { font-size: 0.8em; opacity: 0.7; display: block; margin-bottom: 4px; }
  select, input[type=time] {
    width: 100%; box-sizing: border-box; font: inherit; font-size: 1em;
    padding: 10px 12px; border-radius: 12px;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--primary-background-color); color: var(--primary-text-color);
  }
  /* iOS gives time fields a width of their own, past their column. */
  input[type=time] {
    display: block; min-width: 0; max-width: 100%; min-height: 2.75em;
    -webkit-appearance: none; appearance: none;
  }
  button {
    font: inherit; font-weight: 600; font-size: 1em; cursor: pointer;
    padding: 12px 16px; border-radius: 14px; border: none;
    background: var(--secondary-background-color, #eee); color: var(--primary-text-color);
    transition: transform 0.1s ease, filter 0.2s ease;
  }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.4; cursor: default; }
  button.go { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
  button.stop { background: var(--error-color, #db4437); color: #fff; }

  .field {
    width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px;
    text-align: left; font-weight: normal; padding: 10px 12px; border-radius: 12px;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--primary-background-color); color: var(--primary-text-color);
  }
  .field .caret { opacity: 0.6; }
  .pdesc {
    font-size: 0.85em; opacity: 0.75; margin-top: 6px; line-height: 1.35;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .pdesc:empty { display: none; }
  .pdesc { cursor: pointer; }
  .pdesc.full { display: block; -webkit-line-clamp: unset; overflow: visible; }
  .pchips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .pchips .chip { padding: 3px 9px; font-size: 0.8em; }
  .pnote { font-size: 0.75em; opacity: 0.6; margin-top: 4px; }
  .pnote:empty { display: none; }
  .sheet {
    position: fixed; inset: 0; z-index: 10;
    display: flex; align-items: flex-end; justify-content: center;
  }
  .sheet .backdrop {
    position: absolute; inset: 0; background: rgba(0, 0, 0, 0.45); touch-action: none;
  }
  .sheetbox {
    position: relative; width: min(100%, 560px); max-height: 85%; box-sizing: border-box;
    display: flex; flex-direction: column;
    background: var(--card-background-color, #fff); color: var(--primary-text-color);
    border-radius: 20px 20px 0 0; box-shadow: 0 -8px 30px rgba(0, 0, 0, 0.25);
    padding-bottom: env(safe-area-inset-bottom);
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
  }
  .sheethead { display: flex; gap: 8px; padding: 12px; touch-action: none; }
  .sheethead .search {
    flex: 1; min-width: 0; box-sizing: border-box; font: inherit;
    font-size: max(16px, 1em); /* smaller, iOS zooms the page on focus */
    padding: 10px 12px; border-radius: 12px; border: 1px solid var(--divider-color, #ccc);
    background: var(--primary-background-color); color: var(--primary-text-color);
  }
  .sheethead .close { padding: 10px 14px; }
  .list { overflow-y: auto; overscroll-behavior: contain; padding: 0 8px 12px; }
  .group {
    font-size: 0.72em; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    opacity: 0.55; padding: 14px 10px 4px;
  }
  .prow {
    display: block; box-sizing: border-box; width: 100%; text-align: left; cursor: pointer;
    border-radius: 12px; padding: 9px 10px;
  }
  .prow:hover { background: var(--secondary-background-color, #eee); }
  .prow.sel { background: rgba(3, 169, 244, 0.14); }
  .ptop { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .pn { font-weight: 600; min-width: 0; }
  .ptag {
    font-size: 0.72em; padding: 1px 7px; border-radius: 999px; white-space: nowrap;
    background: var(--secondary-background-color, #eee);
  }
  .ppill {
    flex: none; font-size: 0.72em; padding: 1px 7px; border-radius: 999px; white-space: nowrap;
    background: var(--secondary-background-color, #eee);
  }
  .pmeta { flex: none; margin-left: auto; font-size: 0.8em; opacity: 0.6; white-space: nowrap; }
  .pdline { display: flex; align-items: flex-start; gap: 4px; margin-top: 2px; }
  .pd {
    flex: 1; min-width: 0; font-size: 0.82em; opacity: 0.65;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .prow.full .pd { white-space: normal; }
  .pexp {
    flex: none; padding: 0 6px; background: none; font-weight: normal; font-size: 0.8em;
    opacity: 0.6; transition: transform 0.15s ease;
  }
  .prow.full .pexp { transform: rotate(180deg); }
  .empty { padding: 24px; text-align: center; opacity: 0.6; }
  .vprobe {
    position: fixed; top: 4px; left: 4px; z-index: 20; pointer-events: none;
    background: rgba(0, 0, 0, 0.75); color: #7CFC00; font: 11px/1.3 monospace;
    padding: 6px 8px; border-radius: 6px; white-space: pre;
  }
  .vunit { position: fixed; top: 0; left: -10px; width: 1px; visibility: hidden; }
  @media (min-width: 700px) {
    .sheet { align-items: center; }
    .sheetbox { border-radius: 20px; max-height: 80%; }
  }
  ${CYCLE_STYLE}
  .panel.cycles { gap: 8px; }
  .chead { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .call {
    padding: 0; background: none; font-size: 0.85em; color: var(--primary-color, #03a9f4);
  }
  .ctop { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .cname { font-size: 1.15em; font-weight: 600; min-width: 0; }
  .cline { font-size: 0.9em; opacity: 0.75; }
  .clist {
    max-height: 9.5em; overflow-y: auto; overscroll-behavior: contain;
    border-top: 1px solid var(--divider-color, #ddd);
  }
  .crow { display: flex; align-items: baseline; gap: 8px; padding: 7px 2px; font-size: 0.88em; }
  .crow + .crow { border-top: 1px solid var(--divider-color, #eee); }
  .cday, .cdur { flex: none; opacity: 0.65; white-space: nowrap; }
  .cprog { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .crow .badge { font-size: 0.7em; }
  .hidden { display: none !important; }
  .side { display: flex; flex-direction: column; align-items: center; gap: 20px;
          width: min(100%, 560px); }
  @media (min-width: 900px) and (min-aspect-ratio: 1/1) {
    .wrap { flex-direction: row; gap: 48px; }
    .stage { width: min(48vw, 78vh, 640px); }
    .side { width: min(36vw, 480px); }
    .status { text-align: left; align-self: stretch; }
    .status .big { font-size: 2.2em; }
  }
`;

const svg = (t) => `
<svg viewBox="0 0 400 560" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="body" x1="0" x2="1">
      <stop offset="0" stop-color="#e9edf2"/><stop offset="0.5" stop-color="#ffffff"/>
      <stop offset="1" stop-color="#d9dfe6"/>
    </linearGradient>
    <linearGradient id="panel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f6f8fa"/><stop offset="1" stop-color="#dfe4ea"/>
    </linearGradient>
    <radialGradient id="ring" cx="0.5" cy="0.4" r="0.6">
      <stop offset="0.7" stop-color="#cfd6de"/><stop offset="1" stop-color="#8b96a3"/>
    </radialGradient>
    <radialGradient id="glass" cx="0.4" cy="0.35" r="0.75">
      <stop offset="0" stop-color="#3b4a5a"/><stop offset="1" stop-color="#121a24"/>
    </radialGradient>
    <linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#6cc4ff" stop-opacity="0.85"/>
      <stop offset="1" stop-color="#1f6fd1" stop-opacity="0.9"/>
    </linearGradient>
    <clipPath id="window"><circle cx="200" cy="300" r="108"/></clipPath>
  </defs>

  <ellipse class="shadow" cx="200" cy="548" rx="170" ry="10" fill="rgba(0,0,0,0.25)"/>

  <g class="machine">
    <rect x="30" y="20" width="340" height="510" rx="26" fill="url(#body)"
          stroke="#b9c2cc" stroke-width="2"/>
    <rect x="30" y="20" width="340" height="110" rx="26" fill="url(#panel)"/>
    <rect x="30" y="104" width="340" height="26" fill="url(#panel)"/>
    <line x1="30" y1="130" x2="370" y2="130" stroke="#c3cbd4" stroke-width="2"/>

    <rect class="slot" x="50" y="42" width="74" height="48" rx="7" fill="#3a4450"/>
    <g class="drawer" data-clean="drawer" role="button" aria-label="${t.clean.drawer.hint}">
      <rect class="front" x="52" y="44" width="70" height="44" rx="6" fill="#e3e8ee" stroke="#c3cbd4"/>
      <rect x="58" y="50" width="28" height="32" rx="3" fill="#d2d9e0"/>
      <rect x="90" y="50" width="26" height="32" rx="3" fill="#d2d9e0"/>
    </g>
    <text class="hint drawer" data-clean="drawer" x="50" y="120">${t.clean.drawer.hint}</text>

    <rect x="150" y="40" width="130" height="54" rx="10" fill="#0f1712"/>
    <text class="lcd" x="215" y="78" text-anchor="middle">--:--</text>

    <circle cx="326" cy="67" r="24" fill="url(#ring)" stroke="#9aa5b1" stroke-width="2"/>
    <rect x="323" y="46" width="6" height="16" rx="3" fill="#6b7682"/>
    <circle class="led" cx="296" cy="100" r="5"/>

    <circle cx="200" cy="300" r="138" fill="url(#ring)" stroke="#a5afba" stroke-width="2"/>
    <circle cx="200" cy="300" r="120" fill="#5c6875"/>

    <g clip-path="url(#window)">
      <circle cx="200" cy="300" r="108" fill="url(#glass)"/>
      <g class="drum">
        <circle cx="200" cy="300" r="104" fill="none" stroke="#2c3946" stroke-width="3"
                stroke-dasharray="4 10"/>
        <path d="M150 330 q20 -40 50 -10 q25 25 45 -5 q10 30 -25 45 q-40 15 -70 -30z"
              fill="#e85d75" opacity="0.9"/>
        <path d="M205 245 q35 -15 50 15 q10 25 -20 30 q-30 5 -45 -20z" fill="#ffd166" opacity="0.9"/>
        <path d="M150 260 q15 -25 40 -10 q15 15 -5 30 q-25 15 -35 -20z" fill="#06d6a0" opacity="0.9"/>
        <path d="M230 320 q25 10 15 35 q-15 20 -35 0z" fill="#8ecae6" opacity="0.9"/>
      </g>
      <g class="water">
        <g class="wave">
          <path d="M40 300 q20 -12 40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0 t40 0
                   t40 0 t40 0 v200 h-480z" fill="url(#water)"/>
        </g>
      </g>
      <circle class="bubble" cx="170" cy="370" r="5" fill="#bfe6ff"/>
      <circle class="bubble" cx="230" cy="380" r="4" fill="#bfe6ff"/>
      <circle class="bubble" cx="200" cy="390" r="6" fill="#bfe6ff"/>
      <circle class="bubble" cx="250" cy="365" r="3" fill="#bfe6ff"/>
      <g class="suds">
        <circle cx="160" cy="330" r="9" fill="#e8f6ff" stroke="#bfe6ff"/>
        <circle cx="215" cy="345" r="6" fill="#e8f6ff" stroke="#bfe6ff"/>
        <circle cx="245" cy="320" r="10" fill="#e8f6ff" stroke="#bfe6ff"/>
        <circle cx="185" cy="290" r="5" fill="#e8f6ff" stroke="#bfe6ff"/>
        <circle cx="230" cy="275" r="7" fill="#e8f6ff" stroke="#bfe6ff"/>
        <circle cx="175" cy="360" r="6" fill="#e8f6ff" stroke="#bfe6ff"/>
      </g>
      <path d="M135 245 a95 95 0 0 1 60 -45" stroke="rgba(255,255,255,0.35)"
            stroke-width="10" stroke-linecap="round" fill="none"/>
    </g>

    <g class="door">
      <circle cx="200" cy="300" r="120" fill="none" stroke="#d5dce3" stroke-width="10"/>
      <rect x="312" y="282" width="16" height="36" rx="6" fill="#9aa5b1"/>
    </g>

    <rect x="60" y="460" width="280" height="44" rx="10" fill="none" stroke="#c9d1d9"
          stroke-width="2"/>
    <g class="hatch" data-clean="filter" role="button" aria-label="${t.clean.filter.hint}">
      <rect x="292" y="468" width="38" height="28" rx="6" fill="#e3e8ee" stroke="#c3cbd4"/>
      <circle cx="311" cy="482" r="6" fill="none" stroke="#b9c2cc" stroke-width="2"/>
    </g>
    <text class="hint filter" data-clean="filter" x="282" y="487" text-anchor="end">${t.clean.filter.hint}</text>
    <circle data-clean="drum" cx="200" cy="300" r="120" fill="transparent"/>
    <text class="hint drum" data-clean="drum" x="200" y="453" text-anchor="middle">${t.clean.drum.hint}</text>
  </g>
</svg>`;

class PeppinaCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entities) throw new Error("peppina-card: entities required");
    this._config = config;
    this._built = false;
  }

  getCardSize() {
    return 12;
  }

  disconnectedCallback() {
    clearTimeout(this._tick);
  }

  set hass(hass) {
    this._hass = hass;
    // The language and the time format of the user's profile.
    const locale = hass.locale || { language: hass.language };
    const key = `${locale.language}|${locale.time_format}`;
    if (key !== this._localeKey) {
      this._localeKey = key;
      this._timeFormat = timeFormat(locale);
      this._dayFormat = dayFormat(locale);
      this._cyclesShown = undefined;
      const t = textsFor(locale.language);
      if (t !== this.t) {
        // Another language: the card is built again, in it.
        if (this.picker) this.picker.close();
        this.t = t;
        this._built = false;
      }
    }
    if (!this._built) this._build();
    this._update();
  }

  _clock(date) {
    return this._timeFormat.format(date);
  }

  _id(role) {
    return this._config.entities[role];
  }

  _state(role) {
    const id = this._id(role);
    return id ? this._hass.states[id] : undefined;
  }

  _val(role) {
    const s = this._state(role);
    return s && !["unknown", "unavailable"].includes(s.state) ? s.state : undefined;
  }

  // Minutes the selected program takes: its last cycle, else the machine's estimate.
  _duration() {
    const sel = this._state("select");
    const programs = (sel && sel.attributes.programs) || [];
    const p = sel && programs.find((x) => x.key === sel.state);
    return p && p.duration ? p.duration.actual || p.duration.minutes : undefined;
  }

  // What a schedule would do with the time typed: in "Avvia alle" start
  // then (and end after the program's duration, when known); in "Finisci
  // alle" start the duration before. {start, end} or {error}.
  _plan() {
    const value = this.$.when.value || "";
    const [h, m] = value.split(":").map(Number);
    if (!value || !Number.isFinite(h) || !Number.isFinite(m)) return undefined;
    const at = new Date();
    at.setHours(h, m, 0, 0);
    if (at <= new Date()) at.setDate(at.getDate() + 1);
    const minutes = this._duration();
    if (this._mode === "start") {
      return { start: at, end: minutes ? new Date(at.getTime() + minutes * 60000) : undefined };
    }
    if (!minutes) return { error: this.t.noDuration };
    const start = new Date(at.getTime() - minutes * 60000);
    return start <= new Date() ? { error: this.t.tooSoon } : { start, end: at };
  }

  _updateSchedule() {
    for (const button of this.$.modes) button.classList.toggle("on", button.dataset.mode === this._mode);
    this.$.wlabel.textContent = this._mode === "start" ? this.t.startLabel : this.t.endLabel;
    const plan = this._plan();
    let other = "\u00a0";  // keeps the two columns level
    if (plan && plan.error) other = plan.error;
    else if (plan && this._mode === "end") other = this.t.startsAt(this._clock(plan.start));
    else if (plan && plan.end) other = this.t.endsAround(this._clock(plan.end));
    this.$.other.textContent = other;
    this.$.schedule.disabled = !this._canSchedule || !plan || !!plan.error;
  }

  // The running program as the picker names it, and when the cycle ends.
  _cycleLine(end) {
    const key = this._val("program");
    const known = key && key !== "No program";
    const programs = ((this._state("select") || {}).attributes || {}).programs || [];
    const p = known && programs.find((x) => x.key === key);
    const name = p ? tagged(p, this.t) : known ? prettyProgram(key) : "";
    const ends = end ? this.t.ends(this._clock(end)) : "";
    const line = [name, ends].filter(Boolean).join(" · ");
    return line.charAt(0).toUpperCase() + line.slice(1);
  }

  _call(domain, service, role, data = {}) {
    const id = this._id(role);
    if (!id) return undefined;
    return this._hass.callService(domain, service, { entity_id: id, ...data });
  }

  _due(clean) {
    return this._val(`${clean}_due`) === "on";
  }

  // The drum clean program the machine has, if the card can start one.
  _autocleanProgram() {
    const sel = this._state("select");
    const options = (sel && sel.attributes.options) || [];
    return this._id("start") ? AUTOCLEAN.find((p) => options.includes(p)) : undefined;
  }

  _ask(clean) {
    if (!this._due(clean) || !this._id(`${clean}_done`)) return;
    this._asking = clean;
    const count = Number((this._state(clean) || { attributes: {} }).attributes.count);
    this.$.askq.textContent = this.t.clean[clean].ask;
    this.$.asknote.textContent = Number.isFinite(count) && count > 0 ? this.t.cleanCount(count) : "";
    const program = clean === "drum" && this._autocleanProgram();
    this.$.autoclean.classList.toggle("hidden", !program);
    this.$.autoclean.disabled = !this._canStart;
    this.$.autoclean.title = this._canStart ? "" : this.t.autocleanNeedsRemote;
    this.$.ask.classList.remove("hidden");
    this.$.yes.focus({ preventScroll: true });
  }

  _closeAsk() {
    this._asking = undefined;
    this.$.ask.classList.add("hidden");
  }

  // Select the drum clean, start it, and put the user's program back.
  async _autoclean() {
    const program = this._autocleanProgram();
    const previous = this._val("select");
    this._closeAsk();
    if (!program) return;
    try {
      await this._call("select", "select_option", "select", { option: program });
      await this._call("button", "press", "start");
    } finally {
      if (previous && previous !== program) {
        this._call("select", "select_option", "select", { option: previous });
      }
    }
  }

  // The last cycle in evidence, the few before it in a short list, and the
  // way to the history page when the dashboard has one.
  _updateCycles() {
    const s = this._state("cycles");
    const cycles = (s && s.attributes.cycles) || [];
    this.$.cycles.classList.toggle("hidden", !cycles.length);
    this.$.call.classList.toggle("hidden", !this._config.history);
    const sel = this._state("select");
    const shown = [s, sel, new Date().toDateString()];
    const same = this._cyclesShown && shown.every((v, i) => v === this._cyclesShown[i]);
    if (!cycles.length || same) return;
    this._cyclesShown = shown;
    const t = this.t;
    const programs = (sel && sel.attributes.programs) || [];
    const day = (date) => dayLabel(date, t, this._dayFormat);
    const [last, ...earlier] = cycles;
    const start = new Date(last.start);
    const end = new Date(last.end);
    this.$.ctop.replaceChildren(
      el("span", "cname", programLabel(last.program, programs, t)), outcome(last, t));
    this.$.cline.textContent =
      `${day(start)} · ${this._clock(start)}–${this._clock(end)} · ${duration(last.minutes)}`;
    this.$.cchips.replaceChildren(...cycleSettings(last, t).map((f) => el("span", "chip", f)));
    this.$.clist.classList.toggle("hidden", !earlier.length);
    this.$.clist.replaceChildren(...earlier.map((c) => {
      const when = new Date(c.start);
      const row = el("div", "crow");
      row.append(
        el("span", "cday", `${day(when)} · ${this._clock(when)}`),
        el("span", "cprog", programLabel(c.program, programs, t)),
        el("span", "cdur", duration(c.minutes)),
      );
      if (c.outcome === "interrupted") row.append(outcome(c, t));
      return row;
    }));
  }

  _fillSelect(role, select, label) {
    const sel = this._state(role);
    select.closest("div").classList.toggle("hidden", !sel);
    if (!sel) return;
    const opts = sel.attributes.options || [];
    if (select.dataset.opts !== opts.join(",")) {
      select.innerHTML = "";
      for (const o of opts) {
        const el = document.createElement("option");
        el.value = o;
        el.textContent = label(o);
        select.appendChild(el);
      }
      select.dataset.opts = opts.join(",");
    }
    select.disabled = opts.length < 2;
    if (this.shadowRoot.activeElement !== select) select.value = sel.state;
  }

  _build() {
    const t = this.t;
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${STYLE}</style>
      <div class="wrap">
        <div class="stage">${svg(t)}</div>
        <div class="side">
        <div class="status"><div class="big"></div><div class="small"></div></div>
        <div class="panel">
          <div class="chips"></div>
          <div class="row">
            <div class="programbox">
              <label>${t.program}</label>
              <button class="field" type="button"><span class="pname"></span><span class="caret">▾</span></button>
              <div class="pdesc"></div>
              <div class="pchips"></div>
              <div class="pnote"></div>
            </div>
          </div>
          <div class="row">
            <div><label>${t.temperature}</label><select class="settemp"></select></div>
            <div><label>${t.spinSpeed}</label><select class="setspin"></select></div>
          </div>
          <div class="row">
            <button class="go start">${t.start}</button>
            <button class="stop">${t.stop}</button>
          </div>
          <div class="row auto">
            <div><label>${t.autoStart}</label><div class="autostate"></div></div>
            <button class="autotoggle"></button>
          </div>
          <div class="seg">
            <button type="button" class="smode" data-mode="start">${t.startAt}</button>
            <button type="button" class="smode" data-mode="end">${t.endAt}</button>
          </div>
          <div class="row sched">
            <div><label class="wlabel"></label><input type="time" class="when"></div>
            <div>
              <label class="other"></label>
              <div class="btns">
                <button class="schedule">${t.schedule}</button>
                <button class="cancel">${t.cancel}</button>
              </div>
            </div>
          </div>
        </div>
        <div class="panel cycles hidden">
          <div class="chead">
            <span class="label">${t.lastCycle}</span>
            <button class="call" type="button">${t.allCycles} ›</button>
          </div>
          <div class="ctop"></div>
          <div class="cline"></div>
          <div class="cchips"></div>
          <div class="clist"></div>
        </div>
        </div>
      </div>
      <div class="sheet hidden" role="dialog" aria-modal="true" aria-label="${t.program}">
        <div class="backdrop"></div>
        <div class="sheetbox">
          <div class="sheethead">
            <input class="search" type="search" autocomplete="off" placeholder="${t.search}">
            <button class="close" type="button" aria-label="${t.close}">✕</button>
          </div>
          <div class="list"></div>
        </div>
      </div>
      <div class="ask hidden" role="dialog" aria-modal="true">
        <div class="backdrop"></div>
        <div class="askbox">
          <div class="askq"></div>
          <div class="asknote"></div>
          <div class="btns">
            <button class="go yes" type="button">${t.cleanYes}</button>
            <button class="no" type="button">${t.cleanNo}</button>
          </div>
          <button class="autoclean" type="button">${t.autoclean}</button>
        </div>
      </div>`;
    const $ = (sel) => root.querySelector(sel);
    this.$ = {
      wrap: $(".wrap"), lcd: $(".lcd"), big: $(".big"), small: $(".small"),
      chips: $(".chips"), start: $(".start"),
      settemp: $(".settemp"), setspin: $(".setspin"),
      auto: $(".auto"), autostate: $(".autostate"), autotoggle: $(".autotoggle"),
      stop: $(".stop"), when: $(".when"), schedule: $(".schedule"), cancel: $(".cancel"),
      modes: [...root.querySelectorAll(".smode")], wlabel: $(".wlabel"), other: $(".other"),
      svg: $("svg"), ask: $(".ask"), askq: $(".askq"), asknote: $(".asknote"), yes: $(".yes"),
      autoclean: $(".autoclean"),
      cycles: $(".cycles"), call: $(".call"), ctop: $(".ctop"), cline: $(".cline"),
      cchips: $(".cchips"), clist: $(".clist"),
    };
    this._cyclesShown = undefined;
    this.$.call.addEventListener("click", () => {
      if (this._config.history) navigate(this._config.history);
    });
    try {
      this._mode = localStorage.getItem("peppina-schedule-mode") === "end" ? "end" : "start";
    } catch (err) {
      this._mode = "start";
    }
    for (const button of this.$.modes) {
      button.addEventListener("click", () => {
        this._mode = button.dataset.mode;
        try {
          localStorage.setItem("peppina-schedule-mode", this._mode);
        } catch (err) {
          // private browsing: the choice lasts until the page reloads
        }
        this._updateSchedule();
      });
    }
    this.$.when.addEventListener("input", () => this._updateSchedule());
    this.picker = new ProgramPicker(root, t, (option) =>
      this._call("select", "select_option", "select", { option }));
    viewportProbe(root);
    for (const role of ["settemp", "setspin"]) {
      this.$[role].addEventListener("change", (e) =>
        this._call("select", "select_option", role, { option: e.target.value }));
    }
    this.$.autotoggle.addEventListener("click", () =>
      this._call("homeassistant", "toggle", "auto"));
    this.$.start.addEventListener("click", () => this._call("button", "press", "start"));
    this.$.stop.addEventListener("click", () => this._call("button", "press", "stop"));
    this.$.cancel.addEventListener("click", () => this._call("button", "press", "cancel"));
    this.$.svg.addEventListener("click", (e) => {
      const part = e.target.closest && e.target.closest("[data-clean]");
      if (part) this._ask(part.dataset.clean);
    });
    this.$.yes.addEventListener("click", () => {
      const clean = this._asking;
      this._closeAsk();
      if (clean) this._call("button", "press", `${clean}_done`);
    });
    for (const sel of [".ask .no", ".ask .backdrop"]) {
      root.querySelector(sel).addEventListener("click", () => this._closeAsk());
    }
    this.$.autoclean.addEventListener("click", () => this._autoclean());
    this.$.schedule.addEventListener("click", () => {
      const plan = this._plan();
      if (plan && plan.start) {
        this._call("datetime", "set_value", "delayed", { datetime: plan.start.toISOString() });
      }
    });
    this._built = true;
  }

  _update() {
    const t = this.t;
    const name = this._config.name || "Peppina";
    const on = this._val("status") === "on";
    const mode = Number(this._val("mode"));
    const phase = Number(this._val("phase"));
    const paused = mode === MODE_PAUSED;
    const error = this._val("error");
    const hasError = on && error && !/^0+$/.test(error);
    const running = on && mode === MODE_RUNNING && !paused;
    const spinning = running && SPIN_PHASES.has(phase);
    const doorOpen = this._val("door") === "on";
    const remote = this._val("remote") === "on";
    const remaining = Number(this._val("remaining"));
    const endRaw = this._val("end");
    const end = endRaw ? new Date(endRaw) : undefined;
    const delayedRaw = this._val("delayed");
    const delayed = delayedRaw ? new Date(delayedRaw) : undefined;

    const w = this.$.wrap.classList;
    w.toggle("washing", running && !spinning);
    w.toggle("spinning", spinning);
    w.toggle("paused", on && paused);
    w.toggle("error", !!hasError);
    w.toggle("open", doorOpen && !running);
    for (const clean of CLEANINGS) w.toggle(`due-${clean}`, this._due(clean));

    let lcd = "--:--";
    let big = t.sleeps(name);
    let small = t.off;
    if (hasError) {
      lcd = `E${error}`;
      big = t.error;
      small = t.code(error);
    } else if (running || (on && paused)) {
      const h = Math.floor(remaining / 60);
      lcd = Number.isFinite(remaining) ? `${h}:${pad(remaining % 60)}` : "--:--";
      big = paused ? t.paused : t.phases[phase] || t.washing;
      small = this._cycleLine(end);
    } else if (delayed) {
      lcd = hhmm(delayed);
      big = t.scheduled;
      small = t.setsOff(this._clock(delayed));
    } else if (on && mode === MODE_TIMER) {
      lcd = "TIMER";
      big = t.machineTimer;
      small = this._cycleLine(end);
    } else if (on && mode === MODE_DONE) {
      lcd = "END";
      big = t.done;
      small = doorOpen ? t.doorOpen : t.toHang;
    } else if (on) {
      lcd = "0:00";
      big = t.ready;
      small = remote ? t.remoteOn : t.remoteOff;
    }
    this.$.lcd.textContent = lcd;
    this.$.big.textContent = big;
    this.$.small.textContent = small;

    const chips = [];
    const temp = this._val("temp");
    if (temp && (running || paused)) chips.push(`${temp}°C`);
    const spin = this._val("spin");
    if (spin && (running || paused)) chips.push(t.spin(spin));
    if (doorOpen) chips.push(t.doorOpen);
    this.$.chips.innerHTML = "";
    for (const text of chips) {
      const c = document.createElement("span");
      c.className = "chip";
      c.textContent = text;
      this.$.chips.appendChild(c);
    }
    if (on && !remote && !running) {
      const c = document.createElement("span");
      c.className = "chip warn";
      c.textContent = t.remoteNeeded;
      this.$.chips.appendChild(c);
    }

    this.picker.update(this._state("select"));
    this._updateCycles();
    this._fillSelect("settemp", this.$.settemp, (v) => (v === "0" ? t.cold : `${v}°C`));
    this._fillSelect("setspin", this.$.setspin, (v) => (v === "0" ? t.noSpin : t.spin(v)));

    // Optional roles of the user's own: "auto" is whatever schedules loads
    // (an automation, a switch), "watch" whatever waits to see them start.
    // `auto_after` (minutes) is how long remote control must stay on before
    // "auto" acts: until then the card counts down.
    const auto = this._val("auto");
    this.$.auto.classList.toggle("hidden", !auto);
    clearTimeout(this._tick);
    if (auto) {
      const remoteSince = remote ? new Date(this._state("remote").last_changed) : undefined;
      const left = remoteSince && on && !running && !paused && !delayed
        ? remoteSince.getTime() + (this._config.auto_after || 0) * 60000 - Date.now()
        : 0;
      let text = t.autoOn;
      if (auto !== "on") text = t.autoOff;
      else if (left > 0) {
        const sec = Math.ceil(left / 1000);
        text = t.startingIn(`${Math.floor(sec / 60)}:${pad(sec % 60)}`);
        this._tick = setTimeout(() => this._update(), 1000);
      } else if (delayed) text = t.startsAt(this._clock(delayed));
      this.$.autostate.textContent = text;
      this.$.autotoggle.textContent = auto === "on" ? t.turnOff : t.turnOn;
    }

    const canStart = on && remote && !running && !paused;
    this._canStart = canStart;
    this.$.start.disabled = !canStart;
    this.$.stop.disabled = !(running || paused || delayed);
    this._canSchedule = on && remote && !running;
    this.$.cancel.classList.toggle("hidden", !delayed);
    if (delayed && this.shadowRoot.activeElement !== this.$.when) {
      // In "Finisci alle" the field shows when the pending start ends.
      const minutes = this._duration();
      const shown = this._mode === "end" && minutes
        ? new Date(delayed.getTime() + minutes * 60000) : delayed;
      this.$.when.value = hhmm(shown);
    }
    this._updateSchedule();
  }
}

const HISTORY_STYLE = `
  :host { display: block; }
  .hwrap {
    min-height: calc(100vh - var(--header-height, 56px)); box-sizing: border-box;
    display: flex; justify-content: center; padding: 16px;
    background: var(--primary-background-color); color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
  }
  .hbox { width: min(100%, 640px); display: flex; flex-direction: column; gap: 16px; }
  .hhead { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .htitle { font-size: 1.6em; font-weight: 600; }
  .hcount { opacity: 0.6; }
  .month {
    background: var(--card-background-color, #fff); border-radius: 20px; padding: 12px 16px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12); margin-bottom: 16px;
  }
  .month .label { padding-bottom: 4px; }
  .hrow {
    display: grid; grid-template-columns: 6.5em minmax(0, 1fr) auto; gap: 2px 12px;
    align-items: baseline; padding: 10px 0;
  }
  .hrow + .hrow { border-top: 1px solid var(--divider-color, #eee); }
  .hday { font-size: 0.85em; opacity: 0.65; }
  .hprog { font-weight: 600; overflow-wrap: anywhere; }
  .hdur { font-size: 0.9em; white-space: nowrap; text-align: right; }
  .hsub { grid-column: 2; font-size: 0.82em; opacity: 0.7; }
  .hrow .badge { grid-column: 3; justify-self: end; font-size: 0.7em; }
  .hmsg { padding: 24px; text-align: center; opacity: 0.6; }
  ${CYCLE_STYLE}
`;

// The history page: every cycle kept, newest first, month by month. The
// integration hands the list over (peppina/cycles) and the card asks again
// whenever the cycles sensor changes. Program names come from the select.
class PeppinaHistoryCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entities || !config.entities.cycles) {
      throw new Error("peppina-history-card: entities.cycles required");
    }
    this._config = config;
    this._built = false;
  }

  getCardSize() {
    return 12;
  }

  set hass(hass) {
    this._hass = hass;
    const locale = hass.locale || { language: hass.language };
    const key = `${locale.language}|${locale.time_format}`;
    if (key !== this._localeKey) {
      this._localeKey = key;
      this.t = textsFor(locale.language);
      this._timeFormat = timeFormat(locale);
      this._dayFormat = dayFormat(locale);
      this._monthFormat = monthFormat(locale);
      this._built = false;
    }
    if (!this._built) this._build();
    const source = hass.states[this._config.entities.cycles];
    if (source !== this._source) {
      this._source = source;
      this._load();
    }
    this._render();
  }

  _build() {
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${HISTORY_STYLE}</style>
      <div class="hwrap"><div class="hbox">
        <div class="hhead"><span class="htitle">${this.t.cycles}</span><span class="hcount"></span></div>
        <div class="hlist"></div>
      </div></div>`;
    this.$ = { count: root.querySelector(".hcount"), list: root.querySelector(".hlist") };
    this._shown = undefined;
    this._built = true;
  }

  async _load() {
    const asked = (this._asked = (this._asked || 0) + 1);
    let cycles;
    try {
      ({ cycles } = await this._hass.callWS({
        type: "peppina/cycles", entity_id: this._config.entities.cycles,
      }));
    } catch (err) {
      cycles = undefined;
    }
    // A newer answer is on its way.
    if (asked !== this._asked) return;
    this._cycles = cycles;
    this._failed = !cycles;
    this._render();
  }

  _render() {
    const t = this.t;
    const select = this._config.entities.select;
    const sel = select && this._hass.states[select];
    const shown = [this._cycles, this._failed, sel, new Date().toDateString()];
    if (this._shown && shown.every((v, i) => v === this._shown[i])) return;
    this._shown = shown;
    const cycles = this._cycles;
    this.$.count.textContent = cycles && cycles.length ? t.cycleCount(cycles.length) : "";
    if (!cycles || !cycles.length) {
      const message = this._failed ? t.loadFailed : cycles ? t.noCycles : t.loading;
      this.$.list.replaceChildren(el("div", "hmsg", message));
      return;
    }
    const programs = (sel && sel.attributes.programs) || [];
    const clock = (date) => this._timeFormat.format(date);
    const months = [];
    let month;
    for (const c of cycles) {
      const start = new Date(c.start);
      const end = new Date(c.end);
      const name = this._monthFormat.format(start);
      if (name !== month) {
        month = name;
        months.push(el("div", "month"));
        months[months.length - 1].append(el("div", "label", name));
      }
      const row = el("div", "hrow");
      row.append(
        el("span", "hday", dayLabel(start, t, this._dayFormat)),
        el("span", "hprog", programLabel(c.program, programs, t)),
        el("span", "hdur", duration(c.minutes)),
        el("span", "hsub", [`${clock(start)}–${clock(end)}`, ...cycleSettings(c, t)].join(" · ")),
        outcome(c, t),
      );
      months[months.length - 1].append(row);
    }
    this.$.list.replaceChildren(...months);
  }
}

// The frontend swaps window.customElements for a scoped-registry polyfill
// while it boots. Loaded before that, the card lands in the native registry
// only, the polyfill never sees it and the page shows "Configuration error".
// Define again, wherever window.customElements points, once the app is up.
const define = () => {
  if (!customElements.get("peppina-card")) customElements.define("peppina-card", PeppinaCard);
  if (!customElements.get("peppina-history-card")) {
    customElements.define("peppina-history-card", PeppinaHistoryCard);
  }
};
define();
customElements.whenDefined("home-assistant").then(define);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "peppina-card", name: "Peppina", description: textsFor(navigator.language).description,
});
