// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// Indicateur TRX distant de la barre du haut (GNOME) : logique pure, sans GNOME, testée sous Node (tests/js/indicator_test.js).
// Entrée : les fichiers publiés par la station (lecture seule). Sortie : voyant, texte de la barre, lignes du menu.
// L'indicateur ne commande JAMAIS la station : il lit seulement.

export const STALE_S = 5;            // fichier d'état plus vieux : passerelle muette (elle écrit 4 fois par seconde)

const MODE_LABELS = { PKTUSB: "USB-D", PKTLSB: "LSB-D", PKTFM: "FM-D", PKTAM: "AM-D", "FM-D": "FM-D", "AM-D": "AM-D" };
const CUT_REASONS = {
  tot: "durée maximale d'émission atteinte", heartbeat: "perte du signal de vie du client", toggle: "demande d'un client",
  stop: "bouton STOP", client_disconnected: "déconnexion du client émetteur", frequency_changed: "fréquence modifiée sur le poste",
  mode_changed: "mode modifié sur le poste pendant l'émission", rig_reported_rx: "le poste est repassé en réception",
  cat_down: "liaison avec le poste perdue", rig_silent: "poste muet", rig_overheat: "poste trop chaud",
  ptt_write_failed: "échec de l'ordre d'émission", rig_did_not_key: "le poste n'a pas émis", shutdown: "arrêt de la station",
  startup: "démarrage de la station", spectrum_port_keyed: "port du spectre mal réglé",
};
const LOCAL_REASONS = { tx: "émission au micro du poste", frequency: "fréquence changée sur le poste", mode: "mode changé sur le poste" };
const SPECTRUM = { ok: "reçu", waiting: "en attente de la réception", starting: "démarrage", error: "en panne" };
const CLUSTER = { green: "toutes les sources connectées", orange: "sources en partie connectées", red: "aucune source connectée" };
const RANK = { ok: 0, info: 0, warn: 1, bad: 2 };

export function modeLabel(mode) {
  return MODE_LABELS[mode] || (typeof mode === "string" ? mode : "?");
}

export function clock(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

export function mhz(hz, decimals) {
  return Number.isFinite(hz) && hz > 0 ? (hz / 1e6).toFixed(decimals) : "?";
}

function width(hz) {
  return !Number.isFinite(hz) || hz <= 0 ? "" : hz >= 1000 ? (hz / 1000).toFixed(hz % 1000 === 0 ? 0 : 1) + " kHz" : hz + " Hz";
}

function text(value, max) {
  /* Texte venant d'un fichier : ramené à une ligne courte, sans caractère de contrôle. */
  return String(value === undefined || value === null ? "" : value).replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, max || 80);
}

