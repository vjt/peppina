// The card's program picker in jsdom, against the 92 programs of vjt's
// washer as the integration describes them (tests/fixtures/programs.json).
// jsdom has no layout: how the sheet looks is not checked here.
import { JSDOM } from "jsdom";
import fs from "node:fs";
import assert from "node:assert/strict";

const here = (path) => new URL(path, import.meta.url);
const source = fs.readFileSync(here("../../custom_components/peppina/www/peppina-card.js"), "utf8");
const programs = JSON.parse(fs.readFileSync(here("../fixtures/programs.json"), "utf8"));
let failures = 0;
const test = (name, fn) => {
  try { fn(); console.log("ok  ", name); } catch (e) { failures++; console.log("FAIL", name, "\n     ", e.message); }
};

// i18n: what hass says of the user's language; Italian unless a test says otherwise.
const ITALIAN = { locale: { language: "it", time_format: "language" } };

function mount({ withPrograms = true, state = "hqd_smart", options, url, viewport, i18n = ITALIAN } = {}) {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: url || "https://ha.local/peppina" });
  const { window } = dom;
  if (viewport) window.visualViewport = Object.assign(new window.EventTarget(), viewport);
  window.eval(source);
  const calls = [];
  const states = {
    "binary_sensor.s": { state: "on", attributes: {} },
    "sensor.m": { state: "1", attributes: {} },
    "binary_sensor.r": { state: "on", attributes: {}, last_changed: new Date().toISOString() },
    "select.p": { state, attributes: { options: options || programs.map((p) => p.key), ...(withPrograms ? { programs } : {}) } },
    "sensor.program": { state: "No program", attributes: {} },
    "sensor.end": { state: "unknown", attributes: {} },
    "datetime.d": { state: "unknown", attributes: {} },
  };
  const card = window.document.createElement("peppina-card");
  card.setConfig({ entities: { status: "binary_sensor.s", mode: "sensor.m", remote: "binary_sensor.r", select: "select.p",
    program: "sensor.program", end: "sensor.end", delayed: "datetime.d" } });
  window.document.body.appendChild(card);
  let lang = i18n;
  const hass = () => ({ ...lang, states: { ...states }, callService: (d, s, data) => calls.push([d, s, data]) });
  card.hass = hass();
  // The user switches language in their profile.
  const speak = (next) => { lang = next; card.hass = hass(); };
  const root = card.shadowRoot;
  const $ = (s) => root.querySelector(s);
  const $$ = (s) => [...root.querySelectorAll(s)];
  const sheetOpen = () => !$(".sheet").classList.contains("hidden");
  const search = (q) => { $(".search").value = q; $(".search").dispatchEvent(new window.Event("input")); };
  const rows = () => $$(".list .prow");
  const headers = () => $$(".list .group").map((g) => g.textContent);
  return { window, card, root, $, $$, calls, states, hass, speak, sheetOpen, search, rows, headers };
}

test("the field replaces the native select and describes the program", () => {
  const t = mount();
  assert.equal(t.$("select.program"), null);
  assert.equal(t.$(".pname").textContent, "Smart A.I.");
  assert.match(t.$(".pdesc").textContent, /Intelligenza Artificiale/);
  assert.deepEqual(t.$$(".pchips .chip").map((c) => c.textContent),
    ["≈ 1 h 21 min", "max 9 kg", "freddo–60°C", "1200 giri"]);
  assert.equal(t.$(".pnote").textContent, "Stima della macchina, a 40°C e 1200 giri");
  assert.equal(t.sheetOpen(), false);
});

test("the duration sits next to each program that has one, and nowhere else", () => {
  const t = mount();
  t.$(".field").click();
  const meta = (key) => t.$(`.prow[data-key="${key}"] .pmeta`)?.textContent;
  assert.equal(meta("hqd_smart"), "1 h 21 min · 192×");
  assert.equal(meta("hqd_eco_40_60_degrees"), "2 h 50 min · 38×");
  assert.equal(meta("hqd_cottons"), "4×");
  assert.equal(meta("hqd_quick_15"), "max 1,8 kg");
});

