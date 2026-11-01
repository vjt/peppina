// The card's cleaning reminders in jsdom: which part of the machine calls,
// what a tap asks, and what each answer presses. Animations are not checked.
import { JSDOM } from "jsdom";
import fs from "node:fs";
import assert from "node:assert/strict";

const here = (path) => new URL(path, import.meta.url);
const source = fs.readFileSync(here("../../custom_components/peppina/www/peppina-card.js"), "utf8");
let failures = 0;
const pending = [];
const test = (name, fn) => {
  pending.push((async () => {
    try { await fn(); console.log("ok  ", name); } catch (e) { failures++; console.log("FAIL", name, "\n     ", e.message); }
  })());
};

function mount({ due = {}, remote = "on", mode = "1", options = ["hqd_smart", "hqd_autoclean"], roles = {} } = {}) {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", url: "https://ha.local/peppina" });
  const { window } = dom;
  window.eval(source);
  const calls = [];
  const states = {
    "binary_sensor.s": { state: "on", attributes: {} },
    "sensor.m": { state: mode, attributes: {} },
    "binary_sensor.r": { state: remote, attributes: {}, last_changed: new Date().toISOString() },
    "select.p": { state: "hqd_smart", attributes: { options } },
  };
  const entities = { status: "binary_sensor.s", mode: "sensor.m", remote: "binary_sensor.r", select: "select.p",
    start: "button.start", ...roles };
  for (const clean of ["filter", "drawer", "drum"]) {
    states[`sensor.${clean}`] = { state: "100", attributes: { count: 100, tot: 100, remaining: 0 } };
    states[`binary_sensor.${clean}_due`] = { state: due[clean] ? "on" : "off", attributes: {} };
    Object.assign(entities, { [clean]: `sensor.${clean}`, [`${clean}_due`]: `binary_sensor.${clean}_due`,
      [`${clean}_done`]: `button.${clean}_done`, ...roles });
  }
  const card = window.document.createElement("peppina-card");
  card.setConfig({ entities });
  window.document.body.appendChild(card);
  const hass = () => ({ states: { ...states }, callService: async (d, s, data) => { calls.push([d, s, data]); } });
  card.hass = hass();
  const root = card.shadowRoot;
  const $ = (s) => root.querySelector(s);
  const tap = (s) => $(s).dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const asking = () => !$(".ask").classList.contains("hidden");
  const plain = () => JSON.parse(JSON.stringify(calls));
  return { window, card, root, $, calls, plain, states, hass, tap, asking };
}

test("nothing due: no hint, and a tap asks nothing", () => {
  const t = mount();
  const w = t.$(".wrap").classList;
  assert.ok(!w.contains("due-filter") && !w.contains("due-drawer") && !w.contains("due-drum"));
  t.tap(".hatch rect");
  t.tap(".drawer .front");
  assert.equal(t.asking(), false);
});

test("each cleaning due marks its own part", () => {
  const t = mount({ due: { filter: true, drum: true } });
  const w = t.$(".wrap").classList;
  assert.ok(w.contains("due-filter") && w.contains("due-drum") && !w.contains("due-drawer"));
  assert.equal(t.$(".hint.filter").textContent, "Pulisci il filtro!");
  assert.equal(t.$(".hint.drawer").textContent, "Pulisci il cassetto!");
  t.states["binary_sensor.filter_due"] = { state: "off", attributes: {} };
  t.card.hass = t.hass();
  assert.ok(!w.contains("due-filter"));
});

test("the filter: tap, confirm, its done button is pressed", () => {
  const t = mount({ due: { filter: true } });
  t.tap(".hatch rect");
  assert.equal(t.asking(), true);
  assert.equal(t.$(".askq").textContent, "Hai pulito il filtro?");
  assert.equal(t.$(".asknote").textContent, "100 lavaggi dall'ultima pulizia");
  assert.ok(t.$(".autoclean").classList.contains("hidden"));
  t.tap(".ask .yes");
  assert.equal(t.asking(), false);
  assert.deepEqual(t.plain(), [["button", "press", { entity_id: "button.filter_done" }]]);
});

test("the drawer: the hint answers a tap too, and no presses nothing", () => {
  const t = mount({ due: { drawer: true } });
  t.tap(".hint.drawer");
  assert.equal(t.$(".askq").textContent, "Hai pulito il cassetto del detersivo?");
  t.tap(".ask .no");
  assert.equal(t.asking(), false);
  t.tap(".drawer .front");
  t.tap(".ask .backdrop");
  assert.equal(t.asking(), false);
  assert.deepEqual(t.plain(), []);
});

test("the drum offers the autoclean, and puts the program back after starting it", async () => {
  const t = mount({ due: { drum: true } });
  t.tap('circle[data-clean="drum"]');
  assert.equal(t.$(".askq").textContent, "Hai pulito il cestello?");
  assert.ok(!t.$(".autoclean").classList.contains("hidden"));
  assert.equal(t.$(".autoclean").disabled, false);
  t.tap(".autoclean");
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(t.asking(), false);
  assert.deepEqual(t.plain(), [
    ["select", "select_option", { entity_id: "select.p", option: "hqd_autoclean" }],
    ["button", "press", { entity_id: "button.start" }],
    ["select", "select_option", { entity_id: "select.p", option: "hqd_smart" }],
  ]);
});

test("the drum: done without the autoclean", () => {
  const t = mount({ due: { drum: true } });
  t.tap('circle[data-clean="drum"]');
  t.tap(".ask .yes");
  assert.deepEqual(t.plain(), [["button", "press", { entity_id: "button.drum_done" }]]);
});

test("no autoclean without remote control, nor on a machine without the program", () => {
  const t = mount({ due: { drum: true }, remote: "off" });
  t.tap('circle[data-clean="drum"]');
  assert.equal(t.$(".autoclean").disabled, true);
  const other = mount({ due: { drum: true }, options: ["hqd_smart", "iot_wash_quick_drum_cleaner"] });
  other.tap('circle[data-clean="drum"]');
  assert.equal(other.$(".autoclean").classList.contains("hidden"), false);
  const none = mount({ due: { drum: true }, options: ["hqd_smart"] });
  none.tap('circle[data-clean="drum"]');
  assert.ok(none.$(".autoclean").classList.contains("hidden"));
});

test("without the done role a due cleaning shows but does not ask", () => {
  const t = mount({ due: { filter: true }, roles: { filter_done: undefined } });
  assert.ok(t.$(".wrap").classList.contains("due-filter"));
  t.tap(".hatch rect");
  assert.equal(t.asking(), false);
});

await Promise.all(pending);
process.exitCode = failures ? 1 : 0;
