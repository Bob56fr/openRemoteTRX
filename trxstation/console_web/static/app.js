// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Console web de la station : état (relu toutes les 3 s), tuiles des thèmes, bulle d'aide (survol à la souris,
// premier toucher au doigt), terminal intégré relié à LA console texte de la session. « Ouvrir le menu » ouvre le
// menu EN FORMULAIRES (flow.js, étape 235) ; le tableau de bord et l'éditeur passent par le terminal, où le numéro
// n'est tapé que quand la console attend au menu (sinon il répondrait à une question en cours).
"use strict";
(function () {
  const $ = (s) => document.querySelector(s);
  const HOVER = matchMedia("(hover: hover) and (pointer: fine)").matches;
  let state = null, lang = null, level = null, pinned = null, term = null, fit = null, ws = null, toastTimer = null;
  const ui = (k, vars) => {
    let s = (state && state.ui && state.ui[k]) || k;
    for (const [a, b] of Object.entries(vars || {})) s = s.replace("{" + a + "}", b);
    return s;
  };
  // Drapeaux des langues (étape 241), dessinés en SVG : Windows n'affiche pas les drapeaux en emoji (« FR »).
  // Langue inconnue : son code en lettres.
  const FLAGS = {
    fr: [["rect", { width: 20, height: 40, fill: "#002395" }], ["rect", { x: 20, width: 20, height: 40, fill: "#fff" }],
      ["rect", { x: 40, width: 20, height: 40, fill: "#ED2939" }]],
    de: [["rect", { width: 60, height: 14, fill: "#000" }], ["rect", { y: 13, width: 60, height: 14, fill: "#DD0000" }],
      ["rect", { y: 26, width: 60, height: 14, fill: "#FFCE00" }]],
    es: [["rect", { width: 60, height: 40, fill: "#AA151B" }], ["rect", { y: 10, width: 60, height: 20, fill: "#F1BF00" }]],
    en: [["rect", { width: 60, height: 40, fill: "#012169" }],
      ["path", { d: "M0,0 L60,40 M60,0 L0,40", stroke: "#fff", "stroke-width": 8 }],
      ["path", { d: "M0,0 L60,40 M60,0 L0,40", stroke: "#C8102E", "stroke-width": 3 }],
      ["path", { d: "M30,0 V40 M0,20 H60", stroke: "#fff", "stroke-width": 13 }],
      ["path", { d: "M30,0 V40 M0,20 H60", stroke: "#C8102E", "stroke-width": 8 }]],
  };
  function flag(code) {
    const shapes = FLAGS[code];
    if (!shapes) return document.createTextNode(code.toUpperCase());
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 60 40");
    svg.setAttribute("aria-hidden", "true");
    for (const [tag, attrs] of shapes) {
      const s = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, String(v));
      svg.append(s);
    }
    return svg;
  }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ---------------------------------------------------------------- état
  async function refresh() {
    try {
      const r = await fetch("/api/state", { credentials: "same-origin", cache: "no-store" });
      if (r.status === 403) { location.reload(); return; }              // session fermée (réseau) : page de connexion
      if (!r.ok) return;
      state = await r.json();
    } catch (e) { return; }
    header();
    if (state.lang !== lang || state.level !== level) {
      lang = state.lang; level = state.level; document.documentElement.lang = lang; texts(); tiles();
    }
    $("#term-state").textContent = state.idle ? "" : "…";
  }
  function header() {
    $("#title").textContent = ui("web.title");
    $("#sub").textContent = ui("web.version", { version: state.version });
    const pills = $("#pills");
    pills.replaceChildren();
    const pill = (cls, text) => { const p = el("span", "pill " + cls); p.append(el("span", "dot"), document.createTextNode(text)); pills.append(p); };
    if (!state.configured) pill("warn", ui("web.not_configured"));
    else pill(state.running ? "on" : "off", ui(state.running ? "web.running" : "web.stopped"));
    if (state.running) pill(state.ptt !== "RX" ? "tx" : "", ui(state.ptt !== "RX" ? "web.tx" : "web.rx"));
    if (state.update) {                                   // nouvelle version publiée : un clic ouvre la mise à jour
      pill("warn update", ui("web.update", { version: state.update }));
      const p = pills.lastChild;
      p.setAttribute("role", "button");
      p.tabIndex = 0;
      p.title = ui("web.update_open", { menu: state.update_menu });
      const go = () => openMenu(state.update_menu);
      p.addEventListener("click", go);
      p.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    }
    const rig = state.rig || {};
    $("#freq").textContent = rig.frequency_hz ? fmtFreq(rig.frequency_hz) : "--.---.--";
    const meta = [];
    if (rig.connected) {
      if (rig.mode) meta.push(rig.mode);
      if (typeof rig.strength_db === "number") meta.push(sText(rig.strength_db));
      if (typeof rig.vd === "number") meta.push(rig.vd.toFixed(1).replace(".", ",") + " V");
    } else meta.push(ui("web.no_rig"));
    $("#meta").textContent = meta.join(" · ");
    const first = $("#first");
    first.hidden = state.configured;
    first.textContent = ui("web.first_use", { menu: state.assistant });
  }
  function fmtFreq(hz) {
    const s = String(Math.round(hz / 10)).padStart(6, "0");      // 14 205 000 Hz -> 14.205.00
    return s.slice(0, -5) + "." + s.slice(-5, -2) + "." + s.slice(-2);
  }
  function sText(db) { return db >= 0 ? (db === 0 ? "S9" : "S9+" + db) : "S" + Math.max(0, Math.round(9 + db / 6)); }
  function texts() {
    $("#q").placeholder = ui("web.search");
    $("#all").textContent = ui("web.expand");
    $("#none").textContent = ui("web.collapse");
    const langs = $("#langs");
    langs.replaceChildren();
    langs.setAttribute("aria-label", ui("web.language"));
    for (const [code, name] of state.langs || []) {
      const b = el("button", "seg flag" + (code === state.lang ? " on" : ""));
      b.append(flag(code));
      b.setAttribute("aria-label", name);
      b.type = "button";
      b.dataset.lang = code;
      b.title = name;
      langs.append(b);
    }
    const levels = $("#levels");
    levels.replaceChildren();
    levels.setAttribute("aria-label", ui("web.level"));
    for (const lv of ["basic", "normal", "expert"]) {
      const b = el("button", "seg" + (lv === state.level ? " on" : ""), ui("level." + lv));
      b.type = "button";
      b.dataset.level = lv;
      b.title = ui("level." + lv + ".desc");
      levels.append(b);
    }
    $("#logout").textContent = ui("web.logout");
    $("#logout").hidden = !state.network;
    $("#term-label").textContent = ui("web.terminal");
    $("#term-toggle").textContent = ui("web.hide");
    $("#term-max").textContent = ui("web.max");
    $("#term-tab").textContent = "▸ " + ui("web.show");
  }

  // ---------------------------------------------------------------- tuiles
  function tiles() {
    const grid = $("#grid");
    grid.replaceChildren();
    state.themes.forEach((th, i) => {
      const card = el("article", "card");
      card.dataset.t = th.number;
      card.style.setProperty("--c", th.color);
      card.style.animationDelay = i * 45 + "ms";
      const head = el("header");
      head.dataset.toggle = th.number;
      const titles = el("div");
      titles.append(el("div", "num", th.number), el("h2", "", th.title));
      const shown = th.items.filter((it) => it.visible).length;
      card.dataset.shown = String(shown);
      head.append(el("span", "ico", th.icon), titles, el("span", "count", shown ? String(shown) : ""));
      head.title = th.summary;
      const list = el("ul", "items");
      for (const it of th.items) {
        const li = el("li"), b = el("button");
        b.type = "button";
        b.dataset.k = it.key;
        b.append(el("span", "k", it.key), document.createTextNode(it.short));
        if (!it.visible) { li.classList.add("other"); b.append(el("span", "lvl", ui("level." + it.level))); }
        li.append(b);
        list.append(li);
      }
      card.append(head, list);
      grid.append(card);
    });
    filter();
  }
  function find(key) {
    for (const th of state.themes) for (const it of th.items) if (it.key === key) return [th, it];
    return [null, null];
  }

  // ---------------------------------------------------------------- bulle d'aide
  function showHelp(key, anchor, pin) {
    const [th, it] = find(key);
    if (!it || !anchor) return;
    const pop = $("#help");
    pop.replaceChildren(el("span", "eyebrow", th.icon + " " + th.title + " · " + it.key), el("h3", "", it.label));
    for (const [k, v] of [["web.role", it.role], ["web.when", it.when], ["web.changes", it.changes]]) {
      if (v) pop.append(el("span", "lbl", ui(k)), el("p", "", v));
    }
    if (it.admin) pop.append(el("span", "tag", ui("web.admin")));
    if (pin) {
      const b = el("button", "btn open", ui("web.open") + " " + it.key + " ▸");
      b.type = "button";
      b.addEventListener("click", () => openMenu(it.key));
      pop.append(b);
    } else pop.append(el("span", "hint", ui(HOVER ? "web.click_open" : "web.tap_open")));
    pop.classList.toggle("pinned", !!pin);
    pop.classList.add("on");
    if (innerWidth <= 700) return;                                  // téléphone : panneau du bas (CSS)
    const r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight, gap = 12;
    const right = r.right + gap + w <= innerWidth - 8;
    pop.style.left = (right ? r.right + gap : Math.max(8, r.left - gap - w)) + "px";
    pop.style.top = Math.min(Math.max(8, r.top + r.height / 2 - 28), innerHeight - h - 8) + "px";
  }
  function hideHelp(force) {
    if (force) pinned = null;
    if (!pinned) $("#help").classList.remove("on", "pinned");
  }

  // ---------------------------------------------------------------- ouvrir un menu
  async function openMenu(key, inTerminal) {
    hideHelp(true);
    const item = state && state.themes.flatMap((th) => th.items).find((it) => it.key === key);
    if (item && item.mode === "dashboard" && !inTerminal) {    // 1.3 : tableau de bord dessiné par la page
      window.TRXDash.open(key + "  " + item.label);
      return;
    }
    if (window.TRXFlow.busy()) { window.TRXFlow.show(); toast(ui("web.flow.busy")); return; }
    let answer = null;
    try {
      const r = await fetch("/api/open", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, terminal: !!inTerminal }) });
      answer = await r.json().catch(() => null);
      if (r.status === 409) { toast(ui(answer && answer.busy === "flow" ? "web.flow.busy" : "web.busy")); showTerm(answer && answer.busy !== "flow"); return; }
    } catch (e) { return; }
    if (answer && answer.mode === "terminal") {
      $("#term").classList.toggle("max", !!answer.full);
      showTerm(true);
      if (term) term.focus();
    }
  }
  function toast(text) {
    const t = $("#toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
  }

  // ---------------------------------------------------------------- terminal intégré
  function showTerm(on) {
    $("#term").classList.toggle("show", on);
    $("#term-tab").hidden = on;
    if (!on) $("#term").classList.remove("max");
    if (on && fit) setTimeout(() => { fit.fit(); sendSize(); }, 320);
  }
  function sendSize() {
    if (ws && ws.readyState === 1 && term) ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
  }
  function connect() {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.onopen = () => { term.reset(); sendSize(); };
    ws.onmessage = (ev) => {
      let m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "output") term.write(m.data);
      if (m.type === "flow_start") window.TRXFlow.open(m.flow);
      if (m.type === "flow") window.TRXFlow.event(m.event);
      if (m.type === "expired") location.reload();                 // session fermée : retour à la connexion
    };
    ws.onclose = () => setTimeout(connect, 2000);
  }
  function startTerm() {
    term = new Terminal({ fontFamily: getComputedStyle(document.body).getPropertyValue("--f-mono") || "monospace",
      fontSize: 14, cursorBlink: true, convertEol: false, scrollback: 5000,
      theme: { background: "#0b1115", foreground: "#cfe6df", cursor: "#53f3d8" } });
    fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open($("#term-body"));
    term.onData((d) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "input", data: d })); });
    addEventListener("resize", () => { if ($("#term").classList.contains("show")) { fit.fit(); sendSize(); } });
    showTerm(false);                                              // replié au départ : l'onglet « Terminal » reste
    connect();
  }

  // ---------------------------------------------------------------- recherche, boutons, souris
  function filter() {
    const q = $("#q").value.trim().toLowerCase();
    for (const card of document.querySelectorAll(".card")) {
      const th = state.themes.find((x) => x.number === card.dataset.t);
      let any = false;
      card.querySelectorAll(".items li").forEach((li, k) => {
        const it = th.items[k];
        // sans recherche : les menus du niveau choisi ; une recherche trouve TOUS les menus (les autres grisés)
        const hit = q ? [it.label, it.role, it.when, th.title].join(" ").toLowerCase().includes(q) : it.visible;
        li.hidden = !hit;
        any = any || hit;
      });
      card.hidden = !any;
      if (q) card.classList.remove("closed");
    }
  }
  $("#q").addEventListener("input", filter);
  $("#all").addEventListener("click", () => document.querySelectorAll(".card").forEach((c) => c.classList.remove("closed")));
  $("#none").addEventListener("click", () => document.querySelectorAll(".card").forEach((c) => c.classList.add("closed")));
  $("#langs").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-lang]");
    if (!b || b.dataset.lang === state.lang) return;
    try {
      await fetch("/api/lang", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lang: b.dataset.lang }) });
    } catch (err) { return; }
    refresh();
  });
  $("#levels").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-level]");
    if (!b || b.dataset.level === state.level) return;
    try {
      await fetch("/api/level", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ level: b.dataset.level }) });
    } catch (err) { return; }
    refresh();
  });
  $("#logout").addEventListener("click", async () => {
    try { await fetch("/api/logout", { method: "POST", credentials: "same-origin" }); } catch (e) { /* page rechargée */ }
    location.reload();
  });
  $("#term-toggle").addEventListener("click", () => showTerm(false));
  $("#term-max").addEventListener("click", () => {
    $("#term").classList.toggle("max");
    if (fit) setTimeout(() => { fit.fit(); sendSize(); }, 320);
    if (term) term.focus();
  });
  window.TRXFlow.init(ui, (m) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); },
    (key) => openMenu(key, true));
  window.TRXDash.init(ui, () => {
    const item = state && state.themes.flatMap((th) => th.items).find((it) => it.mode === "dashboard");
    if (item) openMenu(item.key, true);
  });
  $("#term-tab").addEventListener("click", () => { showTerm(true); if (term) term.focus(); });
  document.addEventListener("click", (e) => {
    // clic dans la page, hors du panneau du menu : le panneau se range (le menu continue, onglet en bas à droite)
    // Chemin du clic mémorisé AU MOMENT du clic : un bouton du panneau remplacé par la question suivante n'est plus
    // dans la page quand le clic arrive ici (e.target.closest le croirait dehors et rangerait le panneau).
    const path = e.composedPath ? e.composedPath() : [];
    const inside = (id) => path.some((n) => n && n.id === id) || !!e.target.closest("#" + id);
    if (window.TRXFlow.shown() && !inside("flow") && !inside("flow-tab")) window.TRXFlow.hide();
    const b = e.target.closest(".items button");
    if (b) {
      if (HOVER || pinned === b.dataset.k) openMenu(b.dataset.k);
      else {
        pinned = b.dataset.k;
        document.querySelectorAll(".items button").forEach((x) => x.classList.toggle("sel", x === b));
        showHelp(pinned, b, true);
      }
      return;
    }
    if (e.target.closest("#help") || e.target.closest("#term") || e.target.closest("#term-tab")
        || inside("flow")) return;
    const h = e.target.closest("[data-toggle]");
    if (h) h.closest(".card").classList.toggle("closed");
    hideHelp(true);
  });
  document.addEventListener("mouseover", (e) => {
    const b = e.target.closest(".items button");
    if (b && !pinned) showHelp(b.dataset.k, b, false);
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest(".items button") && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest(".items button"))) hideHelp(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (window.TRXDash.shown()) { window.TRXDash.close(); return; }
    if (window.TRXFlow.shown()) window.TRXFlow.hide();
    hideHelp(true);
  });
  addEventListener("scroll", () => hideHelp(false), { passive: true });

  // ---------------------------------------------------------------- fond du bandeau : waterfall discret
  (function waterfall() {
    const cv = $("#wf"), ctx = cv.getContext("2d");
    let w = 1, h = 1, row = 0;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const peaks = [0.18, 0.33, 0.52, 0.71, 0.86];
    function draw() {
      ctx.drawImage(cv, 0, 0, w, h - 1, 0, 1, w, h - 1);
      for (let x = 0; x < w; x += 2) {
        let v = Math.random() * 0.18;
        for (const p of peaks) { const d = Math.abs(x / w - p) * 90; v += Math.exp(-d * d) * (0.55 + 0.45 * Math.sin(row / 9 + p * 20)); }
        v = Math.min(1, v);
        ctx.fillStyle = "hsl(" + (190 - v * 120) + " 90% " + (8 + v * 45) + "%)";
        ctx.fillRect(x, 0, 2, 1);
      }
      row++;
    }
    function size() {
      w = cv.width = Math.max(1, cv.clientWidth); h = cv.height = Math.max(1, cv.clientHeight);
      ctx.fillStyle = "#050b0e"; ctx.fillRect(0, 0, w, h);
      for (let i = 0; i < h; i++) draw();
    }
    new ResizeObserver(size).observe(cv.parentElement);
    function loop() { draw(); requestAnimationFrame(loop); }
    if (!reduce) requestAnimationFrame(loop);
  })();

  refresh().then(() => { startTerm(); });
  setInterval(refresh, 3000);
})();
