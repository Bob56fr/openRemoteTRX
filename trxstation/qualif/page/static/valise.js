// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Page de la valise de qualification (lot G2a) : client du bus de la valise par WebSocket.
// Mots de sécurité SEULEMENT dans la fenêtre d'intervention, tapés au clavier (collage refusé) : message « mot ».
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  let T = {};
  let ws = null;
  let finished = false;
  const open = new Map();          // questions ouvertes : id -> événement
  const lines = [];
  let ivId = null;                 // question de mot affichée dans la fenêtre
  let ivTrusted = true;            // toute la saisie du mot vient du clavier
  let ivKeys = 0;                  // touches de caractère réellement frappées dans le champ
  let audio = null;

  function t(key, fields) {
    let s = T[key] || key;
    for (const [k, v] of Object.entries(fields || {})) s = s.split("{" + k + "}").join(String(v));
    return s;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ------------------------------------------------------------------ son

  function ensureAudio() {
    if (!audio) {
      try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { audio = null; }
    }
    if (audio && audio.state === "suspended") audio.resume();
  }

  function beep(freqs, dur, gain) {
    if (!audio) return;
    let at = audio.currentTime;
    for (const f of freqs) {
      const o = audio.createOscillator();
      const g = audio.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(gain, at);
      g.gain.exponentialRampToValueAtTime(0.001, at + dur);
      o.connect(g).connect(audio.destination);
      o.start(at);
      o.stop(at + dur);
      at += dur + 0.05;
    }
  }

  document.addEventListener("pointerdown", ensureAudio);
  document.addEventListener("keydown", ensureAudio);

  // ------------------------------------------------------------------ envoi

  function send(message) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }

  function answer(id, text) {
    notice("");
    send({ type: "reponse", id: id, text: text });
  }

  function notice(text, grave) {
    const a = $("avis");
    a.textContent = text;
    a.className = "avis" + (grave ? " grave" : "");
    a.hidden = !text;
  }

  $("stop").addEventListener("click", async () => {
    try {
      const r = await fetch("/api/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      notice(data.ok ? t("stop.done") : t("stop.failed", { message: data.message || "?" }), !data.ok);
    } catch (e) {
      notice(t("stop.failed", { message: String(e) }), true);
    }
  });

  // ------------------------------------------------------------------ bandeau et journal

  function status(e) {
    $("poste").textContent = e.poste || "";
    $("details").textContent = t("hamlib") + " " + (e.hamlib || "?") + " · " + t("folder") + " " + (e.dossier || "");
    const st = $("v-station");
    st.textContent = t("station") + " : " + t(e.station ? "station.on" : "station.off");
    st.className = "voyant" + (e.station ? " ok" : "");
    const br = $("v-branchement");
    const b = e.branchement || "inconnu";
    br.textContent = t("connection") + " : " + t("connection." + b);
    br.className = "voyant" + (b === "charge" ? " charge" : b === "antenne" ? " ok" : " attention");
  }

  function addLine(text) {
    for (const l of String(text).split("\n")) lines.push(l);
    if (lines.length > 5000) lines.splice(0, lines.length - 5000);
  }

  function showLines() {
    $("journal").textContent = lines.join("\n");
    const recent = $("recent");
    recent.textContent = lines.slice(-40).join("\n");
    recent.scrollTop = recent.scrollHeight;
  }

  // ------------------------------------------------------------------ question en cours

  function choiceLabel(c) {
    if (c.texte) return c.texte;
    if (c.libelle) return t("choice." + c.libelle);
    return T["menu." + c.cle] || c.cle;
  }

  function renderChoice(zone, q) {
    const main = q.choix.some((c) => T["menu." + c.cle] && !c.texte && !c.libelle);
    if (main) {
      zone.appendChild(el("h2", "", t("menu.title")));
      zone.appendChild(el("p", "aide", t("menu.hint")));
    } else {
      zone.appendChild(el("p", "invite", q.texte.trim()));
    }
    const grid = el("div", "choix");
    for (const c of q.choix) {
      const b = el("button");
      b.type = "button";
      if (c.fait) b.classList.add("fait");
      if (c.bloque) b.classList.add("bloque");
      b.appendChild(el("span", "cle", c.cle));
      b.appendChild(document.createTextNode(" " + choiceLabel(c)));
      if (c.fait) b.appendChild(el("span", "marque", "✓"));
      let info = c.info || "";
      if (c.cle === "7" && main && info) info += " " + t("photos");
      if (c.etat) info = c.etat;
      if (c.bloque) info = t("blocked." + c.bloque);
      if (info) b.appendChild(el("span", "info", info));
      b.addEventListener("click", () => answer(q.id, c.cle));
      grid.appendChild(b);
    }
    zone.appendChild(grid);
  }

  function renderInput(zone, q, secret) {
    zone.appendChild(el("p", "invite", q.texte.trim()));
    const row = el("div", "ligne-saisie");
    const input = el("input");
    input.type = secret ? "password" : "text";
    input.autocomplete = "off";
    const go = el("button", "", t("send"));
    go.type = "button";
    const submit = () => answer(q.id, input.value);
    go.addEventListener("click", submit);
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") submit(); });
    row.appendChild(input);
    row.appendChild(go);
    zone.appendChild(row);
    setTimeout(() => input.focus(), 0);
  }

  function renderButtons(zone, q, buttons) {
    zone.appendChild(el("p", "invite", q.texte.trim()));
    const row = el("div", "boutons");
    buttons.forEach(([label, value, second]) => {
      const b = el("button", second ? "second" : "", label);
      b.type = "button";
      b.addEventListener("click", () => answer(q.id, value));
      row.appendChild(b);
    });
    zone.appendChild(row);
  }

  function render() {
    const zone = $("zone");
    zone.replaceChildren();
    const questions = [...open.values()];
    const words = questions.filter((q) => q.genre === "mot");
    showIntervention(words.length ? words[words.length - 1] : null);
    const others = questions.filter((q) => q.genre !== "mot");
    const q = others.length ? others[others.length - 1] : null;
    if (finished) {
      zone.appendChild(el("p", "attente", t("finished")));
    } else if (!q) {
      zone.appendChild(el("p", "attente", t("waiting")));
    } else if (q.genre === "choix" && Array.isArray(q.choix)) {
      renderChoice(zone, q);
    } else if (q.genre === "oui_non") {
      renderButtons(zone, q, [[t("yes"), "o"], [t("no"), "n"], [t("enter"), "", true]]);
    } else if (q.genre === "fait") {
      renderButtons(zone, q, [[t("done"), ""]]);
    } else {
      renderInput(zone, q, q.genre === "secret");
    }
  }

  // ------------------------------------------------------------------ fenêtre d'intervention

  function showIntervention(q) {
    const box = $("intervention");
    if (!q) {
      box.hidden = true;
      ivId = null;
      return;
    }
    if (q.id === ivId) return;
    ivId = q.id;
    ivTrusted = true;
    ivKeys = 0;
    $("iv-why").textContent = t("why." + (q.famille || "EMETTRE"));
    $("iv-what").textContent = (q.contexte || "").trim();
    $("iv-t-what").hidden = !q.contexte;
    $("iv-label").textContent = t("iv.word", { word: q.mot });
    $("iv-erreur").hidden = true;
    const input = $("iv-mot");
    input.value = "";
    box.hidden = false;
    ensureAudio();
    beep([880, 660, 880], 0.18, 0.6);              // bip BIEN AUDIBLE (cahier § 3)
    setTimeout(() => input.focus(), 0);
  }

  function ivError(text) {
    const e = $("iv-erreur");
    e.textContent = text;
    e.hidden = false;
    ivInput.focus();                               // l'opérateur retape tout de suite le mot
  }

  const ivInput = $("iv-mot");
  for (const kind of ["paste", "drop"]) {
    ivInput.addEventListener(kind, (ev) => { ev.preventDefault(); ivError(t("iv.paste")); });
  }
  ivInput.addEventListener("beforeinput", (ev) => {
    if (!ev.isTrusted || /insertFromPaste|insertFromDrop|insertReplacementText/.test(ev.inputType || "")) {
      ev.preventDefault();
      ivTrusted = ivTrusted && ev.isTrusted;
      ivError(t("iv.paste"));
    }
  });
  ivInput.addEventListener("input", (ev) => { if (!ev.isTrusted) ivTrusted = false; });
  ivInput.addEventListener("keydown", (ev) => { if (ev.isTrusted && ev.key && ev.key.length === 1) ivKeys += 1; });

  function submitWord(ev) {
    const q = open.get(ivId);
    if (!q) return;
    const typed = ivInput.value.trim().toUpperCase();
    const accepted = [String(q.mot).toUpperCase(), String(q.famille || "").toUpperCase()];
    if (!accepted.includes(typed)) {
      ivError(t("iv.wrong", { word: q.mot }));
      return;
    }
    // Frappé au clavier : aucun collage ni saisie simulée, et au moins une touche par lettre du mot
    const typedByHand = ivTrusted && ev.isTrusted && ivKeys >= typed.length;
    if (!typedByHand) {
      ivError(t("err.not_typed"));
      return;
    }
    send({ type: "mot", id: q.id, text: ivInput.value, trusted: true });
  }

  $("iv-valider").addEventListener("click", submitWord);
  ivInput.addEventListener("keydown", (ev) => { if (ev.key === "Enter") submitWord(ev); });
  $("iv-passer").addEventListener("click", (ev) => {
    if (ivId !== null) send({ type: "mot", id: ivId, text: "", trusted: ev.isTrusted });
  });

  // ------------------------------------------------------------------ événements du bus

  function onEvent(e, live) {
    switch (e.type) {
      case "ligne": addLine(e.texte); break;
      case "statut": status(e); break;
      case "question": open.set(e.id, e); break;
      case "reponse": case "annule": open.delete(e.id); break;
      case "fin": finished = true; break;
      case "stop": if (live) addLine("— STOP —"); break;
      case "avis": if (live) notice(e.texte, true); break;
      case "erreur":
        if (ivId !== null) ivError(t(e.cle)); else notice(t(e.cle), true);
        return;
      default: break;
    }
  }

  function texts() {
    $("titre").textContent = t("title");
    document.title = t("title");
    $("v-pilote").textContent = t("who");
    $("stop").textContent = t("stop");
    $("stop").title = t("stop.title");
    $("t-recent").textContent = t("recent");
    $("t-journal").textContent = t("journal");
    $("iv-titre").textContent = t("iv.title");
    $("iv-t-why").textContent = t("iv.why");
    $("iv-t-what").textContent = t("iv.what");
    $("iv-rule").textContent = t("iv.rule");
    $("iv-valider").textContent = t("iv.validate");
    $("iv-passer").textContent = t("iv.skip");
  }

  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onmessage = (m) => {
      let e;
      try { e = JSON.parse(m.data); } catch (err) { return; }
      if (e.type === "init") {
        T = e.textes || {};
        texts();
        open.clear();
        lines.length = 0;
        finished = !!e.fin;
        for (const ev of e.evenements || []) onEvent(ev, false);
        open.clear();
        for (const q of e.ouvertes || []) open.set(q.id, q);
        notice("");
      } else {
        onEvent(e, true);
      }
      showLines();
      render();
    };
    ws.onclose = () => {
      if (finished) return;
      notice(t("lost"), true);
      setTimeout(connect, 2000);
    };
  }

  connect();
})();
