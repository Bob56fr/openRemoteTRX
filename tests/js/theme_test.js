// Thème de couleurs (theme.js) : `node tests/js/theme_test.js`
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");

const attrs = {}, store = new Map();
let storageBroken = false;
global.document = { documentElement: { setAttribute: (k, v) => { attrs[k] = v; } } };
global.localStorage = {
  getItem: (k) => { if (storageBroken) throw new Error("bloqué"); return store.has(k) ? store.get(k) : null; },
  setItem: (k, v) => { if (storageBroken) throw new Error("bloqué"); store.set(k, String(v)); },
};
const theme = require(path.join(__dirname, "../../trxstation/gateway/api/static/theme.js"));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("rien de mémorisé : thème par défaut", () => {
  assert.equal(theme.stored(), "defaut");
  assert.equal(theme.apply(theme.stored()), "defaut"); assert.equal(attrs["data-theme"], "defaut");
});

test("choix mémorisé puis relu au chargement suivant", () => {
  assert.equal(theme.choose("yaesu"), "yaesu");
  assert.equal(attrs["data-theme"], "yaesu"); assert.equal(store.get("trx.theme"), "yaesu");
  assert.equal(theme.stored(), "yaesu");
});

test("valeur douteuse : jamais injectée dans la page, thème par défaut", () => {
  for (const bad of ['"><script>', "Icom", "", "x".repeat(40), null, 12]) {
    assert.equal(theme.valid(bad), false);
    assert.equal(theme.apply(bad), "defaut");
  }
  store.set("trx.theme", "<img src=x>");
  assert.equal(theme.stored(), "defaut");
});

test("stockage bloqué (navigation privée) : la page fonctionne quand même", () => {
  storageBroken = true;
  assert.equal(theme.stored(), "defaut");
  assert.equal(theme.choose("kenwood"), "kenwood"); assert.equal(attrs["data-theme"], "kenwood");   // appliqué, non mémorisé
  storageBroken = false;
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("OK    " + name); } catch (err) { failed++; console.log("ECHEC " + name + "\n      " + String(err.stack || err).split("\n").slice(0, 6).join("\n      ")); }
}
console.log((tests.length - failed) + "/" + tests.length + " tests du thème réussis");
process.exit(failed ? 1 : 0);
