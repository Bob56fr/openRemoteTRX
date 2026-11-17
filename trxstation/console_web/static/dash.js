// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Tableau de bord dans la page (menu 1.3, étape 238) : les mêmes panneaux et le même journal que trx-monitor,
// calculés par la station (`/api/dashboard`, lecture seule) et dessinés ici. Une seule action : STOP TX, qui ne
// peut que COUPER une émission (« T 0 » direct à rigctld, `/api/stop_tx`).
"use strict";
(function () {
  const $ = (s) => document.querySelector(s);
  const TX = ["KEYING", "TX", "UNKEYING"];
  const POLL_MS = 700;
  let ui = (k) => k, toTerminal = () => {}, timer = null, net = false, busy = false, flashTimer = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function panel(p) {
    const card = el("section", "dcard dcard-" + p.key);
    card.append(el("h3", "", p.title));
    const rows = el("dl", "drows");
    for (const [label, text, level] of p.rows || []) {
      rows.append(el("dt", "", label), el("dd", "lv-" + (level || "info"), text));
    }
    card.append(rows);
    return card;
  }

  function render(data) {
    const body = $("#dash-grid");
    $("#dash-stale").hidden = !data.ok || !!data.fresh;
    if (!data.ok) {
      body.replaceChildren(el("p", "dash-error", data.error || "?"));
      return;
    }
    body.replaceChildren(...(data.panels || []).map(panel));
    const log = $("#dash-log-lines");
    log.replaceChildren(...(data.log || []).slice().reverse().map((line) => el("li", /STOP TX|FIGÉE|INJOIGNABLE|DÉFAUT|MODE SÛR|PROFIL VPN/.test(line) ? "hot" : "", line)));
    const tx = TX.includes(data.ptt);
    $("#dash-stop").classList.toggle("live", tx);          // émission en cours : STOP bien visible
    $("#dash").classList.toggle("tx", tx);
  }

  async function poll() {
    if (busy) return;
    busy = true;
    try {
      const r = await fetch("/api/dashboard" + (net ? "?net=1" : ""), { credentials: "same-origin" });
      if (r.status === 403) { location.reload(); return; }   // session fermée : retour à la connexion
      render(await r.json());
    } catch (e) {
      /* station injoignable un instant : on garde le dernier affichage */
    } finally {
      busy = false;
    }
  }

  function flash(text, ok) {
    const f = $("#dash-flash");
    f.textContent = text;
    f.className = "dash-flash " + (ok ? "ok" : "bad");
    f.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { f.hidden = true; }, 8000);
  }

  async function stopTx() {
    const b = $("#dash-stop");
    b.disabled = true;
    try {
      const r = await fetch("/api/stop_tx", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: "{}" });
      const answer = await r.json().catch(() => ({ ok: false, message: "?" }));
      flash(answer.message || "?", !!answer.ok);
    } catch (e) {
      flash("STOP TX : station injoignable", false);
    } finally {
      b.disabled = false;
      poll();
    }
  }

  function open(label) {
    $("#dash-title").textContent = label || "";
    $("#dash-stop").textContent = "■ " + ui("web.dash.stop");
    $("#dash-net").textContent = ui("web.dash.net");
    $("#dash-term").textContent = "⌨ " + ui("web.flow.terminal");
    $("#dash-close").textContent = ui("web.dash.close");
    $("#dash-stale").textContent = ui("web.dash.stale");
    $("#dash-log-title").textContent = ui("web.dash.log");
    $("#dash").hidden = false;
    document.body.classList.add("dash-open");
    poll();
    clearInterval(timer);
    timer = setInterval(poll, POLL_MS);
  }
  function close() {
    clearInterval(timer);
    timer = null;
    $("#dash").hidden = true;
    document.body.classList.remove("dash-open");
  }
  function shown() { return !$("#dash").hidden; }

  window.TRXDash = {
    init(uiFn, terminalFn) {
      ui = uiFn;
      toTerminal = terminalFn;
      $("#dash-stop").addEventListener("click", stopTx);
      $("#dash-net").addEventListener("click", () => {
        net = !net;
        $("#dash-net").classList.toggle("on", net);
        poll();
      });
      $("#dash-term").addEventListener("click", () => { close(); toTerminal(); });
      $("#dash-close").addEventListener("click", close);
    },
    open, close, shown,
  };
})();
