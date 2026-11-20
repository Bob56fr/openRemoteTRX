// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Diffusion en direct dans la page (docs/diffusion-cahier-des-charges.md, lot D2 ; protocole : docs/protocole.md § 20) :
   calculs purs, testés sous Node (tests/js/diffusion_test.js), sans DOM. Le dessin est dans ui.js (indicateur
   « DIFFUSION » de l'en-tête, rubrique « Diffusion en direct »). L'état vient de state.diffusion (opérateurs) ; le   // i18n-ok (commentaire)
   module « diffusion » n'agit jamais sur le poste. */
(function (root) {
  "use strict";   // i18n-ok

  const I18N = root.TrxI18n || (typeof require === "function" ? require("./i18n.js") : null);

  // Cahier § 1.1 : à confirmer une fois, au premier lancement (la station s'en souvient).
  function warning() { return I18N.t("diffusion.warning"); }
  const HOURS = [1, 2, 3, 4, 6, 8, 12, 24, null];       // null : sans limite (24 h/24, choix explicite)
  const DEFAULT_HOURS = 1;
  // Ordre et libellés de la liste proposée à l'opérateur (cahier § 7, protocol.CHOICE_FIELDS) ; TOUT coché par
  // défaut, comme le POC (décision de l'utilisateur du 2026-11-18, étape 248). Textes relus à l'affichage.
  const META_KEYS = ["pseudo", "indicatif", "frequence_hz", "mode", "bande", "tx", "s_metre", "filtre", "voyants", "message"];
  function meta() { return META_KEYS.map((key) => [key, I18N.t("diffusion.meta_" + key)]); }
  const DEFAULT_META = META_KEYS.slice();
  const LIMITS = { pseudo: 32, indicatif: 16, message: 140 };
  const STOP_KEYS = ["operator", "duration", "overload", "gateway_restart", "auth", "disabled", "station_stop"];
  const PHASE_KEYS = ["connexion", "en_direct", "nouvel_essai"];
  function table(keys, prefix) { const out = {}; for (const k of keys) out[k] = I18N.t(prefix + k); return out; }
  function stops() { return table(STOP_KEYS, "diffusion.stop_"); }
  function phases() { return table(PHASE_KEYS, "diffusion.phase_"); }

  function remaining(s) {
    if (s === null || s === undefined) return I18N.t("diffusion.no_limit");
    const m = Math.max(0, Math.round(s / 60));
    if (m < 60) return m + " min";
    return Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0");
  }

  function hoursLabel(h) { return h === null ? I18N.t("diffusion.hours_no_limit") : h + " h"; }

  /* Raison d'un silence voulu (la station la dit aussi aux auditeurs, docs/protocole-diffusion.md § 3.1). */
  const SILENCE_KEYS = ["hors_bandes", "emission", "pas_de_son", "poste_eteint"];
  function silences() { return table(SILENCE_KEYS, "diffusion.silence_"); }
  function access(a) { return I18N.t(a === "public" ? "diffusion.access_public" : "diffusion.access_private"); }

  /* Indicateur de l'en-tête : toujours visible pendant une diffusion (cahier § 8). null hors diffusion. */
  function indicator(d) {
    if (!d || d.active !== true) return null;
    const n = typeof d.listeners === "number" ? d.listeners : null;
    const live = d.phase === "en_direct";
    const parts = [I18N.t("diffusion.indicator")];
    if (n !== null) parts.push("🎧 " + n);
    parts.push(remaining(d.remaining_s));
    const silence = silences()[d.silence];
    if (silence) parts.push("🔇");
    const title = I18N.t("diffusion.title", {
      access: access(d.access), phase: phases()[d.phase] || d.phase || "",
      listeners: n !== null ? I18N.plural("diffusion.title_listeners", n) : "", remaining: remaining(d.remaining_s),
      silence: silence ? I18N.t("diffusion.title_silence", { silence: silence }) : "",
    });
    return {
      text: parts.join(" · "),
      level: live ? "live" : "retry",
      title: I18N.t("diffusion.title_touch", { title: title }),
    };
  }

  /* Texte d'état de la rubrique. */
  function status(d) {
    if (!d) return I18N.t("diffusion.status_unavailable");
    if (d.enabled === false) return I18N.t("diffusion.status_disabled");
    if (d.problem) return I18N.t("diffusion.status_problem", { problem: d.problem });
    if (d.active) {
      const silence = silences()[d.silence];
      return I18N.t("diffusion.status_active", {
        who: d.operator ? I18N.t("diffusion.status_by", { operator: d.operator }) : "",
        access: access(d.access), phase: phases()[d.phase] || d.phase, remaining: remaining(d.remaining_s),
        voice: I18N.t(d.voice ? "diffusion.status_voice_on" : "diffusion.status_voice_off"),
        bands: I18N.t(d.outside_bands ? "diffusion.status_bands_on" : "diffusion.status_bands_off"),
        silence: silence ? I18N.t("diffusion.status_silence", { silence: silence }) : "",
      });
    }
    const stop = d.last_stop && stops()[d.last_stop.cause];
    return I18N.t("diffusion.status_idle", { last: stop ? I18N.t("diffusion.status_last", { stop: stop }) : "" });
  }

  /* Contrôle du formulaire avant envoi (la station vérifie de nouveau tout). */
  function startArgs(form) {
    const f = form || {};
    const access = f.access === "public" ? "public" : "prive";
    const hours = f.hours === null || f.hours === "none" ? null : Number(f.hours || DEFAULT_HOURS);
    if (hours !== null && !(Number.isInteger(hours) && hours >= 1 && hours <= 24)) return { error: I18N.t("diffusion.form_hours") };
    const meta = (Array.isArray(f.meta) ? f.meta : DEFAULT_META).filter((k) => META_KEYS.includes(k));
    const args = { access: access, hours: hours, voice: f.voice === true, meta: meta };
    for (const k of Object.keys(LIMITS)) {
      const v = typeof f[k] === "string" ? f[k].trim() : "";
      const label = I18N.t("diffusion.meta_" + k);
      if (v.length > LIMITS[k]) return { error: I18N.t("diffusion.form_too_long", { label: label, limit: LIMITS[k] }) };
      // eslint-disable-next-line no-control-regex
      if (/[\u0000-\u001f\u007f-\u009f]/.test(v)) return { error: I18N.t("diffusion.form_invalid", { label: label }) };
      if (v) args[k] = v;
    }
    return { args: args };
  }

  function passwordOk(pw) { return typeof pw === "string" && /^[A-Za-z0-9]{8,64}$/.test(pw); }

  const api = { get WARNING() { return warning(); }, HOURS, DEFAULT_HOURS, get META() { return meta(); }, DEFAULT_META,
                LIMITS, get STOPS() { return stops(); }, get PHASES() { return phases(); }, remaining, hoursLabel,
                indicator, status, startArgs, passwordOk };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxDiffusion = api; }
})(typeof window !== "undefined" ? window : globalThis);
