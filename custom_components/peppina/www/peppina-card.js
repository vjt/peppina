// Peppina card: the washing machine itself, full page, with its controls.
//
// Served by the integration (see dashboard.py) and dropped into the Peppina
// dashboard. The config maps roles to entity ids, e.g.
//   type: custom:peppina-card
//   name: Peppina
//   entities: {status: binary_sensor.x_status, mode: sensor.x_mode, ...}
// Missing roles are simply not shown.

const PHASES = {
  0: "Pronto", 1: "Lavaggio", 2: "Lavaggio", 3: "Centrifuga", 4: "Risciacquo",
  5: "Risciacquo", 6: "Risciacquo", 7: "Asciugatura", 8: "Asciugatura",
  9: "Vapore", 10: "Pronto", 11: "Centrifuga", 12: "Pesatura", 13: "Pesatura",
  14: "Lavaggio", 15: "Lavaggio", 16: "Lavaggio", 17: "Risciacquo",
  18: "Risciacquo", 19: "Programmato", 20: "Tumbling", 24: "Refresh",
  25: "Lavaggio", 26: "Riscaldamento", 27: "Lavaggio",
};
const SPIN_PHASES = new Set([3, 11]);

// hOn machMode for washers: 1 ready, 2 running, 3 paused, 5 timer, 6 error, 7 done
const MODE_RUNNING = 2;
const MODE_PAUSED = 3;
const MODE_TIMER = 5;
const MODE_DONE = 7;

