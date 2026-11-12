// The cycles in jsdom: the last one and the few before on the card, the
// whole history on its page. Times are UTC, so the expected strings hold
// wherever the tests run.
process.env.TZ = "UTC";
import { JSDOM } from "jsdom";
import fs from "node:fs";
import assert from "node:assert/strict";

const here = (path) => new URL(path, import.meta.url);
const source = fs.readFileSync(here("../../custom_components/peppina/www/peppina-card.js"), "utf8");
const programs = JSON.parse(fs.readFileSync(here("../fixtures/programs.json"), "utf8"));
let failures = 0;
const pending = [];
const test = (name, fn) => {
  pending.push((async () => {
    try { await fn(); console.log("ok  ", name); } catch (e) { failures++; console.log("FAIL", name, "\n     ", e.message); }
  })());
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const at = (daysAgo, hh, mm) => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - daysAgo);
  d.setUTCHours(hh, mm, 0, 0);
  return d.toISOString();
};
// Newest first, as the sensor attribute and the websocket command give them.
const CYCLES = [
  { program: "iot_wash_bed_linen", start: at(0, 0, 55), end: at(0, 2, 37), minutes: 102,
    outcome: "finished", temp: 60, spin: 1400 },
  { program: "hqd_smart", start: at(1, 15, 26), end: at(1, 15, 30), minutes: 4,
    outcome: "interrupted", temp: 40, spin: 1200 },
  { program: null, start: at(40, 5, 56), end: at(40, 7, 18), minutes: 81,
    outcome: "finished", temp: 0, spin: 0 },
  { program: "hqd_unknown_one", start: at(41, 6, 0), end: at(41, 7, 0), minutes: 60,
    outcome: "finished", temp: null, spin: null },
];
const dayOf = (iso, language) => new Intl.DateTimeFormat(language,
  { weekday: "short", day: "numeric", month: "short" }).format(new Date(iso)).replace(/^\p{Ll}/u, (c) => c.toUpperCase());
const monthOf = (iso, language) => new Intl.DateTimeFormat(language, { month: "long", year: "numeric" })
  .format(new Date(iso));

function dom() {
  const page = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://ha.local/peppina/default" });
  page.window.eval(source);
  return page.window;
}

function mount({ cycles = CYCLES, history = "/peppina/cycles", language = "it" } = {}) {
  const window = dom();
  const states = {
    "binary_sensor.s": { state: "on", attributes: {} },
    "sensor.m": { state: "1", attributes: {} },
    "select.p": { state: "hqd_smart", attributes: { options: programs.map((p) => p.key), programs } },
    "sensor.c": { state: CYCLES[0].end, attributes: { cycles } },
  };
  const card = window.document.createElement("peppina-card");
  card.setConfig({ entities: { status: "binary_sensor.s", mode: "sensor.m", select: "select.p", cycles: "sensor.c" },
    ...(history ? { history } : {}) });
  window.document.body.appendChild(card);
  const hass = () => ({ locale: { language, time_format: "24" }, states: { ...states }, callService: async () => {} });
  card.hass = hass();
  const $ = (s) => card.shadowRoot.querySelector(s);
  const $$ = (s) => [...card.shadowRoot.querySelectorAll(s)];
  return { window, card, states, hass, $, $$ };
}

function mountHistory({ answer = () => ({ cycles: CYCLES }), language = "it", select = "select.p" } = {}) {
  const window = dom();
  const asked = [];
  const states = {
    "select.p": { state: "hqd_smart", attributes: { options: [], programs } },
    "sensor.c": { state: CYCLES[0].end, attributes: { cycles: CYCLES.slice(0, 5) } },
  };
  const card = window.document.createElement("peppina-history-card");
  card.setConfig({ entities: { cycles: "sensor.c", ...(select ? { select } : {}) } });
  window.document.body.appendChild(card);
  const hass = () => ({ locale: { language, time_format: "24" }, states: { ...states },
    callWS: async (msg) => { asked.push(msg); return answer(msg); } });
  card.hass = hass();
  const $ = (s) => card.shadowRoot.querySelector(s);
  const $$ = (s) => [...card.shadowRoot.querySelectorAll(s)];
  return { window, card, states, hass, asked, $, $$ };
}

test("the last cycle in evidence, the ones before in a list", () => {
  const t = mount();
  assert.equal(t.$(".cycles").classList.contains("hidden"), false);
  assert.equal(t.$(".cycles .label").textContent, "Ultimo lavaggio");
  assert.equal(t.$(".cname").textContent, "Lenzuola");
  assert.equal(t.$(".ctop .badge").textContent, "Completato");
  assert.equal(t.$(".cline").textContent, "Oggi · 00:55–02:37 · 1 h 42 min");
  assert.deepEqual(t.$$(".cchips .chip").map((c) => c.textContent), ["60°C", "1400 giri"]);
  const rows = t.$$(".clist .crow");
  assert.deepEqual(rows.map((r) => r.querySelector(".cprog").textContent),
    ["Smart A.I.", "Programma sconosciuto", "Unknown one"]);
  assert.equal(rows[0].querySelector(".cday").textContent, "Ieri · 15:26");
  assert.equal(rows[0].querySelector(".badge.stopped").textContent, "Interrotto");
  assert.equal(rows[1].querySelector(".cday").textContent, `${dayOf(CYCLES[2].start, "it")} · 05:56`);
  assert.equal(rows[1].querySelector(".badge"), null);
  assert.equal(rows[1].querySelector(".cdur").textContent, "1 h 21 min");
});

test("a cold cycle without spin, and one alone", () => {
  const t = mount({ cycles: [CYCLES[2]] });
  assert.equal(t.$(".cname").textContent, "Programma sconosciuto");
  assert.deepEqual(t.$$(".cchips .chip").map((c) => c.textContent), ["freddo"]);
  assert.ok(t.$(".clist").classList.contains("hidden"));
});

