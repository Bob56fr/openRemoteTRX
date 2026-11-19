// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Page de la valise de qualification (lots G2a et G2b) : client du bus de la valise par WebSocket.
// Les tuiles ne font que RÉPONDRE au menu de la valise (touches existantes) ; aucun essai n'est inventé ici.
// Mots de sécurité SEULEMENT dans la fenêtre d'intervention, tapés au clavier (collage refusé) : message « mot ».
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  let T = {};
  let ws = null;
  let finished = false;
  const open = new Map();          // questions ouvertes : id -> événement
  const lines = [];
  let tiles = null;                // dernier événement « tuiles »
  let current = null;              // touche de l'essai en cours (lancé d'ici ou enchaîné)
  let chain = null;                // enchaînement en cours : { rang, total }
  let report = null;               // dernier rapport fabriqué (chemin)
  let meters = { actif: false };   // dernières mesures relues par les essais
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

  function menuQuestion() {
    for (const q of open.values()) if (q.role === "menu") return q;
    return null;
  }

  function launch(key) {              // une tuile, un thème, « Tout lancer » : réponse au menu de la valise
    const q = menuQuestion();
    if (!q) return;
    current = key.includes(":") || key === "tout" || key === "echecs" ? null : key;
    answer(q.id, key);
  }

  function notice(text, grave) {
    const a = $("avis");
    a.textContent = text;
    a.className = "avis" + (grave ? " grave" : "");
    a.hidden = !text;
  }

  function reportNotice(path) {     // rapport fabriqué : où il est, et un bouton pour ouvrir son dossier
    const a = $("avis");
    a.replaceChildren(el("span", "", t("report.done", { path: path }) + " "));
    const b = el("button", "btn-mini", t("report.open"));
    b.type = "button";
    b.addEventListener("click", () => fetch("/api/open_report", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }));
    a.appendChild(b);
    a.className = "avis";
    a.hidden = false;
  }

  async function stopAll() {        // STOP et « Arrêter l'enchaînement » : même chemin (T 0, puis retour au menu)
    try {
      const r = await fetch("/api/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      notice(data.ok ? t("stop.done") : t("stop.failed", { message: data.message || "?" }), !data.ok);
    } catch (e) {
      notice(t("stop.failed", { message: String(e) }), true);
    }
  }
  $("arret-seq").addEventListener("click", stopAll);

  $("stop").addEventListener("click", async () => {
    try {
      const r = await fetch("/api/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await r.json();
      notice(data.ok ? t("stop.done") : t("stop.failed", { message: data.message || "?" }), !data.ok);
    } catch (e) {
      notice(t("stop.failed", { message: String(e) }), true);
    }
  });
  $("tout").addEventListener("click", () => launch("tout"));
  $("echecs").addEventListener("click", () => launch("echecs"));

  // ------------------------------------------------------------------ bandeau, mesures, journal

  let statusNow = {};

  function status(update) {
    const e = statusNow = Object.assign({}, statusNow, update);   // une mise à jour peut ne porter qu'un champ
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

  function fmt(v, digits, unit) {
    if (v === null || v === undefined || v === "") return "—";
    const n = Number(v);
    return (Number.isFinite(n) ? n.toFixed(digits) : String(v)) + (unit || "");
  }

  function showMeters() {
    const m = meters;
    const tx = m.actif !== false && m.ptt === true;
    $("txband").hidden = !tx;
    $("txband").textContent = t("tx.band");
    const p = $("v-ptt");
    p.textContent = m.ptt === true ? t("ptt.tx") : m.ptt === false ? t("ptt.rx") : t("ptt.unknown");
    p.className = "voyant" + (tx ? " tx" : m.ptt === false ? " ok" : "");
    const freq = m.freq_hz ? (m.freq_hz / 1e6).toFixed(3) + " MHz" + (m.mode ? " " + m.mode : "") : "—";
    $("m-freq").textContent = freq;
    $("m-po").textContent = fmt(m.po, 2);
    $("m-swr").textContent = fmt(m.swr, 1);
    $("m-alc").textContent = fmt(m.alc, 2);
    $("m-s").textContent = fmt(m.s_db, 0, " dB");
    document.querySelector(".mesures").classList.toggle("vieilles", m.actif === false);
    // Panneau de droite calé sous l'en-tête, dont la hauteur change avec le bandeau ÉMISSION
    document.documentElement.style.setProperty("--haut", ($("bandeau").offsetHeight + 12) + "px");
  }

  function addLine(text) {
    for (const l of String(text).split("\n")) lines.push(l);
    if (lines.length > 5000) lines.splice(0, lines.length - 5000);
  }

  function lastLines(n) {
    return lines.filter((l) => l.trim()).slice(-n).join("\n");
  }

  // Ligne du terminal rendue lisible (bloc de droite) : alignements du terminal retirés, flèches, titres et
  // alertes repérés ; le journal complet (en bas de page) reste tel quel.
  function tidy(line) {
    let s = String(line).trim();
    let cls = "l";
    if (/^!!!/.test(s) || /ATTENTION|REMETTRE|TO RESTORE|RESTORE BY HAND/i.test(s)) {
      cls += " alerte";
      s = s.replace(/^!+\s*/, "");
    }
    if (/^(===|>>>|---)/.test(s)) {
      cls += " titre";
      s = s.replace(/^[=>-]+\s*/, "").replace(/\s*[=-]+$/, "");
    }
    s = s.replace(/^\[\s*([^\]]*?)\s*\]\s*/, "$1 · ");          // « [OK     ] Mode AM » -> « OK · Mode AM »
    s = s.replace(/\s*->\s*/g, " → ").replace(/\s{2,}/g, " · ");
    return [cls, s];
  }

  function showLines() {
    $("journal").textContent = lines.join("\n");
    $("maintenant").textContent = finished ? t("finished") : menuQuestion() ? t("ready") : tidy(lastLines(1))[1];
    const recent = $("recent");
    recent.replaceChildren();
    for (const l of lines.filter((x) => x.trim()).slice(-14)) {
      const [cls, text] = tidy(l);
      recent.appendChild(el("div", cls, text));
    }
    recent.scrollTop = recent.scrollHeight;
  }

  // ------------------------------------------------------------------ tuiles

  function itemLabel(it) {
    return it.texte || T["menu." + it.cle] || it.cle;
  }

  let follow = null;                // tuile en cours : gardée visible pendant l'essai
  let followed = null;

  function renderTiles() {
    follow = null;
    const box = $("themes");
    box.replaceChildren();
    const menu = menuQuestion();
    $("tout").disabled = $("echecs").disabled = !menu;
    $("arret-seq").hidden = !chain || !!menu;
    $("seq-info").textContent = chain && !menu ? t("seq.running", { rank: chain.rang, total: chain.total }) : "";
    for (const b of document.querySelectorAll("#station-boutons button")) {
      // « Démarrer » grisé si la station tourne, « Arrêter » si elle est arrêtée
      const useless = (b.dataset.cle === "d" && statusNow.station === true) ||
        (b.dataset.cle === "a" && statusNow.station === false);
      b.disabled = !menu || useless;
    }
    if (!tiles) return;
    $("compte").textContent = t("progress", { done: tiles.faits, total: tiles.total });
    $("prog").style.width = (tiles.total ? (tiles.faits / tiles.total) * 100 : 0) + "%";
    const cols = [el("div", "colonne"), el("div", "colonne")];
    box.appendChild(cols[0]);
    box.appendChild(cols[1]);
    for (const th of tiles.themes) {
      const sec = el("section", "theme");
      const h = el("header");
      h.appendChild(el("h3", "", t("theme." + th.id)));
      h.appendChild(el("span", "ou " + th.ou, t("where." + th.ou)));
      const all = el("button", "btn-mini", t("run.theme"));
      all.type = "button";
      all.disabled = !menu;
      all.addEventListener("click", () => launch("theme:" + th.id));
      h.appendChild(all);
      sec.appendChild(h);
      const ul = el("ul");
      for (const it of th.essais) {
        const running = current === it.cle && !menu;
        const state = running ? "encours" : it.etat;
        const li = el("li", "essai " + state + (it.bloque ? " bloque" : ""));
        if (running) follow = li;
        li.appendChild(el("span", "pt " + state));
        const txt = el("div");
        const name = itemLabel(it);
        const optional = it.facultatif && !name.toLowerCase().includes(t("optional").toLowerCase());
        txt.appendChild(el("div", "n", name + (optional ? " · " + t("optional") : "")));
        if (it.bloque) txt.appendChild(el("div", "raison", t("blocked." + it.bloque)));
        if (it.couvert && it.etat === "a_faire") {      // essai à la main que la valise fait elle-même (A1…A8)
          txt.appendChild(el("div", "d", t("covered", { key: "A" + it.couvert.split(".")[1] })));
        }
        txt.appendChild(el("div", "d", running ? t("state.encours") : it.detail || t("state." + it.etat)));
        li.appendChild(txt);
        if (it.etat !== "absent") {
          const b = el("button", "btn-mini", it.etat === "a_faire" ? "▶" : "↻");
          b.type = "button";
          b.title = t(it.etat === "a_faire" ? "run.one" : "run.again");
          b.disabled = !menu || !!it.bloque;
          if (it.bloque) b.title = t("blocked." + it.bloque);
          b.addEventListener("click", () => launch(it.cle));
          li.appendChild(b);
        }
        ul.appendChild(li);
      }
      sec.appendChild(ul);
      cols[RIGHT_THEMES.includes(th.id) ? 1 : 0].appendChild(sec);
    }
  }
  // Deux colonnes indépendantes (sans trous) : à droite la réception et les essais automatiques, à gauche le
  // reste, essais À LA MAIN juste sous l'émission (essai du 2026-11-19 : on ne les trouvait pas)
  const RIGHT_THEMES = ["reception", "auto"];

  function stationButtons() {
    const box = $("station-boutons");
    if (box.childElementCount) return;
    for (const key of ["d", "a", "7", "q"]) {
      const b = el("button", key === "q" ? "second" : "", T["menu." + key] || key);
      b.type = "button";
      b.dataset.cle = key;
      b.addEventListener("click", () => launch(key));
      box.appendChild(b);
    }
  }

  function legend() {
    const box = $("legende");
    box.replaceChildren();
    for (const s of ["ok", "partiel", "echec", "encours", "a_faire", "absent"]) {
      const span = el("span");
      span.appendChild(el("span", "pt " + s));
      span.lastChild.style.display = "inline-block";
      span.appendChild(document.createTextNode(" " + t("state." + s)));
      box.appendChild(span);
    }
  }

  // ------------------------------------------------------------------ question en cours (hors menu)

  function withLinks(tag, cls, text) {      // adresses http(s) cliquables, ouvertes dans un NOUVEL onglet
    const e = el(tag, cls);
    const parts = String(text).split(/(https?:\/\/[^\s),;]+)/);
    parts.forEach((part, i) => {
      if (i % 2) {
        const a = el("a", "lien", part);
        a.href = part;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        e.appendChild(a);
      } else if (part) {
        e.appendChild(document.createTextNode(part));
      }
    });
    return e;
  }

  function choiceLabel(c) {
    if (c.texte) return c.texte;
    if (c.libelle) return t("choice." + c.libelle);
    return T["menu." + c.cle] || c.cle;
  }

  function renderChoice(zone, q) {
    zone.appendChild(withLinks("p", "invite", q.texte.trim()));
    const grid = el("div", "choix");
    for (const c of q.choix) {
      const b = el("button");
      b.type = "button";
      if (c.fait) b.classList.add("fait");
      b.appendChild(el("span", "cle", c.cle));
      b.appendChild(document.createTextNode(" " + choiceLabel(c)));
      if (c.etat) b.appendChild(el("span", "info", c.etat));
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

  function drillTitle(id) {
    for (const th of (tiles && tiles.themes) || []) {
      for (const it of th.essais) if (it.essai === id) return it.texte;
    }
    return t("drill.title");
  }

  function bigButton(label, cls, onClick) {
    const b = el("button", "gros " + (cls || ""), label);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  function renderDrill(zone, q) {
    const [, id, , step, measured] = q.role.split(":");
    zone.appendChild(el("div", "surtitre", t("drill.title")));
    zone.appendChild(el("h2", "", drillTitle(id)));
    const tot = statusNow.tot_s ? Math.round(statusNow.tot_s) : "?";
    zone.appendChild(el("p", "but", t("drill." + id + ".but")));
    if (step === "debut" || step === "repere" || step === "fin") {
      zone.appendChild(el("h3", "", t("drill.steps")));
      const ol = el("ol", "etapes");
      for (const s of T["drill." + id + ".steps"] || []) ol.appendChild(el("li", "", s));
      zone.appendChild(ol);
      zone.appendChild(el("h3", "", t("drill.expected")));
      zone.appendChild(el("p", "", t("drill." + id + ".expected", { tot: tot })));
      if (statusNow.page_station) {
        const a = el("a", "lien-station", t("drill.station_link"));
        a.href = statusNow.page_station;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        zone.appendChild(a);
      }
      if (T["drill." + id + ".mark"]) zone.appendChild(el("p", "cote", t("drill.side")));
    }
    const row = el("div", "boutons gros-boutons");
    if (step === "debut") {
      row.appendChild(bigButton(t("drill.start"), "", () => answer(q.id, "")));
      row.appendChild(bigButton(t("drill.skip"), "second", () => answer(q.id, "s")));
    } else if (step === "repere") {
      zone.appendChild(el("p", "attente", t("drill.observing")));
      row.appendChild(bigButton(t("drill." + id + ".mark"), "repere", () => {
        answer(q.id, "");                               // l'instant est noté d'abord…
        if (id === "station_stop") {                    // … puis la station est arrêtée (ne peut qu'arrêter)
          fetch("/api/station_stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
            .then(() => notice(t("drill.station_stopping")));
        }
      }));
    } else if (step === "fin") {
      zone.appendChild(el("p", "attente", t("drill.observing")));
      row.appendChild(bigButton(t("drill.end"), "", () => answer(q.id, "")));
    } else if (step === "avis") {
      zone.appendChild(el("p", "but", t("drill.verdict", { measure: t("measure." + measured) })));
      zone.appendChild(el("p", "", t("drill.expected") + " : " + t("drill." + id + ".expected", { tot: tot })));
      row.appendChild(bigButton(t("drill.yes"), "", () => answer(q.id, "o")));
      row.appendChild(bigButton(t("drill.no"), "second", () => answer(q.id, "n")));
      row.appendChild(bigButton(t("drill.dontknow"), "second", () => answer(q.id, "")));
    } else {                                            // remarque
      zone.appendChild(el("p", "but", t("drill.note")));
      const input = el("input");
      input.type = "text";
      const line = el("div", "ligne-saisie");
      line.appendChild(input);
      zone.appendChild(line);
      row.appendChild(bigButton(t("drill.note_send"), "", () => answer(q.id, input.value)));
      row.appendChild(bigButton(t("drill.note_none"), "second", () => answer(q.id, "")));
      setTimeout(() => input.focus(), 0);
    }
    zone.appendChild(row);
  }

  function renderQuestion() {
    const zone = $("zone");
    zone.replaceChildren();
    const others = [...open.values()].filter((q) => q.genre !== "mot" && q.role !== "menu");
    const q = others.length ? others[others.length - 1] : null;
    zone.hidden = !q;
    if (!q) return;
    if (q.role && q.role.startsWith("essai:")) {
      renderDrill(zone, q);
      return;
    }
    zone.appendChild(el("h2", "", t("question")));
    if (q.genre === "choix" && Array.isArray(q.choix)) renderChoice(zone, q);
    else if (q.genre === "oui_non") renderButtons(zone, q, [[t("yes"), "o"], [t("no"), "n"], [t("enter"), "", true]]);
    else if (q.genre === "fait") renderButtons(zone, q, [[t("done"), ""]]);
    else renderInput(zone, q, q.genre === "secret");
  }

  function render() {
    const words = [...open.values()].filter((q) => q.genre === "mot");
    showIntervention(words.length ? words[words.length - 1] : null);
    renderQuestion();
    renderTiles();
    showMeters();
    if (follow && current !== followed) {          // nouvelle tuile en cours : amenée à l'écran, en face du panneau
      followed = current;
      follow.scrollIntoView({ block: "center", behavior: "smooth" });
    }
    if (!current) followed = null;
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

  const ivInput = $("iv-mot");

  function ivError(text) {
    const e = $("iv-erreur");
    e.textContent = text;
    e.hidden = false;
    ivInput.focus();                               // l'opérateur retape tout de suite le mot
  }

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
      case "ligne": if (!e.menu) addLine(e.texte); break;
      case "statut": status(e); break;
      case "tuiles": tiles = e; break;
      case "question":
        open.set(e.id, e);
        if (e.role === "menu") {
          // La valise attend au menu : plus rien en cours, plus personne ne relit le poste. Jamais une vieille
          // valeur montrée comme actuelle (vu à l'essai : bandeau ÉMISSION resté après un STOP).
          current = null;
          chain = null;
          meters = { actif: false };
        }
        break;
      case "reponse": case "annule": open.delete(e.id); break;
      case "enchainement": current = e.cle; chain = { rang: e.rang, total: e.total }; break;
      case "mesure": if (e.nom === "poste" && e.valeur) meters = Object.assign({}, meters, e.valeur); break;
      case "fin": finished = true; meters = { actif: false }; break;
      case "stop": if (live) addLine("— STOP —"); break;
      case "avis": if (live) notice(e.texte, true); break;
      case "rapport": report = e.chemin; if (live) reportNotice(e.chemin); break;
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
    $("t-journal").textContent = t("journal");
    $("tout").textContent = t("run.all");
    $("echecs").textContent = t("run.failed");
    $("arret-seq").textContent = t("seq.stop");
    for (const k of ["freq", "po", "swr", "alc", "s"]) $("t-" + k).textContent = t("meter." + k);
    $("iv-titre").textContent = t("iv.title");
    $("iv-t-why").textContent = t("iv.why");
    $("iv-t-what").textContent = t("iv.what");
    $("iv-rule").textContent = t("iv.rule");
    $("iv-valider").textContent = t("iv.validate");
    $("iv-passer").textContent = t("iv.skip");
    stationButtons();
    legend();
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
        statusNow = {};
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