test("a program without an estimate shows no duration", () => {
  const t = mount({ state: "hqd_cottons" });
  assert.ok(!t.$$(".pchips .chip").some((c) => c.textContent.startsWith("≈")));
  assert.equal(t.$(".pnote").textContent, "");
});

test("the sheet opens with the most used first, then hOn's groups", () => {
  const t = mount();
  t.$(".field").click();
  assert.equal(t.sheetOpen(), true);
  const names = t.rows().slice(0, 5).map((r) => r.querySelector(".pn").textContent);
  assert.deepEqual(names, ["Smart A.I.", "Eco 40-60", "Baby Care", "Cotone", "Sintetici"]);
  assert.deepEqual(t.headers(), ["Più usati", "Tradizionali", "Rapidi", "Eco", "Delicati", "Macchie",
    "Salute", "Casa", "Sport", "Baby", "Pets", "Ariel", "Dash", "Business", "Altri"]);
  const used = programs.filter((p) => p.usage > 0).length;
  assert.equal(t.headers()[0], "Più usati");
  assert.equal(t.rows().length, 92 + Math.min(10, used));  // up to ten most used
  assert.equal(t.rows()[0].querySelector(".pmeta").textContent, "1 h 21 min · 192×");
  assert.ok(t.rows()[0].classList.contains("sel"));
});

test("namesakes carry their tag", () => {
  const t = mount();
  t.$(".field").click();
  const row = t.$('.prow[data-key="iot_wash_cotton"]');
  assert.equal(row.querySelector(".pn").textContent, "Cotone");
  assert.equal(row.querySelector(".ptag").textContent, "guidato");
  assert.equal(t.$('.prow[data-key="hqd_cottons"] .ptag'), null);
});

test("search folds accents and drops the most used section", () => {
  const t = mount();
  t.$(".field").click();
  t.search("vino");
  assert.ok(t.rows().some((r) => r.querySelector(".pn").textContent === "Macchie di Vino"));
  assert.ok(!t.headers().includes("Più usati"));
  t.search("e in grado");  // "è in grado" in Eco 40-60
  assert.ok(t.rows().some((r) => r.dataset.key === "hqd_eco_40_60_degrees"));
  t.search("zzzz");
  assert.equal(t.rows().length, 0);
  assert.equal(t.$(".list .empty").textContent, "Nessun programma trovato");
});

test("picking a row selects it and closes", () => {
  const t = mount();
  t.$(".field").click();
  t.$('.prow[data-key="iot_wash_cotton"]').click();
  assert.equal(JSON.stringify(t.calls), JSON.stringify([["select", "select_option", { entity_id: "select.p", option: "iot_wash_cotton" }]]));
  assert.equal(t.sheetOpen(), false);
});

test("picking the selected program sends nothing", () => {
  const t = mount();
  t.$(".field").click();
  t.$('.prow[data-key="hqd_smart"]').click();
  assert.deepEqual(t.calls, []);
});

test("Esc, the backdrop and the close button close", () => {
  const t = mount();
  for (const close of [
    () => t.window.document.dispatchEvent(new t.window.KeyboardEvent("keydown", { key: "Escape" })),
    () => t.$(".backdrop").click(),
    () => t.$(".close").click(),
  ]) {
    t.$(".field").click();
    assert.equal(t.sheetOpen(), true);
    close();
    assert.equal(t.sheetOpen(), false);
  }
});

test("unrelated hass updates leave the open list alone", () => {
  const t = mount();
  t.$(".field").click();
  const first = t.rows()[0];
  t.states["sensor.m"] = { state: "2", attributes: {} };
  t.card.hass = t.hass();
  assert.equal(t.rows()[0], first);
});