test("no cycles, no block", () => {
  const t = mount({ cycles: [] });
  assert.ok(t.$(".cycles").classList.contains("hidden"));
  const none = mount();
  delete none.states["sensor.c"];
  none.card.hass = none.hass();
  assert.ok(none.$(".cycles").classList.contains("hidden"));
});

test("a new cycle shows up as the sensor changes", () => {
  const t = mount({ cycles: CYCLES.slice(1) });
  assert.equal(t.$(".cname").textContent, "Smart A.I.");
  t.states["sensor.c"] = { state: CYCLES[0].end, attributes: { cycles: CYCLES } };
  t.card.hass = t.hass();
  assert.equal(t.$(".cname").textContent, "Lenzuola");
  assert.equal(t.$$(".clist .crow").length, 3);
});

test("all washes: to the history view", () => {
  const t = mount();
  const went = [];
  t.window.addEventListener("location-changed", () => went.push(t.window.location.pathname));
  assert.equal(t.$(".call").classList.contains("hidden"), false);
  t.$(".call").click();
  assert.deepEqual(went, ["/peppina/cycles"]);
  const bare = mount({ history: null });
  assert.ok(bare.$(".call").classList.contains("hidden"));
});

test("in English", () => {
  const t = mount({ language: "en" });
  assert.equal(t.$(".cycles .label").textContent, "Last wash");
  assert.equal(t.$(".call").textContent, "All washes ›");
  assert.equal(t.$(".ctop .badge").textContent, "Finished");
  assert.equal(t.$(".cline").textContent, "Today · 00:55–02:37 · 1 h 42 min");
  assert.deepEqual(t.$$(".cchips .chip").map((c) => c.textContent), ["60°C", "1400 rpm"]);
  const rows = t.$$(".clist .crow");
  assert.equal(rows[0].querySelector(".cday").textContent, "Yesterday · 15:26");
  assert.equal(rows[0].querySelector(".badge").textContent, "Interrupted");
  assert.equal(rows[1].querySelector(".cprog").textContent, "Unknown program");
});

test("the history page asks for every cycle and lists them by month", async () => {
  const t = mountHistory();
  assert.equal(t.$(".hmsg").textContent, "Carico i lavaggi…");
  await settle();
  assert.deepEqual(JSON.parse(JSON.stringify(t.asked)), [{ type: "peppina/cycles", entity_id: "sensor.c" }]);
  assert.equal(t.$(".htitle").textContent, "Lavaggi");
  assert.equal(t.$(".hcount").textContent, "4 lavaggi");
  const months = t.$$(".month");
  const expected = [...new Set(CYCLES.map((c) => monthOf(c.start, "it")))];
  assert.deepEqual(months.map((m) => m.querySelector(".label").textContent), expected);
  const rows = t.$$(".hrow");
  assert.deepEqual(rows.map((r) => r.querySelector(".hprog").textContent),
    ["Lenzuola", "Smart A.I.", "Programma sconosciuto", "Unknown one"]);
  assert.deepEqual(rows.map((r) => r.querySelector(".hday").textContent),
    ["Oggi", "Ieri", dayOf(CYCLES[2].start, "it"), dayOf(CYCLES[3].start, "it")]);
  assert.equal(rows[0].querySelector(".hsub").textContent, "00:55–02:37 · 60°C · 1400 giri");
  assert.equal(rows[2].querySelector(".hsub").textContent, "05:56–07:18 · freddo");
  assert.equal(rows[3].querySelector(".hsub").textContent, "06:00–07:00");
  assert.deepEqual(rows.map((r) => r.querySelector(".badge").textContent),
    ["Completato", "Interrotto", "Completato", "Completato"]);
  assert.equal(rows[0].querySelector(".hdur").textContent, "1 h 42 min");
});

test("the history page asks again when the sensor changes, not otherwise", async () => {
  let answer = { cycles: CYCLES.slice(1) };
  const t = mountHistory({ answer: () => answer });
  await settle();
  assert.equal(t.$$(".hrow").length, 3);
  t.card.hass = t.hass();
  await settle();
  assert.equal(t.asked.length, 1);
  answer = { cycles: CYCLES };
  t.states["sensor.c"] = { state: CYCLES[0].end, attributes: { cycles: CYCLES } };
  t.card.hass = t.hass();
  await settle();
  assert.equal(t.asked.length, 2);
  assert.equal(t.$$(".hrow").length, 4);
});

test("the history page: none yet, a failure, English, no program names", async () => {
  const empty = mountHistory({ answer: () => ({ cycles: [] }) });
  await settle();
  assert.equal(empty.$(".hmsg").textContent, "Nessun lavaggio registrato");
  assert.equal(empty.$(".hcount").textContent, "");
  const broken = mountHistory({ answer: () => { throw new Error("not_found"); } });
  await settle();
  assert.equal(broken.$(".hmsg").textContent, "Non riesco a leggere i lavaggi");
  const en = mountHistory({ language: "en", select: null });
  await settle();
  assert.equal(en.$(".htitle").textContent, "Washes");
  assert.equal(en.$(".hcount").textContent, "4 washes");
  assert.deepEqual(en.$$(".hrow .hprog").map((p) => p.textContent),
    ["Bed linen", "Smart", "Unknown program", "Unknown one"]);
  assert.equal(en.$$(".hrow")[1].querySelector(".hsub").textContent, "15:26–15:30 · 40°C · 1200 rpm");
  assert.equal(en.$$(".hrow")[0].querySelector(".hday").textContent, "Today");
});

await Promise.all(pending);
process.exitCode = failures ? 1 : 0;
