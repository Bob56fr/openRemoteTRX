// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Raccourci « Console de la station » (console_link.js) : `node tests/js/console_link_test.js`
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.join(__dirname, "../../trxstation/gateway/api/static");
const cl = require(path.join(STATIC, "console_link.js"));
const TEMPLATE = fs.readFileSync(path.join(STATIC, "console-station.cmd"), "utf-8");

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const hello = (rc) => ({ type: "hello", remote_console: rc });
const OK = { user: "bob", ssh_port: 22, web_port: 8765 };

test("réglages : adresse de la page, compte et ports annoncés", () => {
  assert.deepEqual(cl.settings(hello(OK), "192.168.1.50"), { host: "192.168.1.50", user: "bob", sshPort: 22, webPort: 8765 });
  assert.equal(cl.settings(hello(OK), "[fd00::5]").host, "fd00::5");
  assert.equal(cl.settings(hello(OK), "station.local").host, "station.local");
});

test("rien d'offert : pas de raccourci", () => {
  assert.equal(cl.settings(hello(null), "10.0.0.2"), null);
  assert.equal(cl.settings({ type: "hello" }, "10.0.0.2"), null);
  assert.equal(cl.settings(null, "10.0.0.2"), null);
});

test("valeurs douteuses refusées : jamais de commande glissée dans le fichier", () => {
  for (const bad of ["a'b", "x;calc", "x y", "", "-oProxyCommand=calc", "x\"y", "a..b$"]) assert.equal(cl.settings(hello(OK), bad), null, bad);
  for (const user of ["Bob", "b'o", "-oProxy", "", "a b", 5]) assert.equal(cl.settings(hello({ ...OK, user }), "10.0.0.2"), null, String(user));
  assert.equal(cl.settings(hello({ ...OK, ssh_port: 0 }), "10.0.0.2"), null);
  assert.equal(cl.settings(hello({ ...OK, web_port: 80 }), "10.0.0.2"), null);
  assert.equal(cl.settings(hello({ ...OK, web_port: "8765" }), "10.0.0.2"), null);
});

test("fichier rempli : tout remplacé, lignes CRLF, partie PowerShell présente", () => {
  const s = cl.settings(hello({ user: "pi", ssh_port: 2222, web_port: 8800 }), "192.168.1.50");
  const text = cl.build(TEMPLATE, s);
  assert.ok(text && !text.includes("@@"));
  assert.ok(text.includes("$Station = '192.168.1.50'") && text.includes("$User = 'pi'"));
  assert.ok(text.includes("$SshPort = 2222") && text.includes("$WebPort = 8800"));
  assert.ok(!/[^\r]\n/.test(text) && text.startsWith("@echo off\r\n"));
  assert.ok(/^[\x00-\x7f]*$/.test(text.slice(0, text.indexOf("#PS-BEGIN#"))), "partie cmd.exe en ASCII");
  assert.equal(cl.fileName(s), "Console de la station (192.168.1.50).cmd");
  assert.equal(cl.build("sans marque", s), null);
});

let passed = 0;
for (const [name, fn] of tests) {
  try { fn(); passed++; console.log("OK    " + name); } catch (e) { console.log("ÉCHEC " + name + "\n" + e.stack); process.exitCode = 1; }
}
console.log(passed + "/" + tests.length + " tests JavaScript réussis");