test("a new program state updates field and list", () => {
  const t = mount();
  t.$(".field").click();
  t.states["select.p"] = { ...t.states["select.p"], state: "hqd_cottons" };
  t.card.hass = t.hass();
  assert.equal(t.$(".pname").textContent, "Cotone");
  assert.ok(t.$('.prow[data-key="hqd_cottons"]').classList.contains("sel"));
});

test("unavailable, the field keeps the program and turns off", () => {
  const t = mount();
  t.$(".field").click();
  t.states["select.p"] = { state: "unavailable", attributes: { options: t.states["select.p"].attributes.options } };
  t.card.hass = t.hass();
  assert.equal(t.$(".pname").textContent, "Smart A.I.");
  assert.equal(t.$(".field").disabled, true);
  assert.equal(t.sheetOpen(), false);
});

test("while washing, the card says which program runs, by its dictionary name", () => {
  const t = mount();
  const end = new Date(Date.now() + 90 * 60000);
  t.states["sensor.m"] = { state: "2", attributes: {} };
  t.states["sensor.program"] = { state: "hqd_synthetic_and_coloured", attributes: {} };
  t.states["sensor.end"] = { state: end.toISOString(), attributes: {} };
  t.card.hass = t.hass();
  const hhmm = end.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  assert.equal(t.$(".small").textContent, `Sintetici · finisce alle ${hhmm}`);
  assert.ok(!t.$$(".chips .chip").some((c) => c.textContent.includes("hqd_")));
  // A namesake keeps its tag; an unknown key reads as before; no program, no name.
  t.states["sensor.program"] = { state: "iot_wash_cotton", attributes: {} };
  t.card.hass = t.hass();
  assert.equal(t.$(".small").textContent, `Cotone · guidato · finisce alle ${hhmm}`);
  t.states["sensor.program"] = { state: "No program", attributes: {} };
  t.card.hass = t.hass();
  assert.equal(t.$(".small").textContent, `Finisce alle ${hhmm}`);
});

test("with the keyboard up, the sheet keeps to the visible part of the screen", () => {
  // iOS: the keyboard shrinks the visual viewport only, and may pan it.
  const t = mount({ viewport: { height: 844, offsetTop: 0 } });
  const vv = t.window.visualViewport;
  const style = t.$(".sheet").style;
  t.$(".field").click();
  assert.equal(style.height, "844px");
  vv.height = 500;
  vv.dispatchEvent(new t.window.Event("resize"));
  assert.equal(style.height, "500px");
  vv.offsetTop = 120;
  vv.dispatchEvent(new t.window.Event("scroll"));
  assert.equal(style.top, "120px");
  t.$(".close").click();
  assert.equal(style.height, "");
  assert.equal(style.top, "");
  vv.height = 300;
  vv.dispatchEvent(new t.window.Event("resize"));  // closed: not listening any more
  assert.equal(style.height, "");
});

test("without visualViewport the sheet keeps its CSS", () => {
  const t = mount();
  t.$(".field").click();
  assert.equal(t.$(".sheet").style.height, "");
});

test("the viewport probe shows only when asked for", () => {
  assert.equal(mount().$(".vprobe"), null);
  const t = mount({ url: "https://ha.local/peppina?peppina_viewport", viewport: { height: 500, offsetTop: 0, width: 390, scale: 1 } });
  assert.match(t.$(".vprobe").textContent, /visual 390×500/);
});

test("each row shows temperature and spin pills on the name's line", () => {
  const t = mount();
  t.$(".field").click();
  const head = t.$('.prow[data-key="hqd_cottons"] .ptop');
  assert.deepEqual([...head.querySelectorAll(".ppill")].map((x) => x.textContent), ["freddo–90°C", "1400 giri"]);
});