const prettyProgram = (p) =>
  p.replace(/^(hqd|iot_wash)_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const hhmm = (d) => d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

// What the program picker says, in one place: the rest of the card still
// speaks Italian inline, until it learns other languages.
const STRINGS = {
  search: "Cerca programma",
  close: "Chiudi",
  mostUsed: "Più usati",
  others: "Altri",
  noMatch: "Nessun programma trovato",
  tags: { guided: "guidato", care: "cura capi", download: "scaricato", featured: "in evidenza" },
  load: (kg) => `max ${kg.toLocaleString("it-IT")} kg`,
  temp: ([lo, hi]) => {
    const cold = "freddo";
    if (lo === hi) return lo === 0 ? cold : `${lo}°C`;
    return `${lo === 0 ? cold : lo}–${hi}°C`;
  },
  spin: (rpm) => `${rpm} giri`,
  times: (n) => `${n}×`,
  duration: (minutes) => {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
  },
  // The machine's own estimate, at the settings it was made for.
  estimate: ({ minutes }) => `≈ ${STRINGS.duration(minutes)}`,
  estimateNote: ({ temp, spin }) => {
    const at = [
      temp != null && (Number(temp) === 0 ? "a freddo" : `a ${temp}°C`),
      spin != null && (Number(spin) === 0 ? "senza centrifuga" : `${spin} giri`),
    ].filter(Boolean);
    return `Stima della macchina${at.length ? `, ${at.join(" e ")}` : ""}`;
  },
};
const MOST_USED = 5;

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const fold = (text) => text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
const tagged = (p) => (p.tag ? `${p.name} · ${STRINGS.tags[p.tag] || p.tag}` : p.name);
const facts = (p) => [
  p.duration && STRINGS.estimate(p.duration),
  p.load && STRINGS.load(p.load),
  p.temp && STRINGS.temp(p.temp),
  p.spin && STRINGS.spin(p.spin),
].filter(Boolean);

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
  constructor(root, onPick) {
    const $ = (sel) => root.querySelector(sel);
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
    this.$.list.addEventListener("click", (e) => {
      const row = e.target.closest(".prow");
      if (!row) return;
      this.close();
      if (row.dataset.key !== this._value) this._onPick(row.dataset.key);
    });
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
    this.$.name.textContent = p ? tagged(p) : prettyProgram(sel.state || "");
    this.$.desc.textContent = (p && p.description) || "";
    this.$.chips.replaceChildren(...(p ? facts(p) : []).map((t) => el("span", "chip", t)));
    this.$.note.textContent = p && p.duration ? STRINGS.estimateNote(p.duration) : "";
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
    const query = fold(this.$.search.value.trim());
    const shown = query
      ? this._programs.filter((p) =>
        fold(`${p.name} ${p.description} ${p.group_name || ""}`).includes(query))
      : this._programs;
    const nodes = [];
    // Searching, the groups say enough: the most used would repeat them.
    const top = query ? [] : shown.filter((p) => p.usage > 0)
      .sort((a, b) => b.usage - a.usage).slice(0, MOST_USED);
    if (top.length) nodes.push(el("div", "group", STRINGS.mostUsed), ...top.map((p) => this._row(p)));
    let group;
    for (const p of shown) {
      const name = p.group_name || STRINGS.others;
      if (name !== group) nodes.push(el("div", "group", (group = name)));
      nodes.push(this._row(p));
    }
    if (!shown.length) nodes.push(el("div", "empty", STRINGS.noMatch));
    const scroll = this.$.list.scrollTop;
    this.$.list.replaceChildren(...nodes);
    this.$.list.scrollTop = scroll;
  }

  _row(p) {
    const row = el("button", p.key === this._value ? "prow sel" : "prow");
    row.type = "button";
    row.dataset.key = p.key;
    const head = el("span", "ptop");
    head.append(el("span", "pn", p.name));
    if (p.tag) head.append(el("span", "ptag", STRINGS.tags[p.tag] || p.tag));
    const meta = [
      p.duration && STRINGS.duration(p.duration.minutes),
      p.usage > 0 ? STRINGS.times(p.usage) : !p.duration && p.load && STRINGS.load(p.load),
    ].filter(Boolean).join(" · ");
    if (meta) head.append(el("span", "pmeta", meta));
    row.append(head);
    if (p.description) row.append(el("span", "pd", p.description));
    return row;
  }
}

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
  .row > * { flex: 1 1 140px; }
  label { font-size: 0.8em; opacity: 0.7; display: block; margin-bottom: 4px; }
  select, input[type=time] {
    width: 100%; box-sizing: border-box; font: inherit; font-size: 1em;
    padding: 10px 12px; border-radius: 12px;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--primary-background-color); color: var(--primary-text-color);
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
    display: block; width: 100%; text-align: left; font-weight: normal;
    background: none; border-radius: 12px; padding: 9px 10px;
  }
  .prow:hover { background: var(--secondary-background-color, #eee); }
  .prow.sel { background: rgba(3, 169, 244, 0.14); }
  .ptop { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .pn { font-weight: 600; }
  .ptag {
    font-size: 0.72em; padding: 1px 7px; border-radius: 999px; white-space: nowrap;
    background: var(--secondary-background-color, #eee);
  }
  .pmeta { margin-left: auto; font-size: 0.8em; opacity: 0.6; white-space: nowrap; }
  .pd {
    display: block; font-size: 0.82em; opacity: 0.65; margin-top: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
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

const SVG = `
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

    <rect x="52" y="44" width="70" height="44" rx="6" fill="#e3e8ee" stroke="#c3cbd4"/>
    <rect x="58" y="50" width="28" height="32" rx="3" fill="#d2d9e0"/>
    <rect x="90" y="50" width="26" height="32" rx="3" fill="#d2d9e0"/>

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
      <path d="M135 245 a95 95 0 0 1 60 -45" stroke="rgba(255,255,255,0.35)"
            stroke-width="10" stroke-linecap="round" fill="none"/>
    </g>

    <g class="door">
      <circle cx="200" cy="300" r="120" fill="none" stroke="#d5dce3" stroke-width="10"/>
      <rect x="312" y="282" width="16" height="36" rx="6" fill="#9aa5b1"/>
    </g>

    <rect x="60" y="460" width="280" height="44" rx="10" fill="none" stroke="#c9d1d9"
          stroke-width="2"/>
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
    if (!this._built) this._build();
    this._update();
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

  // The running program as the picker names it, and when the cycle ends.
  _cycleLine(end) {
    const key = this._val("program");
    const known = key && key !== "No program";
    const programs = ((this._state("select") || {}).attributes || {}).programs || [];
    const p = known && programs.find((x) => x.key === key);
    const name = p ? tagged(p) : known ? prettyProgram(key) : "";
    const ends = end ? `finisce alle ${hhmm(end)}` : "";
    const line = [name, ends].filter(Boolean).join(" · ");
    return line.charAt(0).toUpperCase() + line.slice(1);
  }

  _call(domain, service, role, data = {}) {
    const id = this._id(role);
    if (!id) return;
    this._hass.callService(domain, service, { entity_id: id, ...data });
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
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${STYLE}</style>
      <div class="wrap">
        <div class="stage">${SVG}</div>
        <div class="side">
        <div class="status"><div class="big"></div><div class="small"></div></div>
        <div class="panel">
          <div class="chips"></div>
          <div class="row">
            <div class="programbox">
              <label>Programma</label>
              <button class="field" type="button"><span class="pname"></span><span class="caret">▾</span></button>
              <div class="pdesc"></div>
              <div class="pchips"></div>
              <div class="pnote"></div>
            </div>
          </div>
          <div class="row">
            <div><label>Temperatura</label><select class="settemp"></select></div>
            <div><label>Centrifuga</label><select class="setspin"></select></div>
          </div>
          <div class="row">
            <button class="go start">Avvia</button>
            <button class="stop">Ferma</button>
          </div>
          <div class="row auto">
            <div><label>Avvio automatico</label><div class="autostate"></div></div>
            <button class="autotoggle"></button>
          </div>
          <div class="row">
            <div><label>Avvio alle</label><input type="time" class="when"></div>
            <button class="schedule">Programma</button>
            <button class="cancel">Annulla</button>
          </div>
        </div>
        </div>
      </div>
      <div class="sheet hidden" role="dialog" aria-modal="true" aria-label="Programma">
        <div class="backdrop"></div>
        <div class="sheetbox">
          <div class="sheethead">
            <input class="search" type="search" autocomplete="off" placeholder="${STRINGS.search}">
            <button class="close" type="button" aria-label="${STRINGS.close}">✕</button>
          </div>
          <div class="list"></div>
        </div>
      </div>`;
    const $ = (sel) => root.querySelector(sel);
    this.$ = {
      wrap: $(".wrap"), lcd: $(".lcd"), big: $(".big"), small: $(".small"),
      chips: $(".chips"), start: $(".start"),
      settemp: $(".settemp"), setspin: $(".setspin"),
      auto: $(".auto"), autostate: $(".autostate"), autotoggle: $(".autotoggle"),
      stop: $(".stop"), when: $(".when"), schedule: $(".schedule"), cancel: $(".cancel"),
    };
    this.picker = new ProgramPicker(root, (option) =>
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
    this.$.schedule.addEventListener("click", () => {
      const [h, m] = (this.$.when.value || "").split(":").map(Number);
      if (Number.isNaN(h) || Number.isNaN(m)) return;
      const at = new Date();
      at.setHours(h, m, 0, 0);
      if (at <= new Date()) at.setDate(at.getDate() + 1);
      this._call("datetime", "set_value", "delayed", { datetime: at.toISOString() });
    });
    this._built = true;
  }

  _update() {
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

    let lcd = "--:--";
    let big = `${name} dorme`;
    let small = "Spenta";
    if (hasError) {
      lcd = `E${error}`;
      big = "Errore";
      small = `Codice ${error}`;
    } else if (running || (on && paused)) {
      const h = Math.floor(remaining / 60);
      lcd = Number.isFinite(remaining) ? `${h}:${String(remaining % 60).padStart(2, "0")}` : "--:--";
      big = paused ? "In pausa" : PHASES[phase] || "Lava";
      small = this._cycleLine(end);
    } else if (delayed) {
      lcd = hhmm(delayed);
      big = "Programmata";
      small = `Parte alle ${hhmm(delayed)}`;
    } else if (on && mode === MODE_TIMER) {
      lcd = "TIMER";
      big = "Timer della macchina";
      small = this._cycleLine(end);
    } else if (on && mode === MODE_DONE) {
      lcd = "END";
      big = "Finita";
      small = doorOpen ? "Sportello aperto" : "Da stendere";
    } else if (on) {
      lcd = "0:00";
      big = "Pronta";
      small = remote ? "Controllo remoto attivo" : "Controllo remoto spento";
    }
    this.$.lcd.textContent = lcd;
    this.$.big.textContent = big;
    this.$.small.textContent = small;

    const chips = [];
    const temp = this._val("temp");
    if (temp && (running || paused)) chips.push(`${temp}°C`);
    const spin = this._val("spin");
    if (spin && (running || paused)) chips.push(`${spin} giri`);
    if (doorOpen) chips.push("Sportello aperto");
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
      c.textContent = "Attiva il controllo remoto sulla macchina";
      this.$.chips.appendChild(c);
    }

    this.picker.update(this._state("select"));
    this._fillSelect("settemp", this.$.settemp, (v) => (v === "0" ? "Freddo" : `${v}°C`));
    this._fillSelect("setspin", this.$.setspin, (v) => (v === "0" ? "Niente" : `${v} giri`));

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
      let text = "Attivo";
      if (auto !== "on") text = "Spento";
      else if (left > 0) {
        const sec = Math.ceil(left / 1000);
        text = `Avvio in ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
        this._tick = setTimeout(() => this._update(), 1000);
      } else if (delayed) text = `Avvio alle ${hhmm(delayed)}`;
      this.$.autostate.textContent = text;
      this.$.autotoggle.textContent = auto === "on" ? "Spegni" : "Accendi";
    }

    const canStart = on && remote && !running && !paused;
    this.$.start.disabled = !canStart;
    this.$.stop.disabled = !(running || paused || delayed);
    this.$.schedule.disabled = !(on && remote && !running);
    this.$.cancel.classList.toggle("hidden", !delayed);
    if (delayed && this.shadowRoot.activeElement !== this.$.when) {
      this.$.when.value = `${String(delayed.getHours()).padStart(2, "0")}:${String(
        delayed.getMinutes()).padStart(2, "0")}`;
    }
  }
}

// The frontend swaps window.customElements for a scoped-registry polyfill
// while it boots. Loaded before that, the card lands in the native registry
// only, the polyfill never sees it and the page shows "Configuration error".
// Define again, wherever window.customElements points, once the app is up.
const define = () => {
  if (!customElements.get("peppina-card")) customElements.define("peppina-card", PeppinaCard);
};
define();
customElements.whenDefined("home-assistant").then(define);
window.customCards = window.customCards || [];
window.customCards.push({ type: "peppina-card", name: "Peppina", description: "La lavatrice." });
