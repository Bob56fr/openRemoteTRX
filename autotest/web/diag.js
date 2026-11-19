// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Diagnostic du port série pas à pas (chercher l'appel qui fait planter Chrome) : une action par bouton, aucune émission,
// seule commande envoyée : lecture de l'identité CI-V (19 00), à l'adresse 00 (tout poste Icom répond).
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const log = t => { $("log").textContent += `${new Date().toLocaleTimeString()}  ${t}\n`; };
  let port = null, reader = null, writer = null;
  const step = (id, f) => { $(id).onclick = async () => { log(`${$(id).textContent} …`); try { await f(); } catch (e) { log(`  ERREUR : ${e && e.name} ${e && e.message}`); } }; };
  step("d1", async () => {
    port = await navigator.serial.requestPort();
    const i = port.getInfo(); log(`  port choisi : USB ${(i.usbVendorId || 0).toString(16)}:${(i.usbProductId || 0).toString(16)}`);
  });
  step("d2", async () => {
    await port.open({ baudRate: Number($("baud").value), dataBits: 8, stopBits: 1, parity: "none", flowControl: "none" });
    log("  ouvert");
  });
  step("d3", async () => { await port.setSignals({ dataTerminalReady: false, requestToSend: false }); log("  DTR et RTS baissés"); });
  step("d4", async () => {
    writer = writer || port.writable.getWriter(); reader = reader || port.readable.getReader();
    await writer.write(AtCiv.frame(0x00, AtCiv.CMD.ID)); log("  envoyé : FE FE 00 E0 19 00 FD");
    const until = Date.now() + 1500; let got = [];
    while (Date.now() < until) {
      const r = await Promise.race([reader.read(), new Promise(res => setTimeout(() => res(null), until - Date.now()))]);
      if (!r || r.done) break;
      got = got.concat(Array.from(r.value)); if (got.includes(0xFD) && got.length > 12) break;
    }
    log(got.length ? `  reçu : ${AtCiv.hex(new Uint8Array(got))}` : "  aucune réponse en 1,5 s");
  });
  step("d5", async () => {
    if (reader) { try { await reader.cancel(); } catch (e) {} reader.releaseLock(); reader = null; }
    if (writer) { writer.releaseLock(); writer = null; }
    await port.close(); log("  fermé");
  });
  if (!("serial" in navigator)) log("Ce navigateur n'a pas Web Serial : Chrome ou Edge sur ordinateur.");
})();
