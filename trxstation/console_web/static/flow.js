// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Menu ouvert en formulaires (étape 235) : la station joue le menu de TRX Console sans terminal et envoie ses
// messages ; la page les dessine (texte, boutons de choix, oui / non, nombre et bornes, mot de passe, mot de
// confirmation, sortie des commandes) et renvoie les réponses. Une réponse libre reste toujours possible.
"use strict";
(function () {
  const $ = (s) => document.querySelector(s);
  let ui = (k) => k, send = () => {}, inTerminal = () => {}, wantTerminal = false, flow = null, asking = null, sudo = null, running = null, outPre = null;
  const QR = /[█▀▄]{6}/;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function button(text, cls, onClick) {
    const b = el("button", "btn " + (cls || ""), text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function answer(value, label) {
    if (!asking) return;
    asking = null;
    send({ type: "flow_answer", value, label: label || "" });
    renderForm();
  }

  // Lignes du diagnostic et des bilans : [OK] vert, [ATTENTION] orange, [ERREUR] rouge, « == Titre == » en gras
  const TONES = [[/^\s*\[(OK)\]/, "ok"], [/^\s*\[(ATTENTION|WARNING|WARN|ACHTUNG|AVISO)\]/i, "warn"],
    [/^\s*\[(ERREUR|ERROR|FEHLER|ÉCHEC|FAIL)\]/i, "bad"], [/^\s*==.*==\s*$/, "head"]];
  function message(text) {
    const box = el("div", "msg");
    const lines = text.split("\n");
    lines.forEach((line, i) => {
      const tone = TONES.find(([re]) => re.test(line));
      box.append(tone ? el("span", "tone " + tone[1], line) : document.createTextNode(line));
      if (i < lines.length - 1) box.append(document.createTextNode("\n"));
    });
    return box;
  }

  // ---------------------------------------------------------------- journal du menu
  function log() { return $("#flow-log"); }
  function scroll() { const l = log(); l.scrollTop = l.scrollHeight; }
  function add(ev) {
    const l = log();
    if (ev.type === "say") {
      const text = String(ev.text || "").replace(/^\n+/, "");
      if (!text.trim()) return;
      const box = QR.test(text) ? el("pre", "qr", text) : message(text);
      box.dataset.id = ev.id;
      if (/ORT-\d{4}/.test(text)) box.classList.add("warn");
      l.append(box);
    } else if (ev.type === "form") {
      for (const id of ev.hide || []) { const m = l.querySelector('[data-id="' + id + '"]'); if (m) m.remove(); }
      for (const [id, text] of ev.rewrite || []) {
        const m = l.querySelector('[data-id="' + id + '"]');
        if (m) { if (text.trim()) m.textContent = text.replace(/^\n+/, ""); else m.remove(); }
      }
      if (ev.intro && ev.intro.trim()) l.append(el(QR.test(ev.intro) ? "pre" : "div", QR.test(ev.intro) ? "qr" : "msg", ev.intro.replace(/^\n+/, "")));
      asking = ev;
    } else if (ev.type === "answered") {
      asking = null;
      if (ev.value) l.append(el("div", "me", ev.value));
    } else if (ev.type === "run") {
      running = ev.cmd || "…";
      const box = el("div", "cmd");
      box.append(el("div", "cmd-name", ui("web.flow.running").replace("{cmd}", running)));
      outPre = el("pre", "out");
      box.append(outPre);
      l.append(box);
    } else if (ev.type === "out") {
      if (!outPre) { outPre = el("pre", "out"); l.append(outPre); }
      outPre.textContent += String(ev.data || "").replace(/\r/g, "");
    } else if (ev.type === "typed") {
      if (outPre) outPre.textContent += ev.data;
    } else if (ev.type === "end") {
      running = null;
      if (outPre && ev.code) outPre.classList.add("failed");
      outPre = null;
    } else if (ev.type === "done") {
      running = null; asking = null; sudo = null;
      flow.done = true;
      l.append(el("div", "done", ui("web.flow.done")));
      if (wantTerminal) {                               // « Ouvrir dans le terminal » : le même menu, au terminal
        wantTerminal = false;
        const key = flow.key;
        setTimeout(() => { close(); inTerminal(key); }, 0);
      }
    } else if (ev.type === "sudo") {
      sudo = { retry: ev.retry || 0 };
    } else if (ev.type === "sudo_bad" || ev.type === "sudo_sent") {
      sudo = null;
    }
  }

  // ---------------------------------------------------------------- question en cours
  function renderForm() {
    const f = $("#flow-form");
    f.replaceChildren();
    $("#flow-stop").textContent = ui(flow && flow.done ? "web.flow.close" : "web.flow.stop");
    $("#flow-term").textContent = "⌨ " + ui("web.flow.terminal");
    if (!flow) return;
    if (sudo) return sudoForm(f);
    if (asking) return questionForm(f, asking);
    if (running) {
      const input = el("input", "line");
      input.placeholder = ui("web.flow.input");
      input.autocomplete = "off";
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { send({ type: "flow_stdin", data: input.value + "\n" }); input.value = ""; }
      });
      f.append(input);
    }
  }
  function sudoForm(f) {
    const p = el("p", "prompt", ui("web.flow.sudo"));
    const input = el("input", "line");
    input.type = "password";
    input.autocomplete = "current-password";
    const go = () => { send({ type: "flow_password", value: input.value }); sudo = null; renderForm(); };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    f.append(p);
    if (sudo.retry) f.append(el("p", "bad", ui("web.flow.sudo_bad")));
    const row = el("div", "row");
    row.append(input, button(ui("web.flow.send"), "primary", go),
      button(ui("web.flow.cancel"), "", () => { send({ type: "flow_password", value: "" }); sudo = null; renderForm(); }));
    f.append(row);
    input.focus();
  }
  function questionForm(f, q) {
    const prompt = String(q.prompt || "").replace(/\s*:\s*$/, "");
    f.append(el("p", "prompt", prompt));
    const row = el("div", "row");
    let focus = null;
    const textField = (type) => {
      const input = el("input", "line");
      input.type = type || "text";
      input.autocomplete = type === "password" ? "new-password" : "off";
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") answer(input.value); });
      return input;
    };
    if (q.kind === "choice") {
      const grid = el("div", "choices");
      for (const [v, label] of q.choices || []) {
        const b = button("", "choice", () => answer(v, label));
        b.append(el("span", "k", v), el("span", "", label));
        grid.append(b);
      }
      f.append(grid);
    } else if (q.kind === "yesno") {
      row.append(button(ui("web.flow.yes"), q.default ? "primary" : "", () => answer("o", ui("web.flow.yes"))),
        button(ui("web.flow.no"), q.default === false ? "primary" : "", () => answer("n", ui("web.flow.no"))));
    } else if (q.kind === "int") {
      const input = textField("number");
      input.min = q.low; input.max = q.high; input.value = q.current;
      row.append(input, button(ui("web.flow.send"), "primary", () => answer(input.value)),
        button(ui("web.flow.keep").replace("{v}", q.current), "", () => answer("", String(q.current))));
      focus = input;
    } else if (q.kind === "password") {
      const input = textField("password");
      row.append(input, button(ui("web.flow.send"), "primary", () => answer(input.value)));
      if (q.generate) row.append(button(ui("web.flow.generate"), "", () => answer("")));
      if (q.abandon) row.append(button(ui("web.flow.cancel"), "", () => answer(q.abandon)));
      focus = input;
    } else if (q.kind === "word") {
      row.append(button(ui("web.flow.confirm").replace("{word}", q.word), "danger", () => answer(q.word)),
        button(ui("web.flow.cancel"), "", () => answer("")));
    } else if (q.kind === "pause") {
      const b = button(ui("web.flow.continue"), "primary", () => answer(""));
      row.append(b);
      focus = b;
    } else {
      const input = textField("text");
      row.append(input, button(ui("web.flow.send"), "primary", () => answer(input.value)));
      focus = input;
    }
    for (const [v, label] of q.extra || []) row.append(button(label, "", () => answer(v, label)));
    if (row.childElementCount) f.append(row);
    if (["choice", "yesno", "word"].includes(q.kind)) {
      const more = el("details", "free");
      more.append(el("summary", "", ui("web.flow.free")));
      const input = textField("text");
      const r2 = el("div", "row");
      r2.append(input, button(ui("web.flow.send"), "", () => answer(input.value)));
      more.append(r2);
      f.append(more);
    }
    if (focus) focus.focus();
  }

  // ---------------------------------------------------------------- panneau
  function open(summary) {
    flow = { key: summary.key, label: summary.label, done: !!summary.done };
    asking = sudo = running = outPre = null;
    $("#flow-key").textContent = summary.key;
    $("#flow-title").textContent = summary.label;
    log().replaceChildren();
    for (const ev of summary.events || []) add(ev);
    if (summary.done) flow.done = true;
    $("#flow").classList.add("show");
    renderForm();
    scroll();
  }
  function event(ev) {
    if (!flow) return;
    add(ev);
    renderForm();
    scroll();
  }
  function close() {
    if (flow && !flow.done) { send({ type: "flow_stop" }); return; }
    flow = null;
    $("#flow").classList.remove("show");
  }
  function busy() { return !!(flow && !flow.done); }
  window.TRXFlow = {
    init(uiFn, sendFn, terminalFn) {
      ui = uiFn; send = sendFn; inTerminal = terminalFn;
      $("#flow-stop").addEventListener("click", close);
      $("#flow-term").addEventListener("click", () => {
        if (!flow) return;
        if (flow.done) { const key = flow.key; close(); inTerminal(key); return; }
        wantTerminal = true;
        send({ type: "flow_stop" });
      });
    },
    open, event, busy,
  };
})();