test("descriptions read whole: tap in the card, the arrow in the list", () => {
  const t = mount();
  const desc = t.$(".pdesc");
  desc.click();
  assert.ok(desc.classList.contains("full"));
  desc.click();
  assert.ok(!desc.classList.contains("full"));
  t.$(".field").click();
  const row = t.$('.prow[data-key="hqd_cottons"]');
  row.querySelector(".pexp").click();
  assert.ok(row.classList.contains("full"));
  assert.equal(row.querySelector(".pexp").getAttribute("aria-expanded"), "true");
  assert.equal(t.sheetOpen(), true);  // opening the description picks nothing
  assert.equal(t.calls.length, 0);
});

test("a row picks with Enter too", () => {
  const t = mount();
  t.$(".field").click();
  const row = t.$('.prow[data-key="hqd_cottons"]');
  row.dispatchEvent(new t.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  assert.equal(JSON.parse(JSON.stringify(t.calls))[0][2].option, "hqd_cottons");
});

const hhmm = (d) => d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
const pad = (n) => String(n).padStart(2, "0");
const typed = (t, date) => {
  t.$(".when").value = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  t.$(".when").dispatchEvent(new t.window.Event("input"));
};
const inMinutes = (n) => { const d = new Date(Date.now() + n * 60000); d.setSeconds(0, 0); return d; };

test("the schedule row: a label on both columns", () => {
  const t = mount();
  assert.equal(t.$(".wlabel").textContent, "Avvio alle");
  assert.equal(t.$(".other").textContent, "\u00a0");
  assert.equal(t.$(".sched").children.length, 2);
});

test("Avvia alle: says when it ends, from the program's duration", () => {
  const t = mount();  // Smart A.I.: 81 minutes
  const start = inMinutes(120);
  typed(t, start);
  assert.equal(t.$(".other").textContent, `Fine ≈ ${hhmm(new Date(start.getTime() + 81 * 60000))}`);
  t.$(".schedule").click();
  const call = JSON.parse(JSON.stringify(t.calls)).pop();
  assert.equal(call[1], "set_value");
  assert.equal(new Date(call[2].datetime).getTime(), start.getTime());
});

test("Finisci alle: starts the program's duration before", () => {
  const t = mount();
  t.$('.smode[data-mode="end"]').click();
  assert.equal(t.$(".wlabel").textContent, "Fine alle");
  const end = inMinutes(300);
  typed(t, end);
  const start = new Date(end.getTime() - 81 * 60000);
  assert.equal(t.$(".other").textContent, `Avvio alle ${hhmm(start)}`);
  assert.equal(t.$(".schedule").disabled, false);
  t.$(".schedule").click();
  const call = JSON.parse(JSON.stringify(t.calls)).pop();
  assert.equal(new Date(call[2].datetime).getTime(), start.getTime());
  assert.equal(t.window.localStorage.getItem("peppina-schedule-mode"), "end");
});

test("Finisci alle: no duration, or too soon, no schedule", () => {
  const t = mount({ state: "hqd_cottons" });  // never estimated
  t.$('.smode[data-mode="end"]').click();
  typed(t, inMinutes(300));
  assert.equal(t.$(".other").textContent, "Durata non nota");
  assert.equal(t.$(".schedule").disabled, true);
  const smart = mount();
  smart.$('.smode[data-mode="end"]').click();
  typed(smart, inMinutes(30));  // 81 minutes do not fit
  assert.equal(smart.$(".other").textContent, "Troppo presto");
  assert.equal(smart.$(".schedule").disabled, true);
});

test("a real duration wins over the estimate", () => {
  const real = programs.map((p) => p.key === "hqd_smart"
    ? { ...p, duration: { ...p.duration, actual: 90 } } : p);
  const t = mount();
  t.states["select.p"] = { ...t.states["select.p"], attributes: { ...t.states["select.p"].attributes, programs: real } };
  t.card.hass = t.hass();
  assert.ok(t.$$(".pchips .chip").some((c) => c.textContent === "≈ 1 h 30 min"));
  assert.match(t.$(".pnote").textContent, /^Durata dell'ultimo lavaggio/);
  const start = inMinutes(60);
  typed(t, start);
  assert.equal(t.$(".other").textContent, `Fine ≈ ${hhmm(new Date(start.getTime() + 90 * 60000))}`);
});

test("without the programs attribute it falls back to the keys", () => {
  const t = mount({ withPrograms: false });
  assert.equal(t.$(".pname").textContent, "Smart");
  assert.equal(t.$$(".pchips .chip").length, 0);
  t.$(".field").click();
  assert.equal(t.rows().length, 92);
});

test("one program only: the field is disabled", () => {
  const t = mount({ options: ["hqd_smart"] });
  assert.equal(t.$(".field").disabled, true);
});

test("dictionary text never becomes markup", () => {
  const evil = programs.map((p) => p.key === "hqd_smart" ? { ...p, name: "<img src=x onerror=alert(1)>" } : p);
  const dom = mount();
  dom.states["select.p"] = { ...dom.states["select.p"], attributes: { ...dom.states["select.p"].attributes, programs: evil } };
  dom.card.hass = dom.hass();
  dom.$(".field").click();
  assert.equal(dom.root.querySelectorAll(".list img").length, 0);
  assert.equal(dom.$(".pname").textContent, "<img src=x onerror=alert(1)>");
});

// English, and the languages that fall back to it.
const ENGLISH = { locale: { language: "en", time_format: "language" } };
const label = (t, i) => t.$$(".panel label")[i].textContent;

test("in English: the program field, its facts and the controls", () => {
  const t = mount({ i18n: ENGLISH });
  assert.equal(t.$(".pname").textContent, "Smart A.I.");  // hOn's names stay as hOn gives them
  assert.deepEqual(t.$$(".pchips .chip").map((c) => c.textContent),
    ["≈ 1 h 21 min", "max 9 kg", "cold–60°C", "1200 rpm"]);
  assert.equal(t.$(".pnote").textContent, "The machine's own estimate, at 40°C and 1200 rpm");
  assert.deepEqual([label(t, 0), label(t, 1), label(t, 2)], ["Program", "Temperature", "Spin"]);
  assert.deepEqual([t.$(".start").textContent, t.$(".stop").textContent], ["Start", "Stop"]);
  assert.deepEqual(t.$$(".smode").map((b) => b.textContent), ["Start at", "Finish by"]);
  assert.deepEqual([t.$(".schedule").textContent, t.$(".cancel").textContent], ["Schedule", "Cancel"]);
  assert.equal(t.$(".wlabel").textContent, "Starts at");
  assert.deepEqual([t.$(".big").textContent, t.$(".small").textContent], ["Ready", "Remote control on"]);
});

test("in English: the sheet", () => {
  const t = mount({ i18n: ENGLISH });
  t.$(".field").click();
  assert.equal(t.$(".search").placeholder, "Search programs");
  assert.equal(t.$(".close").getAttribute("aria-label"), "Close");
  assert.equal(t.headers()[0], "Most used");
  assert.equal(t.headers().at(-1), "Others");
  assert.equal(t.$('.prow[data-key="iot_wash_cotton"] .ptag').textContent, "guided");
  assert.deepEqual([...t.$('.prow[data-key="hqd_cottons"] .ptop').querySelectorAll(".ppill")]
    .map((x) => x.textContent), ["cold–90°C", "1400 rpm"]);
  assert.equal(t.$(".pexp").getAttribute("aria-label"), "Full description");
  t.search("zzzz");
  assert.equal(t.$(".list .empty").textContent, "No program found");
});

test("in English: Peppina says how she is", () => {
  const t = mount({ i18n: ENGLISH });
  const said = () => [t.$(".big").textContent, t.$(".small").textContent];
  t.states["binary_sensor.s"] = { state: "off", attributes: {} };
  t.card.hass = t.hass();
  assert.deepEqual(said(), ["Peppina is napping", "Switched off"]);
  t.states["binary_sensor.s"] = { state: "on", attributes: {} };
  t.states["sensor.m"] = { state: "7", attributes: {} };
  t.card.hass = t.hass();
  assert.deepEqual(said(), ["All done", "Waiting to be hung out"]);
  t.states["sensor.m"] = { state: "1", attributes: {} };
  t.states["binary_sensor.r"] = { state: "off", attributes: {}, last_changed: new Date().toISOString() };
  t.card.hass = t.hass();
  assert.deepEqual(said(), ["Ready", "Remote control off"]);
  assert.ok(t.$$(".chips .chip.warn").some((c) => c.textContent === "Enable remote control on the machine"));
  t.states["sensor.m"] = { state: "2", attributes: {} };
  t.states["binary_sensor.r"] = { state: "on", attributes: {}, last_changed: new Date().toISOString() };
  t.card.hass = t.hass();
  assert.deepEqual(said(), ["Washing", ""]);
});

test("in English: times follow the profile, 12 or 24 hours", () => {
  const start = inMinutes(120);
  const end = new Date(start.getTime() + 81 * 60000);
  const at = (hour12) => end.toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit", hour12 });
  const t = mount({ i18n: { locale: { language: "en", time_format: "12" } } });
  typed(t, start);
  assert.equal(t.$(".other").textContent, `Done ≈ ${at(true)}`);
  assert.match(t.$(".other").textContent, /[AP]M$/);
  const h24 = mount({ i18n: { locale: { language: "en", time_format: "24" } } });
  typed(h24, start);
  assert.equal(h24.$(".other").textContent, `Done ≈ ${at(false)}`);
  assert.doesNotMatch(h24.$(".other").textContent, /[AP]M/);
  h24.$('.smode[data-mode="end"]').click();
  assert.equal(h24.$(".wlabel").textContent, "Done by");
  typed(h24, inMinutes(30));
  assert.equal(h24.$(".other").textContent, "Too soon");
});

test("in English, the machine's display keeps 24 hours", () => {
  const t = mount({ i18n: { locale: { language: "en", time_format: "12" } } });
  const when = inMinutes(600);
  t.states["datetime.d"] = { state: when.toISOString(), attributes: {} };
  t.card.hass = t.hass();
  assert.equal(t.$(".lcd").textContent, `${pad(when.getHours())}:${pad(when.getMinutes())}`);
  assert.equal(t.$(".big").textContent, "Scheduled");
  assert.match(t.$(".small").textContent, /^Sets off at \d\d:\d\d [AP]M$/);
});

test("Italian for any Italian, English for any other language, or none", () => {
  const big = (i18n) => mount({ i18n }).$(".big").textContent;
  assert.equal(big({ locale: { language: "it-CH" } }), "Pronta");
  assert.equal(big({ language: "it" }), "Pronta");  // hass.language alone, no locale
  assert.equal(big({ locale: { language: "en-GB" } }), "Ready");
  assert.equal(big({ locale: { language: "de" } }), "Ready");
  assert.equal(big({ locale: { language: "ita" } }), "Ready");  // not Italian, despite the letters
  assert.equal(big({}), "Ready");
});

test("a change of language in the profile rebuilds the card in it", () => {
  const t = mount();
  t.$(".field").click();
  assert.equal(t.headers()[0], "Più usati");
  t.speak(ENGLISH);
  assert.equal(t.sheetOpen(), false);  // the sheet in the old language is gone
  assert.equal(t.$(".start").textContent, "Start");
  assert.equal(t.$(".big").textContent, "Ready");
  assert.equal(t.$(".pnote").textContent, "The machine's own estimate, at 40°C and 1200 rpm");
  t.$(".field").click();
  assert.equal(t.headers()[0], "Most used");
  t.$('.prow[data-key="iot_wash_cotton"]').click();
  assert.equal(JSON.parse(JSON.stringify(t.calls)).pop()[2].option, "iot_wash_cotton");
  t.speak(ITALIAN);
  assert.equal(t.$(".start").textContent, "Avvia");
});

process.exitCode = failures ? 1 : 0;
