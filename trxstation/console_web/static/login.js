// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// TRX Console sur le réseau (étape 233) : connexion d'un opérateur administrateur, puis la page des menus.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let ui = {};
  const text = (key, vars) => String(ui[key] || "").replace(/\{(\w+)\}/g, (_, k) => (vars && k in vars ? vars[k] : ""));

  fetch("/api/login", { credentials: "same-origin", cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data) return;
      ui = data.ui || {};
      document.documentElement.lang = data.lang || "fr";
      $("l-title").textContent = text("web.login.title");
      $("l-id").textContent = text("web.login.id");
      $("l-password").textContent = text("web.login.password");
      $("l-submit").textContent = text("web.login.submit");
      $("l-note").textContent = text("web.login.note");
    })
    .catch(() => {});

  $("login").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const error = $("l-error");
    error.hidden = true;
    $("l-submit").disabled = true;
    try {
      const r = await fetch("/api/login", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: $("id").value.trim(), password: $("password").value }) });
      if (r.ok) { location.replace("/"); return; }
      const data = await r.json().catch(() => ({}));
      error.textContent = r.status === 429 ? text("web.login.blocked", { minutes: data.blocked_min || 15 })
        : text("web.login.bad");
      error.hidden = false;
      $("password").value = "";
      $("password").focus();
    } catch (e) {
      error.textContent = String(e && e.message ? e.message : e);
      error.hidden = false;
    } finally {
      $("l-submit").disabled = false;
    }
  });
})();
