// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Diffusion en direct dans la page (docs/diffusion-cahier-des-charges.md, lot D2 ; protocole : docs/protocole.md § 20) :
   calculs purs, testés sous Node (tests/js/diffusion_test.js), sans DOM. Le dessin est dans ui.js (indicateur
   « DIFFUSION » de l'en-tête, rubrique « Diffusion en direct »). L'état vient de state.diffusion (opérateurs) ; le
   module « diffusion » n'agit jamais sur le poste. */
(function (root) {
  "use strict";

  // Cahier § 1.1 : à confirmer une fois, au premier lancement (la station s'en souvient).
  const WARNING = "Vous allez rediffuser le son de votre TRX sur Internet, vers des auditeurs sans compte sur la " +
    "station. Des milliers de SDR en ligne le font déjà, mais ce que vous diffusez est de VOTRE responsabilité. Hors " +
    "des bandes autorisées de la station, les auditeurs n'entendent rien, sauf si le réglage « Diffuser aussi hors " +
    "des bandes autorisées » est en service. Pendant vos émissions, votre voix n'est diffusée que si vous cochez " +
    "« Diffuser aussi ma voix ». Continuer ?";
  const HOURS = [1, 2, 3, 4, 6, 8, 12, 24, null];       // null : sans limite (24 h/24, choix explicite)
  const DEFAULT_HOURS = 1;
  // Ordre et libellés de la liste proposée à l'opérateur (cahier § 7, protocol.CHOICE_FIELDS) ; TOUT coché par
  // défaut, comme le POC (décision de l'utilisateur du 2026-11-18, étape 248).
  const META = [
    ["pseudo", "Pseudo"], ["indicatif", "Indicatif"], ["frequence_hz", "Fréquence"], ["mode", "Mode"],
    ["bande", "Bande"], ["tx", "Réception / émission"], ["s_metre", "S-mètre"], ["filtre", "Filtre"],
    ["voyants", "Voyants (P.AMP, ATT, NB, NR…)"], ["message", "Message"],
  ];
  const DEFAULT_META = META.map(([key]) => key);
  const LIMITS = { pseudo: 32, indicatif: 16, message: 140 };
  const STOPS = {
    operator: "arrêtée par un opérateur", duration: "fin de la durée choisie", overload: "station surchargée",
    gateway_restart: "passerelle relancée", auth: "mot de passe source refusé par le serveur",
    disabled: "fonction mise hors service", station_stop: "arrêt de la station",
  };
  const PHASES = { connexion: "connexion au serveur…", en_direct: "en direct", nouvel_essai: "liaison perdue, nouvel essai…" };

  function remaining(s) {
    if (s === null || s === undefined) return "sans limite";
    const m = Math.max(0, Math.round(s / 60));
    if (m < 60) return m + " min";
    return Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0");
  }

  function hoursLabel(h) { return h === null ? "Sans limite (24 h/24)" : h + " h"; }

  /* Raison d'un silence voulu (la station la dit aussi aux auditeurs, docs/protocole-diffusion.md § 3.1). */
  const SILENCES = {
    hors_bandes: "réception hors des bandes autorisées",
    emission: "émission en cours, voix non diffusée",
    pas_de_son: "le son du poste n'arrive plus",
  };

  /* Indicateur de l'en-tête : toujours visible pendant une diffusion (cahier § 8). null hors diffusion. */
  function indicator(d) {
    if (!d || d.active !== true) return null;
    const n = typeof d.listeners === "number" ? d.listeners : null;
    const live = d.phase === "en_direct";
    const parts = ["DIFFUSION"];
    if (n !== null) parts.push("🎧 " + n);
    parts.push(remaining(d.remaining_s));
    if (SILENCES[d.silence]) parts.push("🔇");
    return {
      text: parts.join(" · "),
      level: live ? "live" : "retry",
      title: "Diffusion en direct (" + (d.access === "public" ? "publique" : "privée") + ", " +
             (PHASES[d.phase] || d.phase || "") + (n !== null ? ", " + n + " auditeur" + (n > 1 ? "s" : "") : "") +
             ", reste " + remaining(d.remaining_s) + ")" +
             (SILENCES[d.silence] ? ". Silence pour les auditeurs : " + SILENCES[d.silence] : "") +
             ". Touche : sa rubrique",
    };
  }

  /* Texte d'état de la rubrique. */
  function status(d) {
    if (!d) return "Diffusion indisponible sur cette station.";
    if (d.enabled === false) return "Diffusion hors service ([diffusion] de station.toml, menu 8.1).";
    if (d.problem) return "Diffusion impossible : " + d.problem + ".";
    if (d.active) {
      const who = d.operator ? " par " + d.operator : "";
      return "En cours" + who + " : " + (d.access === "public" ? "publique" : "privée") + ", " +
             (PHASES[d.phase] || d.phase) + ", reste " + remaining(d.remaining_s) +
             (d.voice ? ", voix émise diffusée" : ", voix émise NON diffusée") +
             (d.outside_bands ? ", hors bandes diffusé" : ", silence hors des bandes autorisées") + "." +
             (SILENCES[d.silence] ? " En ce moment, SILENCE pour les auditeurs : " + SILENCES[d.silence] + "." : "");
    }
    const last = d.last_stop && STOPS[d.last_stop.cause] ? " Dernière : " + STOPS[d.last_stop.cause] + "." : "";
    return "Aucune diffusion en cours." + last;
  }

  /* Contrôle du formulaire avant envoi (la station vérifie de nouveau tout). */
  function startArgs(form) {
    const f = form || {};
    const access = f.access === "public" ? "public" : "prive";
    const hours = f.hours === null || f.hours === "none" ? null : Number(f.hours || DEFAULT_HOURS);
    if (hours !== null && !(Number.isInteger(hours) && hours >= 1 && hours <= 24)) return { error: "Durée : 1 à 24 h, ou sans limite." };
    const meta = (Array.isArray(f.meta) ? f.meta : DEFAULT_META).filter((k) => META.some(([key]) => key === k));
    const args = { access: access, hours: hours, voice: f.voice === true, meta: meta };
    for (const k of Object.keys(LIMITS)) {
      const v = typeof f[k] === "string" ? f[k].trim() : "";
      if (v.length > LIMITS[k]) return { error: META.find(([key]) => key === k)[1] + " : " + LIMITS[k] + " caractères au plus." };
      // eslint-disable-next-line no-control-regex
      if (/[\u0000-\u001f\u007f-\u009f]/.test(v)) return { error: META.find(([key]) => key === k)[1] + " : caractère invalide." };
      if (v) args[k] = v;
    }
    return { args: args };
  }

  function passwordOk(pw) { return typeof pw === "string" && /^[A-Za-z0-9]{8,64}$/.test(pw); }

  const api = { WARNING, HOURS, DEFAULT_HOURS, META, DEFAULT_META, LIMITS, STOPS, PHASES, remaining, hoursLabel,
                indicator, status, startArgs, passwordOk };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxDiffusion = api; }
})(typeof window !== "undefined" ? window : globalThis);
