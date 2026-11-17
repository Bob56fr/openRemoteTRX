// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Menu ouvert en formulaires (étape 235) : la station joue le menu de TRX Console sans terminal et envoie ses
// messages ; la page les dessine (texte, boutons de choix, oui / non, nombre et bornes, mot de passe, mot de
// confirmation, sortie des commandes) et renvoie les réponses. Une réponse libre reste toujours possible.
"use strict";
(function () {
  const $ = (s) => document.querySelector(s);
  let ui = (k) => k, send = () => {}, inTerminal = () => {}, wantTerminal = false, flow = null, asking = null, sudo = null, running = null, outPre = null, lastAsked = null;
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
    lastAsked = asking;                                 // « answered » arrive après : la question y reste connue
    asking = null;
    send({ type: "flow_answer", value, label: label || "" });
    renderForm();
  }

  // Mise en forme des lignes (messages et sortie des commandes), d'après des signes communs aux quatre langues :
  // « === Titre === » titre, [OK] vert, [ATTENTION] ou « ! » orange, [ERREUR] rouge, « -> conseil » en retrait.
  const TONES = [[/^\s*={2,}.*={2,}\s*$/, "head"], [/^\s*\[(OK)\]/, "ok"],
    [/^\s*(!|\[(ATTENTION|WARNING|WARN|ACHTUNG|AVISO)\])/i, "warn"],
    [/^\s*\[(ERREUR|ERROR|FEHLER|ÉCHEC|FAIL)\]|^\s*(Erreur|Error|Fehler)\b/i, "bad"], [/^\s*->/, "hint"]];
  const toneOf = (line) => { const t = TONES.find(([re]) => re.test(line)); return t ? t[1] : ""; };
  function message(text) {
    const box = el("div", "msg");
    const lines = text.split("\n");
    lines.forEach((line, i) => {
      const tone = toneOf(line);
      box.append(tone ? el("span", "tone " + tone, line) : document.createTextNode(line));
      if (i < lines.length - 1) box.append(document.createTextNode("\n"));
    });
    return box;
  }

  // Sortie d'une commande, ligne par ligne : la question d'un outil (texte avant ce que l'opérateur a tapé) et sa
  // réponse sont mises en évidence ; la ligne en cours (question qui attend) reste visible.
  function newOut(parent) {
    const o = { box: el("div", "out"), buf: "", partial: el("div", "ln partial"), stick: true };
    o.box.append(o.partial);
    parent.append(o.box);
    // L'opérateur remonte : on ne bouge plus ; il redescend en bas : on suit de nouveau.
    o.box.addEventListener("scroll", () => {
      o.stick = o.box.scrollHeight - o.box.scrollTop - o.box.clientHeight < 24;
    });
    if (window.ResizeObserver) new ResizeObserver(() => bottom(o)).observe(o.box);
    return o;
  }
  function bottom(o) {
    if (!o.stick) return;
    o.box.scrollTop = o.box.scrollHeight;
    requestAnimationFrame(() => { if (o.stick) o.box.scrollTop = o.box.scrollHeight; });
  }
  function outLine(o, text) {
    const tone = toneOf(text);
    const line = el("div", "ln" + (tone ? " " + tone : "") + (text.trim() ? "" : " blank"), text);
    o.box.insertBefore(line, o.partial);
  }
  // Le cadre suit la fin de la sortie, sauf si l'opérateur est remonté pour relire (il reprend en bas).
  function follow(o, change) {
    change();
    bottom(o);
  }
  function outWrite(o, data) {
    follow(o, () => {
      const parts = (o.buf + data).split("\n");
      o.buf = parts.pop();
      for (const p of parts) outLine(o, p);
      o.partial.textContent = o.buf;
    });
  }
  function outTyped(o, data) {
    const qa = el("div", "ln qa");
    const question = o.buf.replace(/\s+$/, "");
    const m = question.match(/^([\s\S]*?)(\s*\[[^\]]*\])?(\s*:)?$/);
    qa.append(el("span", "q", m ? m[1] : question));
    if (m && m[2]) qa.append(el("span", "def", m[2].trim()));
    const value = data.replace(/\n$/, "");
    qa.append(el("span", "ans", value || "↵"));
    follow(o, () => o.box.insertBefore(qa, o.partial));
    o.buf = "";
    o.partial.textContent = "";
  }
  // Réponse à une question d'un outil posée en formulaire (étape 236) : même bloc qu'une réponse tapée.
  function outAnswer(o, q, value) {
    const qa = el("div", "ln qa");
    qa.append(el("span", "q", String(q.prompt || "").replace(/\s*:\s*$/, "")));
    qa.append(el("span", "ans", value || "↵"));
    follow(o, () => o.box.insertBefore(qa, o.partial));
  }
  function outEnd(o) {
    follow(o, () => {
      if (o.buf) outLine(o, o.buf);
      o.buf = "";
      o.partial.remove();
    });
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
      if (ev.tone === "bad" || ev.tone === "unchanged") box.classList.add(ev.tone);   // refus : bien visible
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
      const q = asking || lastAsked;
      lastAsked = null;
      if (q && q.tool && outPre) outAnswer(outPre, q, ev.value);    // question d'un outil : dans sa sortie, à sa place
      else if (ev.value) l.append(el("div", "me", ev.value));
      asking = null;
    } else if (ev.type === "run") {
      running = ev.cmd || "…";
      const box = el("div", "cmd");
      box.append(el("div", "cmd-name", ui("web.flow.running").replace("{cmd}", running)));
      if (ev.admin) box.firstChild.append(el("span", "admin", "🔒 sudo"));
      outPre = newOut(box);
      l.append(box);
    } else if (ev.type === "out") {
      if (!outPre) outPre = newOut(l);
      outWrite(outPre, String(ev.data || "").replace(/\r/g, ""));
    } else if (ev.type === "typed") {
      if (outPre) outTyped(outPre, String(ev.data || ""));
    } else if (ev.type === "end") {
      running = null;
      if (outPre) { outEnd(outPre); if (ev.code) outPre.box.classList.add("failed"); }
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
    $("#flow-stop").textContent = ui(flow && flow.done ? "web.flow.close" : "web.flow.stop");
    $("#flow-term").textContent = "⌨ " + ui("web.flow.terminal");
    const tool = flow && !sudo && !asking && running;
    if (tool && f.dataset.mode === "tool") { toolChoices(); return; }   // la ligne en cours de frappe reste
    f.replaceChildren();
    f.dataset.mode = tool ? "tool" : "";
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
      f.append(el("div", "choices tool"), input);
      toolChoices();
    }
  }
  // Un outil lancé par le menu (ex. Cluster DX) affiche « a) … b) … » puis attend : ses choix deviennent des boutons.
  const TOOL_CHOICE = /^\s{0,8}([0-9]{1,2}|[a-zA-Z])\)\s+(\S.*)$/;
  function toolChoices() {
    const box = $("#flow-form .choices.tool");
    if (!box) return;
    const found = [];
    if (outPre && outPre.buf.trim()) {                       // une question attend (ligne sans fin)
      let n = outPre.partial.previousElementSibling;
      while (n && n.classList.contains("blank")) n = n.previousElementSibling;
      while (n) {
        const m = TOOL_CHOICE.exec(n.textContent);
        if (!m) break;
        found.unshift([m[1], m[2].trim()]);
        n = n.previousElementSibling;
      }
    }
    const sig = JSON.stringify(found);
    if (box.dataset.sig === sig) return;
    box.dataset.sig = sig;
    box.replaceChildren();
    for (const [v, label] of found) {
      const b = button("", "choice", () => send({ type: "flow_stdin", data: v + "\n" }));
      b.append(el("span", "k", v), el("span", "", label));
      box.append(b);
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
      if (q.default) input.value = q.default;           // valeur actuelle proposée (Entrée = la garder)
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
    show();
    renderForm();
    scroll();
  }
  function event(ev) {
    if (!flow) return;
    add(ev);
    renderForm();
    scroll();
    if (!shown()) tab();                                // panneau masqué : l'onglet signale une question en attente
  }
  // Panneau masqué par un clic dans la page (le menu continue) ; l'onglet du bas le rouvre.
  function shown() { return $("#flow").classList.contains("show"); }
  function show() {
    if (!flow) return;
    $("#flow").classList.add("show");
    $("#flow-tab").hidden = true;
  }
  function tab() {
    const t = $("#flow-tab");
    t.hidden = !(flow && !flow.done);
    t.textContent = "▸ " + ui("web.flow.tab").replace("{key}", flow ? flow.key : "");
    t.classList.toggle("ask", !!(asking || sudo));
  }
  function hide() {
    if (!flow || !shown()) return;
    $("#flow").classList.remove("show");
    if (flow.done) flow = null;
    tab();
  }
  function close() {
    if (flow && !flow.done) { send({ type: "flow_stop" }); return; }
    flow = null;
    $("#flow").classList.remove("show");
    $("#flow-tab").hidden = true;
  }
  function busy() { return !!(flow && !flow.done); }
  window.TRXFlow = {
    init(uiFn, sendFn, terminalFn) {
      ui = uiFn; send = sendFn; inTerminal = terminalFn;
      $("#flow-stop").addEventListener("click", close);
      $("#flow-tab").addEventListener("click", show);
      $("#flow-term").addEventListener("click", () => {
        if (!flow) return;
        if (flow.done) { const key = flow.key; close(); inTerminal(key); return; }
        wantTerminal = true;
        send({ type: "flow_stop" });
      });
    },
    open, event, busy, hide, show, shown,
  };
})();
