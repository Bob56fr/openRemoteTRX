// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* openRemoteTRX-Autotest, page (docs/prequalif-web-cahier-des-charges.md § 4) : écrans, Web Serial, carte son du
   poste (Web Audio), panneau d'émission, rapport. La logique et la garde d'émission sont dans runner.js (testé sous
   Node) ; ici, les COUPURES D'URGENCE de la page : STOP, Échap, onglet caché, fermeture, erreur, port perdu. */
(function () {
  "use strict";
  const { AtI18n: I18N, AtCiv: civ, AtYaesu: yaesu, AtKenwood: kenwood, AtModels: models, AtRunner: R, AtReport: rep } = window;
  const $ = id => document.getElementById(id);
  const show = id => { for (const s of ["s-home", "s-brand", "s-model", "s-port", "s-run", "s-report"]) $(s).hidden = s !== id; document.body.classList.toggle("compact", id !== "s-home"); window.scrollTo(0, 0); };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  const S = { brand: null, model: null, chosen: null, port: null, detected: null, runner: null, startedAt: null, audio: null, report: null };
  $("ver").textContent = "version " + rep.VERSION;

  // ---------- Accueil, marque, modèle ----------
  const T = I18N.T;
  I18N.apply(document);
  const hasSerial = "serial" in navigator;
  if (!hasSerial) { $("noserial").hidden = false; $("b-start").disabled = true; }
  $("b-start").onclick = () => { buildBrands(); show("s-brand"); };
  // Conditions d'utilisation : à CHAQUE visite (rien n'est retenu), le bouton n'agit que case cochée.
  $("terms-ok").checked = false; $("terms-go").disabled = true;
  $("terms-ok").onchange = () => { $("terms-go").disabled = !$("terms-ok").checked; };
  $("terms-go").onclick = () => {
    if (!$("terms-ok").checked) return;
    $("o-terms").hidden = true;
    if (hasSerial) { buildBrands(); show("s-brand"); }                 // sinon l'accueil montre pourquoi (Chrome ou Edge)
  };

  function buildBrands() {
    const box = $("brands"); box.textContent = "";
    for (const b of models.BRANDS) {
      const c = el("button", "choice", b.name); c.type = "button";
      c.appendChild(el("small", null, b.ready ? T("prêt") : T("bientôt")));
      c.disabled = !b.ready;
      c.onclick = () => { S.brand = b; buildModels(); show("s-model"); };
      box.appendChild(c);
    }
  }
  function buildModels() {
    const box = $("models"); box.textContent = "";
    const add = (m, name, note) => {
      const c = el("button", "choice", name); c.type = "button"; c.appendChild(el("small", null, note));
      c.onclick = () => { S.chosen = m; S.model = m;
        $("port-driver").hidden = !(m && m.piloteIcom && /Windows/i.test(navigator.userAgent));   // pilote 1.80 (2026-11-19)
        $("port-help").textContent = S.brand.family === "yaesu"
          ? T("{name}la CAT passe par le port « Enhanced COM Port » (deux ports « Silicon Labs CP2105 » ; l'autre, « Standard », ne sert pas ici). Vitesse : celle du menu CAT RATE du poste (38400 d'usine), la page essaie 38400, 9600, 19200 et 4800.", { name: m ? m.name + " : " : "" })
          : S.brand.family === "kenwood"
          ? T("{name}la CAT passe par le port « Enhanced COM Port » (ports « Silicon Labs CP2105 »). Vitesse : celle du menu du port USB du poste (115200 d'usine). Pendant l'essai, la page met en marche l'information automatique (AI2, non sauvegardée) : c'est le seul moyen de savoir si le poste émet ; elle est remise à la fin.", { name: m ? m.name + " : " : "" })
          : m ? T("{name} : adresse CI-V d'usine {addr}h.", { name: m.name, addr: m.addr.toString(16).toUpperCase() }) : T("La page cherchera l'adresse du poste.");
        show("s-port"); };
      box.appendChild(c);
    };
    for (const m of models.modelsOf(S.brand.id)) add(m, m.name, (m.verifie ? T("vérifié") : T("non vérifié")) + ` · ${m.maxW} W`);
    add(null, T("Je ne sais pas"), T("la page cherchera"));
  }
  $("b-back-brand").onclick = () => show("s-brand");
  $("b-back-model").onclick = () => show("s-model");

  // ---------- Web Serial ----------
  // Délai maximum d'un appel au port : un pilote qui ne répond plus donne une erreur claire au lieu d'une page figée.
  const within = (p, ms, what) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error(T("{what} : pas de réponse du port en {s} s", { what, s: ms / 1000 }))), ms))]);
  async function openAt(port, baud) {
    await within(port.open({ baudRate: baud, dataBits: 8, stopBits: 1, parity: "none", flowControl: "none" }), 5000, T("ouverture"));
    // RTS et DTR baissés tout de suite : certains postes passent en émission sur ces lignes (réglage USB SEND / Keying).
    try { await within(port.setSignals({ dataTerminalReady: false, requestToSend: false }), 3000, "DTR / RTS"); } catch (e) { /* non géré */ }
    const writer = port.writable.getWriter(), reader = port.readable.getReader();
    let cb = () => {}, reading = true;
    (async () => { try { while (reading) { const { value, done } = await reader.read(); if (done) break; if (value) cb(value); } } catch (e) { /* port fermé ou perdu */ } })();
    return {
      onData(f) { cb = f; },
      async write(bytes) { await writer.write(bytes); },
      async close() { reading = false; try { await reader.cancel(); } catch (e) {} try { reader.releaseLock(); } catch (e) {} try { writer.releaseLock(); } catch (e) {} await within(port.close(), 5000, T("fermeture")); },
    };
  }

  $("b-port").onclick = async () => {
    let port;
    try { port = await navigator.serial.requestPort(); } catch (e) { $("port-status").textContent = "Aucun port choisi."; return; }
    S.port = port; $("b-port").disabled = true;
    const status = $("port-status");
    // Pause de 5 s avant d'ouvrir le port (demande de l'utilisateur, 2026-11-19 : Chrome se figeait à l'ouverture juste
    // après la fenêtre de choix du port).
    for (let s = 5; s > 0; s--) { status.textContent = T("Ouverture du port dans {s} s…", { s }); await new Promise(r => setTimeout(r, 1000)); }
    const onTry = b => { status.textContent = T("Essai à {b} bauds…", { b }); };
    const d = S.brand.family === "yaesu"
      ? await yaesu.detect({ openAt: b => openAt(port, b), model: S.model, bauds: models.YAESU_BAUDS, byId: models.byIdent, onTry })
      : S.brand.family === "kenwood"
      ? await kenwood.detect({ openAt: b => openAt(port, b), model: S.model, bauds: models.KENWOOD_BAUDS, byId: models.byKenwood, onTry })
      : await R.detect({ openAt: b => openAt(port, b), model: S.model, bauds: models.ICOM_BAUDS, byAddr: models.byAddr, onTry });
    $("b-port").disabled = false;
    if (d.error === "port") { status.textContent = T("Port impossible à ouvrir : un autre logiciel l'utilise peut-être (WSJT-X, logiciel du constructeur, station openRemoteTRX). Fermez-le et recommencez."); return; }
    if (d.error) { status.textContent = S.brand.family === "yaesu"
      ? T("Le poste ne répond à aucune vitesse. Vérifiez qu'il est allumé, que c'est le port « Enhanced », et la vitesse CAT RATE dans son menu.")
      : S.brand.family === "kenwood"
      ? T("Le poste ne répond à aucune vitesse. Vérifiez qu'il est allumé, que c'est le port « Enhanced », la vitesse du port USB dans son menu, et que « PSQ/PKS Pin Assignment » n'est pas sur « On ».")
      : T("Le poste ne répond à aucune vitesse. Vérifiez qu'il est allumé, que c'est le bon port, et la vitesse CI-V USB dans son menu."); return; }
    S.detected = d;
    if (!S.model && d.guess) S.model = d.guess;
    startRun();
  };

  // ---------- Carte son ----------
  const audio = {
    inId: null, outId: null, inputLabel: null, outputLabel: null, ctx: null, osc: null,
    hasInput() { return !!this.inId; }, hasOutput() { return !!this.outId; },
    async measureInput(ms) {
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: { exact: this.inId }, echoCancellation: false, noiseSuppression: false, autoGainControl: false } }); }
      catch (e) { return null; }
      const ctx = new AudioContext(); const src = ctx.createMediaStreamSource(stream); const an = ctx.createAnalyser(); an.fftSize = 2048; src.connect(an);
      const buf = new Float32Array(an.fftSize); let sum = 0, n = 0; const end = performance.now() + ms;
      while (performance.now() < end) { await new Promise(r => setTimeout(r, 50)); an.getFloatTimeDomainData(buf); for (const v of buf) { sum += v * v; n++; } }
      stream.getTracks().forEach(t => t.stop()); ctx.close();
      return n ? 10 * Math.log10(sum / n || 1e-12) : null;
    },
    async startTone() {
      this.stopTone();
      const ctx = new AudioContext();
      if (this.outId && ctx.setSinkId) await ctx.setSinkId(this.outId);
      const osc = ctx.createOscillator(), g = ctx.createGain();
      osc.frequency.value = 1000; g.gain.value = 0.25;                            // -12 dBFS
      osc.connect(g).connect(ctx.destination); osc.start();
      this.ctx = ctx; this.osc = osc;
    },
    stopTone() { try { if (this.osc) this.osc.stop(); } catch (e) {} try { if (this.ctx) this.ctx.close(); } catch (e) {} this.osc = null; this.ctx = null; },
  };
  const GUESS = /USB Audio CODEC|USB Audio Device|IC-?7300|IC-?705|IC-?9700|IC-?7610|C-Media/i;
  function chooseAudio() {
    return new Promise(async resolve => {
      $("o-audio").hidden = false; $("a-status").textContent = T("Demande d'accès à la carte son…");
      try { const s = await navigator.mediaDevices.getUserMedia({ audio: true }); s.getTracks().forEach(t => t.stop()); }
      catch (e) { $("a-status").textContent = T("Accès refusé : les essais de la carte son seront sautés."); $("a-status").dataset.refused = "1"; }
      const devs = await navigator.mediaDevices.enumerateDevices().catch(() => []);
      const fill = (sel, kind) => {
        sel.textContent = "";
        const list = devs.filter(d => d.kind === kind && d.deviceId && d.deviceId !== "default" && d.deviceId !== "communications");
        sel.appendChild(el("option", null, T("— aucune —"))).value = "";
        for (const d of list) { const o = el("option", null, d.label || T("(sans nom)")); o.value = d.deviceId; sel.appendChild(o); }
        const g = list.find(d => GUESS.test(d.label)); if (g) sel.value = g.deviceId;
      };
      fill($("a-in"), "audioinput"); fill($("a-out"), "audiooutput");
      if (!$("a-status").dataset.refused) $("a-status").textContent = T("Carte du poste proposée quand son nom est reconnu : vérifiez.");
      const done = ok => {
        $("o-audio").hidden = true;
        if (ok) { audio.inId = $("a-in").value || null; audio.outId = $("a-out").value || null;
                  audio.inputLabel = audio.inId ? $("a-in").selectedOptions[0].textContent : null; audio.outputLabel = audio.outId ? $("a-out").selectedOptions[0].textContent : null; }
        else { audio.inId = audio.outId = null; }
        resolve(ok);
      };
      $("a-ok").onclick = () => done(true); $("a-skip").onclick = () => done(false);
    });
  }

  // ---------- Autorisation, puissance à la main ----------
  function authorize(info) {
    return new Promise(resolve => {
      const w = info.watts != null ? T(" ({w} W sur {max} W)", { w: info.watts.toFixed(info.watts < 10 ? 1 : 0), max: info.maxW }) : "";
      $("auth-where").textContent = T("Fréquence {f} MHz, puissance réglée à {pct} %{w} avant la première émission.", { f: R.fmtHz(info.hz), pct: info.pct, w });
      const ul = $("auth-list"); ul.textContent = "";
      for (const [c, t, ms] of info.emissions) ul.appendChild(el("li", null, `${c} : ${t}, ${(ms / 1000).toFixed(0)} s`));
      $("auth-load").checked = false; $("auth-ok").disabled = true;
      $("auth-load").onchange = () => { $("auth-ok").disabled = !$("auth-load").checked; };
      $("o-auth").hidden = false;
      const done = v => { $("o-auth").hidden = true; resolve(v); };
      $("auth-ok").onclick = () => done($("auth-load").checked); $("auth-no").onclick = () => done(false);
    });
  }
  function confirmManualPower(info) {
    return new Promise(resolve => {
      const w = info.watts != null ? ` (${info.watts.toFixed(1)} W)` : "";
      $("power-t").textContent = T("La puissance n'a pas pu être réglée ou relue par la CAT. Réglez-la à la main à {pct} %{w} sur le poste, puis confirmez.", { pct: info.pct, w });
      $("o-power").hidden = false;
      const done = v => { $("o-power").hidden = true; resolve(v); };
      $("power-ok").onclick = () => done(true); $("power-no").onclick = () => done(false);
    });
  }

  // ---------- Écran des essais ----------
  const SYM = { ok: "✓", avert: "!", echec: "✗", na: "–", saute: "–", cur: "●", todo: "○" };
  let stepIndex = 0;
  function buildSteps() {
    const ol = $("steps"); ol.textContent = "";
    R.STEPS.forEach(([c, t]) => { const li = el("li", "todo"); li.id = "st-" + c; li.append(el("span", "s", SYM.todo), el("span", "c", c), el("span", null, T(t))); ol.appendChild(li); });
    $("stept").textContent = R.STEPS.length;
  }
  function setStep(code, state) {
    const li = $("st-" + code); if (!li) return;
    li.className = state; li.firstChild.textContent = SYM[state] || "○";
    const i = R.STEPS.findIndex(s => s[0] === code);
    if (state === "cur" && i >= 0) { stepIndex = i; $("stepn").textContent = i + 1; $("progbar").style.width = (i / R.STEPS.length * 100) + "%"; }
  }
  function poTicks(maxW) {
    const t = $("po-ticks"); t.textContent = "";
    const marks = [[0, "0"], [10, String(maxW / 10)], [25, String(maxW / 4)], [50, String(maxW / 2)], [75, String(maxW * 3 / 4)], [100, maxW + " W"]];
    marks.forEach(([p, txt], i) => { const s = el("span", i === 0 ? "first" : i === marks.length - 1 ? "last" : null, txt); s.style.left = p + "%"; t.appendChild(s); });
    $("po-mark").style.left = "10%";
  }
  const SWR_PTS = [[1, 0], [1.5, 25], [2, 45], [3, 70], [5, 86], [10, 100]];
  const swrPos = v => { for (let i = 1; i < SWR_PTS.length; i++) { const [a, pa] = SWR_PTS[i - 1], [b, pb] = SWR_PTS[i]; if (v <= b) return pa + (pb - pa) * (v - a) / (b - a); } return 100; };
  const fmt = (v, d) => v.toFixed(d).replace(".", ",");
  const peaks = {};
  function peak(k, v) { const now = performance.now(), p = peaks[k]; if (!p || v >= p.v || now - p.t > 1000) peaks[k] = { v, t: now }; return peaks[k].v; }
  function meter(k, pos, color, text, peakPos, peakText) {
    $(k + "-fill").style.width = pos + "%"; $(k + "-fill").style.background = color; $(k + "-peak").style.left = peakPos + "%";
    $(k + "-v").textContent = text; $(k + "-p").textContent = peakText;
  }
  function resetMeters() {
    for (const k of ["po", "swr", "alc"]) { $(k + "-fill").style.width = "0"; $(k + "-peak").style.left = "0"; $(k + "-v").textContent = "—"; $(k + "-p").textContent = ""; delete peaks[k]; }
  }
  function onMeters(s, maxW, na) {
    for (const k of ["po", "swr", "alc"]) {
      const off = na.includes(k);
      $("m-" + k).classList.toggle("na", off);
      if (off) { $(k + "-v").textContent = T("non disponible"); $(k + "-p").textContent = T("le poste ne le donne pas"); }
    }
    if (s.po != null) { const w = maxW ? s.po * maxW / 100 : null, p = peak("po", s.po); meter("po", Math.min(100, s.po), "var(--ok)", w != null ? fmt(w, w < 10 ? 1 : 0) + " W" : fmt(s.po, 0) + " %", Math.min(100, p), T("crête {v}", { v: maxW ? fmt(p * maxW / 100, 1) + " W" : fmt(p, 0) + " %" })); }
    if (s.swr != null) { const p = peak("swr", s.swr), c = s.swr <= 1.5 ? "var(--ok)" : s.swr <= 2 ? "var(--warn)" : "var(--bad)"; meter("swr", swrPos(s.swr), c, fmt(s.swr, 2), swrPos(p), T("crête {v}", { v: fmt(p, 2) })); $("swr-v").style.color = s.swr > 2 ? "var(--bad)" : s.swr > 1.5 ? "var(--warn)" : ""; }
    if (s.alc != null) { const p = peak("alc", s.alc); meter("alc", s.alc, s.alc > 50 ? "var(--bad)" : "var(--ok)", fmt(s.alc, 0) + " %", p, T("crête {v}", { v: fmt(p, 0) + " %" })); }
  }
  let countTimer = null, txInfo = null;
  function onTx(ev) {
    const tx = $("tx"); tx.hidden = false;
    if (ev.on) {
      tx.classList.remove("rx"); $("bandtxt").textContent = T("Émission en cours"); $("countbox").hidden = false;
      resetMeters();
      const ms = txInfo ? txInfo.ms : ev.maxTx, t0 = performance.now();
      clearInterval(countTimer);
      countTimer = setInterval(() => { const left = Math.max(0, ms - (performance.now() - t0)); $("count").textContent = fmt(left / 1000, 1) + " s"; $("countbar").style.width = (left / ms * 100) + "%"; }, 100);
    } else {
      clearInterval(countTimer); tx.classList.add("rx"); $("countbox").hidden = true;
      $("bandtxt").textContent = ev.rx ? T("Réception") : T("RÉCEPTION NON RELUE : coupez le poste à la main");
      resetMeters();
    }
  }
  function onTxInfo(ev) {
    txInfo = ev; const i = ev.info || {};
    $("txwhat").innerHTML = "";
    $("txwhat").append(T("Essai "), el("b", null, ev.code), T(" : {what}. Puissance {pct} % du poste{w}, charge fictive.", { what: i.what || "", pct: S.runner ? S.runner.o.power : 10, w: S.model ? " (" + fmt(S.model.maxW / 10, S.model.maxW < 100 ? 1 : 0) + " W)" : "" }));
    $("freq").textContent = R.fmtHz(i.hz); $("mode").textContent = i.mode || "—";
  }
  const ui = {
    event(ev) {
      if (ev.type === "now") $("nowtxt").textContent = ev.text;
      else if (ev.type === "step") setStep(ev.code, ev.state);
      else if (ev.type === "result") { setStep(ev.result.code, ev.result.status); $("lastres").hidden = false; $("lastres-t").textContent = `${ev.result.code} : ${ev.result.text}`; }
      else if (ev.type === "tx") onTx(ev);
      else if (ev.type === "tx-info") onTxInfo(ev);
      else if (ev.type === "meters") onMeters(ev.sample, ev.maxW, ev.na);
      else if (ev.type === "error") { $("nowtxt").textContent = "Erreur de la page : " + ev.text + " (retour en réception)."; }
    },
    chooseAudio, authorize, confirmManualPower,
  };

  // ---------- Coupures d'urgence ----------
  const emergency = reason => { if (S.runner) S.runner.stop(reason); };
  $("b-stop").onclick = () => emergency("stop");
  document.addEventListener("keydown", e => { if (e.key === "Escape") emergency("stop"); });
  document.addEventListener("visibilitychange", () => { if (document.hidden && S.runner && S.runner.guard.on) emergency("onglet_cache"); });
  window.addEventListener("pagehide", () => emergency(T("fermeture")));
  window.addEventListener("beforeunload", e => { if (S.runner && S.runner.guard.on) { emergency(T("fermeture")); e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("error", () => emergency("erreur"));
  window.addEventListener("unhandledrejection", () => emergency("erreur"));
  if (hasSerial) navigator.serial.addEventListener("disconnect", e => {
    if (S.port && e.target === S.port) { emergency("port_perdu"); $("nowtxt").textContent = T("Le port USB du poste a disparu : si le poste émet, coupez-le à la main."); }
  });

  // ---------- Déroulé ----------
  async function startRun() {
    show("s-run"); buildSteps(); $("tx").hidden = true; $("lastres").hidden = true;
    $("prog-model").textContent = S.model ? S.model.name : T("modèle inconnu");
    if (S.model) poTicks(S.model.maxW);
    S.startedAt = new Date().toISOString();
    S.runner = new R.Runner({ link: S.detected.link, model: S.model, audio, ui, detected: S.detected });
    setStep("R1", "cur");
    const out = await S.runner.run();
    $("progbar").style.width = "100%"; $("b-stop").hidden = true;
    S.report = await rep.build({ brand: S.brand, model: S.model, chosenModel: S.chosen, detected: S.detected, usb: S.port.getInfo ? S.port.getInfo() : null,
                                 audio, run: out, trace: S.detected.link.trace, startedAt: S.startedAt, platform: platform() });
    try { await S.detected.transport.close(); } catch (e) { /* rien */ }
    showReport();
  }
  function platform() {
    const p = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    return /win/i.test(p) ? "Windows" : /mac/i.test(p) ? "macOS" : /linux/i.test(p) ? "Linux" : null;
  }
  const VERDICT = { ok: T("Votre poste a passé tous les essais disponibles."), avert: T("Votre poste répond, avec des points à vérifier."), echec: T("Au moins un essai a échoué.") };
  function showReport() {
    const s = rep.summary(S.report);
    $("verdict").className = "verdict " + s.verdict; $("verdict").textContent = VERDICT[s.verdict];
    const tb = $("restable"); tb.textContent = "";
    for (const l of s.lines) {
      const name = T((R.STEPS.find(x => x[0] === l.code) || [, l.code])[1]);
      const row = el("div", "resitem"), t = el("div", "t");
      t.append(el("b", null, name));
      // Ce qui ne va pas saute aux yeux : un résultat « à vérifier » en orange, un échec en rouge ; dans une ligne en
      // plusieurs parties (« 13 OK : … ; relues fausses : … »), seules les parties en défaut sont colorées.
      const bad = l.statut === "echec" ? "txt-bad" : l.statut === "avert" ? "txt-warn" : null;
      const parts = String(l.texte).split(" ; ");
      parts.forEach((p, i) => {
        if (i) t.append(" ; ");
        const fine = !bad || (parts.length > 1 && /^\d+ OK/.test(p));
        t.append(fine ? p : el("span", /NON REMIS|NOT RESTORED/.test(p) ? "txt-bad" : bad, p));
      });
      row.append(el("span", "c", l.code), t, el("span", "pill " + l.statut, T(l.label)));
      tb.appendChild(row);
    }
    show("s-report"); $("b-stop").hidden = false;
  }
  $("b-download").onclick = () => {
    const blob = new Blob([JSON.stringify(S.report, null, 2)], { type: "application/json" });
    const a = el("a"); a.href = URL.createObjectURL(blob); a.download = rep.fileName(S.report);
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  };
  $("b-print").onclick = () => window.print();
  $("b-again").onclick = () => { S.runner = null; S.detected = null; show("s-brand"); buildBrands(); };
})();