export function summarize(input) {
  /* input : { status, nowS, safeMode, cluster, update, stationId, version }.
     Renvoie { level: "off" | "ok" | "tx" | "warn" | "safe" | "stale", label, lines: [{ key, text, level }] }. */
  const lines = [];
  const add = (key, value, level) => lines.push({ key: key, text: text(value, 120), level: level || "info" });
  const status = input && input.status && typeof input.status === "object" ? input.status : null;
  const nowS = Number(input && input.nowS) || 0;
  const safe = input && input.safeMode ? text(input.safeMode, 100) : "";
  let level = "ok", label = "TRX";

  if (safe) {
    level = "safe"; label = "MODE SÛR";
    add("Station", "MODE SÛR : " + safe + " (TRX Console, menu 9)", "bad");
  }
  const age = status ? nowS - Number(status.written_at) : Infinity;
  if (!status) {
    if (!safe) { level = "off"; label = "TRX arrêtée"; }
    add("Station", "arrêtée (TRX Console, menu 5 pour la démarrer)", safe ? "bad" : "info");
  } else if (!(age < STALE_S)) {
    if (!safe) { level = age > 120 ? "off" : "stale"; label = age > 120 ? "TRX arrêtée" : "TRX ?"; }
    add("Station", age > 120 ? "arrêtée" : "ne répond plus depuis " + Math.round(age) + " s", age > 120 ? "info" : "warn");
  }
  const fresh = status && age < STALE_S;
  if (fresh) {
    const ptt = status.ptt || {}, rig = status.rig || {}, levels = rig.levels || {};
    const clients = Array.isArray(status.clients) ? status.clients.map((c) => text(c, 32)) : [];
    if (!safe) add("Station", "en marche", "ok");
    const transmitting = ptt.state && ptt.state !== "RX";
    if (ptt.state === "TX") {
      const left = Number.isFinite(ptt.tot_remaining_s) ? ptt.tot_remaining_s : null;
      add("Émission", "ÉMISSION par " + (text(ptt.owner, 32) || "?") + (left === null ? "" : ", coupure automatique dans " + clock(left)),
          "bad");
      if (!safe) { level = "tx"; label = "TX " + (left === null ? "" : clock(left)); }
    } else if (transmitting) {
      add("Émission", ptt.state === "KEYING" ? "prise d'émission en cours" : "coupure en cours", "warn");
      if (!safe) { level = "tx"; label = "TX"; }
    } else {
      add("Émission", "réception", "ok");
    }
    if (rig.connected) {
      const freq = mhz(rig.frequency_hz, 6).replace(/(\d)(\d{3})$/, "$1.$2");
      add("Fréquence", freq + " MHz " + modeLabel(rig.mode) + (width(rig.passband_hz) ? ", filtre " + width(rig.passband_hz) : ""), "info");
      if (!transmitting && !safe) label = mhz(rig.frequency_hz, 3) + " " + modeLabel(rig.mode);
    } else {
      add("Poste", "liaison perdue" + (rig.last_error ? " (" + text(rig.last_error, 60) + ")" : "") + " : poste éteint ou débranché ?", "bad");
    }
    add("Clients web", clients.length ? clients.join(", ") : "aucun", clients.length ? "ok" : "info");
    if (Number.isFinite(ptt.local_remaining_s)) {
      add("Sur place", (LOCAL_REASONS[ptt.local_reason] || "action sur le poste") + " : PTT à distance bloqué "
          + (ptt.local_tx ? "pendant l'émission locale" : "encore " + clock(ptt.local_remaining_s)), "warn");
    }
    if (ptt.fault) add("Défaut", text(ptt.fault, 60) + " : intervention sur la station requise", "bad");
    if (ptt.last_cut_reason) add("Dernière coupure", CUT_REASONS[ptt.last_cut_reason] || text(ptt.last_cut_reason, 40), "info");
    if (ptt.temp_alert === "hot") add("Température", "POSTE TROP CHAUD (" + Math.round(ptt.temp_c) + " °C) : émission coupée", "bad");
    else if (ptt.temp_alert === "warn") add("Température", "poste chaud (" + Math.round(ptt.temp_c) + " °C)", "warn");
    else if (Number.isFinite(ptt.temp_c)) add("Température", Math.round(ptt.temp_c) + " °C", "info");
    if (Number.isFinite(levels.VD_METER)) add("Alimentation", levels.VD_METER.toFixed(1) + " V", levels.VD_METER < 12 ? "warn" : "info");
    const sp = status.spectrum || {};
    if (sp.state && sp.state !== "off") {
      add("Spectre HF", (SPECTRUM[sp.state] || text(sp.state, 20)) + (sp.state === "ok" && Number.isFinite(sp.fps) ? " (" + sp.fps + " /s)" : "")
          + (sp.state === "error" && sp.message ? " : " + text(sp.message, 80) : ""), sp.state === "error" ? "warn" : "info");
    }
  }
  const cluster = input && input.cluster;
  if (cluster && cluster.enabled !== false && CLUSTER[cluster.health]) {
    add("Cluster DX", CLUSTER[cluster.health], cluster.health === "green" ? "ok" : cluster.health === "orange" ? "warn" : "bad");
  }
  const release = input && input.update && input.update.release;
  if (release && release.version) add("Mise à jour", "version " + text(release.version, 20) + " disponible (TRX Console, menu 10)", "warn");
  if (input && input.version) add("Version", text(input.version, 20), "info");
  if (input && input.stationId) add("Identifiant", text(input.stationId, 40), "info");

  // Une anomalie colore le voyant en orange, sauf émission ou mode sûr (prioritaires).
  const worst = lines.reduce((m, l) => Math.max(m, RANK[l.level] || 0), 0);
  if (level === "ok" && worst >= 1) level = "warn";
  return { level: level, label: text(label, 24), lines: lines };
}
