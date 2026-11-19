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
  // 4a : écriture SEULE (aucune lecture en cours) ; 4b : lecture seule. Chrome se figeait au bouton 4 (écriture + lecture).
  step("d4a", async () => {
    writer = writer || port.writable.getWriter(); log("  écrivain prêt");
    await writer.write(AtCiv.frame(0x00, AtCiv.CMD.ID)); log("  envoyé : FE FE 00 E0 19 00 FD");
  });
  // Spectre en continu, AVANT toute lecture (sinon Chrome attend sur un port vide et se fige avec le pilote Icom).
  const scope = on => async () => {
    writer = writer || port.writable.getWriter();
    await writer.write(AtCiv.frame(0xB6, AtCiv.CMD.SCOPE_OUT, [on ? 0x01 : 0x00]));
    log(`  envoyé : FE FE B6 E0 27 11 0${on ? 1 : 0} FD`);
  };
  step("dson", scope(true));
  step("dsoff", scope(false));
  step("d4b", async () => {
    reader = reader || port.readable.getReader(); log("  lecteur prêt");
    const until = Date.now() + 1500; let got = [];
    while (Date.now() < until) {
      const r = await Promise.race([reader.read(), new Promise(res => setTimeout(() => res(null), until - Date.now()))]);
      if (!r || r.done) break;
      got = got.concat(Array.from(r.value)); if (got.length > 4000) break;
    }
    const h = AtCiv.hex(new Uint8Array(got)), id = h.indexOf("19 00 B6 FD");
    log(got.length ? `  reçu ${got.length} octets en 1,5 s ; début : ${h.slice(0, 120)}` : "  aucune réponse en 1,5 s");
    if (got.length) log(id >= 0 ? "  réponse d'identité trouvée (19 00 B6)" : "  pas de réponse d'identité dans ce qui a été lu");
  });
  step("d5", async () => {
    if (reader) { try { await reader.cancel(); } catch (e) {} reader.releaseLock(); reader = null; }
    if (writer) { writer.releaseLock(); writer = null; }
    await port.close(); log("  fermé");
  });
  if (!("serial" in navigator)) log("Ce navigateur n'a pas Web Serial : Chrome ou Edge sur ordinateur.");
})();
