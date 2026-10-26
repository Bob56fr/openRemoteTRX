/* Client web de référence de la station TRX.
 *
 * Il parle exactement le protocole de la passerelle (voir gateway/api/protocol.py) et sert de
 * référence pour l'application Android :
 *   GET config -> serveurs ICE ; POST offer {client_id, password, sdp, type} -> réponse SDP ;
 *   canal de données « control » (JSON) ;
 *   commandes toggle / stop / heartbeat / set_frequency / set_mode / get_state ;
 *   messages hello / state / result / error.
 *
 * Deux couches : TrxClient (logique pure, testée sous Node avec un faux navigateur) et, en bas,
 * l'interface DOM (utilisée seulement dans un vrai navigateur).
 *
 * Sécurité côté client : le micro n'est activé que pendant TX confirmé ET propriétaire ; l'émission
 * doit être « autorisée » avant chaque prise (et se désarme à la fin) ; la page masquée coupe l'émission ;
 * un heartbeat est envoyé tant que l'émission est active (sans lui, la passerelle coupe en ~2 s).
 */
(function (root) {
  "use strict";

  const HEARTBEAT_TICK_MS = 400;
  const PING_EVERY_MS = 2000;
  const COMMAND_TIMEOUT_MS = 5000;
  const STALE_MS = 5000;                // plus aucun message de la station depuis ce délai : liaison perdue
  const HELLO_TIMEOUT_MS = 15000;       // le canal de contrôle doit s'ouvrir dans ce délai après la réponse de la station
  const NUDGE_FLUSH_MS = 120;           // les crans de fréquence rapprochés sont regroupés en UNE commande
  const PENDING_MAX_MS = 2500;          // fréquence demandée affichée en attendant la confirmation du poste
  const RECONNECT_TICK_MS = 500;        // cadence de la boucle de reconnexion automatique
  const RECONNECT_FIRST_DELAY_MS = 400; // premier essai quasi immédiat (sous la cadence de la boucle : une minuterie en avance ne le repousse pas) : une micro-coupure 4G se rétablit en une ou deux secondes
  const RECONNECT_RETRY_MS = 1500;      // attente avant le prochain essai : 1,5 s, puis 3 s, puis 4,5 s au plus
  const RECONNECT_HELLO_MS = 6000;      // en reconnexion, un canal qui ne s'ouvre pas en 6 s est abandonné pour réessayer
  const MAX_RECONNECT_WINDOW_S = 300;
  const BAND_STABLE_MS = 1500;          // fréquence stable avant d'être mémorisée pour sa bande
  const HEARTBEAT_GRACE_MS = 3000;       // heartbeats dès la demande de prise d'émission
  const LINK_ALERT_REPEAT_MS = 3000;     // son « liaison perdue » répété tant que la reconnexion dure
  const TX_SILENCE_MS = 1500;            // pendant SON émission, plus rien de la station depuis ce délai : alerte tout de suite
  const ACTIVE_STATES = ["KEYING", "TX", "UNKEYING"];

  const REASONS = {
    out_of_band: "Fréquence hors des bandes d'émission autorisées.",
    cooldown: "Trop rapproché : attends une seconde avant de réémettre.",
    unknown_client: "Client non reconnu par la passerelle.",
    tx_disabled: "Aucune bande d'émission autorisée dans la configuration.",
    cat_down: "Liaison avec le poste perdue.",
    cat_error: "Le poste ne répond pas correctement.",
    ptt_unreadable: "L'état du PTT n'est pas lisible sur ce poste : émission refusée par sécurité.",
    rig_already_tx: "Le poste est déjà en émission.",
    fault_latched: "Défaut verrouillé : intervention sur la station requise.",
    starting: "La station démarre : réessaie dans un instant.",
    not_idle: "Une coupure ou une émission est en cours.",
    cancelled: "Prise d'émission annulée par une coupure.",
    ptt_write_failed: "L'ordre d'émission a échoué ; retour en réception.",
    rig_did_not_key: "Le poste n'est pas passé en émission ; retour en réception.",
    tx_active: "Impossible pendant l'émission (fréquence, mode et réglages du poste sont verrouillés).",
    mode_not_allowed: "Émission refusée dans ce mode : le poste ne module par l'USB qu'en mode données (USB-D...). Change de mode.",
    unknown_memory: "Cette mémoire n'existe plus (supprimée depuis un autre appareil ?).",
    memories_unavailable: "Les mémoires ne sont pas disponibles sur cette station.",
    storage_error: "La station n'a pas pu enregistrer les mémoires (disque ?).",
    layouts_unavailable: "Les mises en page personnalisées ne sont pas disponibles sur cette station.",
    layout_invalid: "Mise en page refusée par la station (règles de sécurité ou de lisibilité non respectées).",
    layout_storage_error: "La station n'a pas pu enregistrer la mise en page (disque ?).",
    invalid: "Valeur refusée par le poste.",
    rig_error: "Erreur du poste.",
  };

  const CUT_REASONS = {
    tot: "durée maximale d'émission atteinte",
    heartbeat: "perte du signal de vie du client",
    toggle: "demande d'un client",
    stop: "bouton STOP",
    client_disconnected: "déconnexion du client émetteur",
    frequency_changed: "fréquence modifiée sur le poste",
    mode_changed: "mode modifié sur le poste pendant l'émission",
    rig_reported_rx: "le poste est repassé en réception",
    cat_down: "liaison avec le poste perdue",
    rig_silent: "poste muet",
    ptt_write_failed: "échec de l'ordre d'émission",
    rig_did_not_key: "le poste n'a pas émis",
    shutdown: "arrêt de la station",
    startup: "démarrage de la station",
  };

  const PTT_LABELS = { RX: "RÉCEPTION", KEYING: "PRISE D'ÉMISSION", TX: "ÉMISSION", UNKEYING: "COUPURE EN COURS" };

  // ------------------------------------------------------------------ fonctions pures

  function formatFrequency(hz) {
    if (hz === null || hz === undefined || !isFinite(hz)) return "—";
    return String(Math.round(hz)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " Hz";
  }

  function sMeterText(db) {            // dB relatifs à S9 (S9 = 0 ; un point S = 6 dB)
    if (db === null || db === undefined) return "—";
    if (db >= 0) return db === 0 ? "S9" : "S9+" + Math.round(db) + " dB";
    return "S" + Math.max(0, Math.round(9 + db / 6));
  }

  function levelFraction(db, low) {    // 0..1 entre `low` dB et 0 dB
    if (db === null || db === undefined) return 0;
    const floor = low === undefined ? -60 : low;
    return Math.min(1, Math.max(0, (db - floor) / -floor));
  }

  function sMeterFraction(db) {        // S0 (-54 dB) .. S9+60
    if (db === null || db === undefined) return 0;
    return Math.min(1, Math.max(0, (db + 54) / 114));
  }

  function reasonText(code, detail) {
    return REASONS[code] || ("Refusé (" + code + (detail ? " : " + detail : "") + ")");
  }

  function cutText(code) {
    return code ? (CUT_REASONS[code] || code) : "";
  }

  // Modes « données » : le nom dépend de la version de Hamlib (4.7 : FM-D et AM-D au lieu de PKTFM, PKTAM).
  const DATA_MODES = { USB: ["PKTUSB"], LSB: ["PKTLSB"], FM: ["PKTFM", "FM-D"], AM: ["PKTAM", "AM-D"] };
  const MODE_LABELS = { PKTUSB: "USB-D (données)", PKTLSB: "LSB-D (données)", PKTFM: "FM-D (données)", PKTAM: "AM-D (données)",
                        "FM-D": "FM-D (données)", "AM-D": "AM-D (données)" };

  function dataModeFor(mode, available) {
    /* Mode données de `mode` parmi `available` (null si aucun) ; sans liste connue, le nom habituel. */
    const names = DATA_MODES[mode] || [];
    if (!Array.isArray(available) || available.length === 0) return names[0] || null;
    return names.find((n) => available.includes(n)) || null;
  }

  function modeLabel(mode) {
    return MODE_LABELS[mode] || mode || "—";
  }

  function txModeHint(mode, txModes, modes) {
    /* La station peut limiter l'émission à certains modes (tx_modes) : message bloquant, avec le mode à choisir. */
    if (!Array.isArray(txModes) || txModes.length === 0 || !mode || txModes.includes(mode)) return "";
    const available = txModes.filter((m) => !Array.isArray(modes) || modes.length === 0 || modes.includes(m));
    const wanted = dataModeFor(mode, available);
    const suggestion = wanted && available.includes(wanted) ? wanted : available[0] || txModes[0];
    return "Émission impossible en " + modeLabel(mode) + " : la station n'autorise que " + txModes.map(modeLabel).join(", ") +
           ". Passe en " + modeLabel(suggestion) + ".";
  }

  function matchesRigDevice(label, names) {
    /* Le périphérique est-il celui du poste ? (« Par défaut - Micro (USB Audio Device) » correspond à « Micro (USB Audio Device) »)
       Un micro qui serait la sortie audio du poste renverrait la réception dans l'émission ; une sortie qui serait
       son entrée audio injecterait le son reçu dans l'émetteur. */
    if (!label || !Array.isArray(names)) return false;
    const clean = String(label).toLowerCase().replace(/^(par défaut|default|communications)\s*-\s*/, "").trim();
    return names.some((name) => {
      const wanted = String(name).toLowerCase().trim();
      return wanted.length > 0 && (clean.includes(wanted) || (clean.length >= 6 && wanted.includes(clean)));
    });
  }

  function dataModeHint(mode, modes) {
    const target = Array.isArray(modes) && modes.length ? dataModeFor(mode, modes) : null;
    if (!target) return "";
    return "Le poste est en " + mode + " : pour émettre le micro de cette page par l'USB, passe en mode " + modeLabel(target) +
           ". En " + mode + ", la plupart des postes modulent avec leur propre micro.";
  }

  function formatIcomFrequency(hz) {
    /* 3 822 500 Hz -> « 3.822.50 » : MHz.kHz.10 Hz, comme l'afficheur d'un poste. */
    if (hz === null || hz === undefined || !isFinite(hz)) return "—";
    const whole = Math.round(hz);
    const mhz = Math.floor(whole / 1000000), rest = whole % 1000000;
    const khz = Math.floor(rest / 1000), tens = Math.floor((rest % 1000) / 10);
    return mhz + "." + String(khz).padStart(3, "0") + "." + String(tens).padStart(2, "0");
  }

  const SHORT_MODES = { PKTUSB: "USB-D", PKTLSB: "LSB-D", PKTFM: "FM-D", PKTAM: "AM-D" };   // FM-D et AM-D s'affichent tels quels

  function shortMode(mode) {
    return mode ? (SHORT_MODES[mode] || mode) : "—";
  }

  const AGC_LABELS = { 0: "AGC-OFF", 1: "AGC-SF", 2: "AGC-F", 3: "AGC-S", 4: "AGC-U", 5: "AGC-M", 6: "AGC-A" };

  function sortMemories(list) {
    /* Favorites d'abord, puis par fréquence croissante (même règle que la station). */
    if (!Array.isArray(list)) return [];
    return list.filter((m) => m && typeof m === "object" && typeof m.id === "string" && typeof m.name === "string" && Number.isFinite(m.hz))
      .sort((a, b) => (!!a.favorite === !!b.favorite ? 0 : a.favorite ? -1 : 1) || a.hz - b.hz || a.name.localeCompare(b.name));
  }

  function chooseLayout(preference, isLandscape, width) {
    if (preference === "portrait" || preference === "landscape") return preference;
    return isLandscape && width >= 640 ? "landscape" : "portrait";   // « auto » : paysage seulement si l'écran est assez large
  }

  function squelchMarkerFraction(sql) {
    /* Position du repère de squelch sur l'échelle du S-mètre. Le squelch (0 à 1) correspond à l'échelle 0-255 du poste, qui est aussi
       celle du S-mètre (120 = S9, 241 = S9+60 dB). 0 = squelch ouvert : pas de repère. Repère INDICATIF. */
    if (sql === null || sql === undefined || !(sql > 0)) return null;
    const raw = Math.min(1, sql) * 255;
    return sMeterFraction(raw <= 120 ? -54 + raw * 54 / 120 : (raw - 120) * 60 / 121);
  }

  function formatWidth(hz) {
    return hz >= 1000 ? (hz / 1000).toFixed(hz % 1000 === 0 ? 0 : 1) + "k" : String(Math.round(hz));
  }

  function nearestIndex(values, target) {
    let best = -1, gap = Infinity;
    values.forEach((v, i) => { const d = Math.abs(v - target); if (d < gap) { gap = d; best = i; } });
    return best;
  }

  function filterLabel(widths, passband) {
    /* « FIL 2.4k » : largeur du filtre de réception en cours (celle de la liste la plus proche, sinon la largeur lue). */
    const i = nearestIndex(widths, passband);
    const close = i >= 0 && Math.abs(widths[i] - passband) <= Math.max(50, widths[i] * 0.15);
    return "FIL " + formatWidth(close ? widths[i] : passband);
  }

  const AGC_CYCLE = [2, 5, 3];          // FAST, MEDIUM, SLOW

  // ---- puissance d'émission : 5, 10, 25, 50, 80, 100 % de la puissance maximale (en watts si la station connaît le maximum)
  const POWER_STEPS = [0.05, 0.1, 0.25, 0.5, 0.8, 1];

  const POWER_TOLERANCE = 0.015;        // le poste relit une valeur arrondie (5 % -> 5,1 %) : on la rattache au palier le plus proche

  function powerStepIndex(fraction) {
    return POWER_STEPS.findIndex((step) => Math.abs(step - fraction) <= POWER_TOLERANCE);
  }

  function powerLabel(fraction, maxWatts) {
    if (!(fraction >= 0)) return "PWR";
    const snapped = powerStepIndex(fraction);
    if (snapped >= 0) fraction = POWER_STEPS[snapped];
    if (maxWatts > 0) {
      const watts = fraction * maxWatts;
      return "PWR " + (Math.abs(watts - Math.round(watts)) < 0.05 ? Math.round(watts) : watts.toFixed(1)) + "W";
    }
    return "PWR " + Math.round(fraction * 100) + "%";
  }

  function nextPower(fraction) {
    /* La puissance SUPÉRIEURE de la liste, puis retour au début en bouclant. Puissance inconnue : on commence par la plus faible. */
    if (!(fraction >= 0)) return POWER_STEPS[0];
    const at = powerStepIndex(fraction);
    if (at >= 0) return POWER_STEPS[(at + 1) % POWER_STEPS.length];
    const next = POWER_STEPS.find((step) => step > fraction);
    return next === undefined ? POWER_STEPS[0] : next;
  }

  // ---- fréquence : saisie, chiffres glissables, bandes
  const MIN_HZ = 1000, MAX_HZ = 6000000000;

  function parseFrequencyEntry(text) {
    /* « 7074 » ou « 7 074,5 » = kHz ; « 14.205 » ou « 7,074 » = MHz (moins de 1000) ; « 7.074.00 » = format du poste. null si invalide. */
    const raw = String(text === null || text === undefined ? "" : text).replace(/\s/g, "").replace(/,/g, ".");
    if (!raw) return null;
    let hz;
    const icom = /^(\d{1,4})\.(\d{3})\.(\d{1,2})$/.exec(raw);
    if (icom) hz = Number(icom[1]) * 1e6 + Number(icom[2]) * 1e3 + Number(icom[3].padEnd(2, "0")) * 10;
    else if (/^\d*\.?\d*$/.test(raw) && /\d/.test(raw)) { const n = parseFloat(raw); hz = n < 1000 ? n * 1e6 : n * 1e3; }
    else return null;
    hz = Math.round(hz);
    return hz >= MIN_HZ && hz <= MAX_HZ ? hz : null;
  }

  function frequencyDigits(hz) {
    /* Les caractères de l'afficheur « M.kkk.hh » avec le poids en Hz de chaque chiffre (null pour un point). */
    const text = formatIcomFrequency(hz);
    if (text === "—") return [];
    const [mhz, khz, tens] = text.split(".");
    const out = [];
    Array.from(mhz).forEach((c, i) => out.push({ char: c, weight: Math.pow(10, 6 + mhz.length - 1 - i) }));
    out.push({ char: ".", weight: null });
    Array.from(khz).forEach((c, i) => out.push({ char: c, weight: [100000, 10000, 1000][i] }));
    out.push({ char: ".", weight: null });
    Array.from(tens).forEach((c, i) => out.push({ char: c, weight: [100, 10][i] }));
    return out;
  }

  function nudgedFrequency(hz, weight, steps) {
    return Math.min(MAX_HZ, Math.max(MIN_HZ, Math.round(hz + weight * steps)));
  }

  const STEPS_HZ = [10, 100, 500, 1000, 5000, 9000, 10000, 12500, 25000];

  const BANDS = [
    { key: "160", label: "160", lo: 1800000, hi: 2000000, start: 1850000, mode: "LSB" },
    { key: "80", label: "80", lo: 3500000, hi: 4000000, start: 3700000, mode: "LSB" },
    { key: "60", label: "60", lo: 5250000, hi: 5450000, start: 5358500, mode: "USB" },
    { key: "40", label: "40", lo: 7000000, hi: 7300000, start: 7100000, mode: "LSB" },
    { key: "30", label: "30", lo: 10100000, hi: 10150000, start: 10130000, mode: "USB" },
    { key: "20", label: "20", lo: 14000000, hi: 14350000, start: 14200000, mode: "USB" },
    { key: "17", label: "17", lo: 18068000, hi: 18168000, start: 18130000, mode: "USB" },
    { key: "15", label: "15", lo: 21000000, hi: 21450000, start: 21300000, mode: "USB" },
    { key: "12", label: "12", lo: 24890000, hi: 24990000, start: 24950000, mode: "USB" },
    { key: "10", label: "10", lo: 28000000, hi: 29700000, start: 28400000, mode: "USB" },
    { key: "6", label: "6", lo: 50000000, hi: 54000000, start: 50150000, mode: "USB" },
  ];

  function bandOf(hz) {
    return Number.isFinite(hz) ? BANDS.find((b) => hz >= b.lo && hz <= b.hi) || null : null;
  }

  function adaptMode(mode, txModes, modes) {
    /* Mode à utiliser pour un rappel : respecte les modes d'émission autorisés (USB -> USB-D) ; null si le poste ne l'a pas. */
    let chosen = mode;
    if (Array.isArray(txModes) && txModes.length && !txModes.includes(chosen)) {
      const data = dataModeFor(chosen, txModes);
      if (data && txModes.includes(data)) chosen = data;
    }
    if (Array.isArray(modes) && modes.length && !modes.includes(chosen)) return null;
    return chosen;
  }

  function loadBandMemory(storage) {
    try {
      const data = JSON.parse(storage.get("trx.bands") || "{}");
      const clean = {};
      for (const b of BANDS) {
        const v = data && data[b.key];
        if (v && Number.isFinite(v.hz) && v.hz >= b.lo && v.hz <= b.hi && typeof v.mode === "string" && /^[A-Za-z0-9-]{1,16}$/.test(v.mode)) clean[b.key] = { hz: v.hz, mode: v.mode };
      }
      return clean;
    } catch (e) { return {}; }
  }

  function rememberBand(memory, hz, mode) {
    const band = bandOf(hz);
    if (!band || !mode) return null;
    const current = memory[band.key];
    if (current && current.hz === hz && current.mode === mode) return null;
    return Object.assign({}, memory, { [band.key]: { hz: hz, mode: mode } });
  }

  function bandTarget(memory, key, txModes, modes) {
    /* Dernière fréquence et dernier mode utilisés sur cette bande, sinon un point de départ usuel. */
    const band = BANDS.find((b) => b.key === key);
    if (!band) return null;
    const saved = memory && memory[key];
    const base = saved ? { hz: saved.hz, mode: saved.mode } : { hz: band.start, mode: band.mode };
    return { hz: base.hz, mode: adaptMode(base.mode, txModes, modes) };
  }

  // ---- journal des pertes de connexion
  const MAX_LOSSES = 10;

  const LOSS_REASONS = {
    datachannel_closed: { kind: "lost", title: "Canal de contrôle fermé",
      explain: "Le canal de commande s'est fermé alors que la liaison était établie : la station, le réseau ou le VPN a coupé.",
      hint: "Regarde le journal de la station à la même heure, puis le VPN et le signal du téléphone." },
    connection_failed: { kind: "lost", title: "Liaison réseau échouée",
      explain: "Le chemin réseau (UDP) entre le téléphone et la station n'est plus utilisable.",
      hint: "Changement de réseau (Wi-Fi vers 4G), VPN coupé ou redémarré, ou redirection de port qui a expiré." },
    connection_closed: { kind: "lost", title: "Liaison fermée",
      explain: "Le navigateur a fermé la liaison WebRTC sans qu'on le lui demande.",
      hint: "Souvent un changement de réseau ou la mise en veille de la page par Android." },
    ice_failed: { kind: "lost", title: "Liaison réseau échouée (ICE)",
      explain: "Le test de connectivité réseau a échoué : plus aucun chemin n'est utilisable entre le téléphone et la station.",
      hint: "Vérifie le VPN, le pare-feu et que le trafic UDP n'est pas bloqué par le réseau." },
    silence: { kind: "lost", title: "Plus de nouvelles de la station",
      explain: "Aucun message n'est arrivé depuis plusieurs secondes alors que le canal paraissait ouvert : liaison gelée, réseau très dégradé ou page suspendue.",
      hint: "Si la page était en arrière-plan ou l'écran verrouillé, Android l'a suspendue : reste au premier plan, ou utilise l'application." },
    no_hello: { kind: "failed", title: "Canal de contrôle jamais ouvert",
      explain: "La station a répondu, mais la liaison WebRTC ne s'est pas établie dans le délai : le trafic UDP est très probablement bloqué.",
      hint: "VPN qui ne laisse pas passer l'UDP, pare-feu, NAT strict ou CGNAT : voir docs/acces-distant.md." },
    network: { kind: "failed", title: "Station injoignable",
      explain: "La requête de connexion n'a pas atteint la station.",
      hint: "Vérifie l'adresse, le VPN, le Wi-Fi ou la 4G, et que la station est démarrée." },
    auth: { kind: "failed", title: "Identifiants refusés",
      explain: "La station a refusé l'identifiant ou le mot de passe, ou bloque temporairement après trop d'essais.",
      hint: "Corrige le mot de passe ou attends quelques minutes." },
    busy: { kind: "failed", title: "Station occupée",
      explain: "La station a atteint son nombre maximal de connexions.", hint: "Déconnecte un autre appareil." },
    http: { kind: "failed", title: "Réponse inattendue de la station",
      explain: "La station a répondu par une erreur HTTP.", hint: "Regarde le journal de la station." },
    client_error: { kind: "failed", title: "Erreur dans le navigateur",
      explain: "Le navigateur n'a pas pu préparer la liaison WebRTC.", hint: "Recharge la page ; si cela persiste, note le détail ci-dessous." },
  };

  function describeLoss(entry, formatTime) {
    const fmt = formatTime || ((t) => new Date(t).toLocaleString("fr-FR"));
    const d = entry.details || {};
    const info = [];
    if (d.sessionS !== null && d.sessionS !== undefined) info.push("session " + (d.sessionS >= 60 ? Math.floor(d.sessionS / 60) + " min " + (d.sessionS % 60) + " s" : d.sessionS + " s"));
    if (d.lastMsgAgoS !== null && d.lastMsgAgoS !== undefined) info.push("dernier message il y a " + d.lastMsgAgoS + " s");
    if (d.lastRttMs !== null && d.lastRttMs !== undefined) info.push("dernier temps de réponse " + d.lastRttMs + " ms");
    if (d.pingFailures) info.push(d.pingFailures + " sondage(s) sans réponse");
    if (d.ptt) info.push("PTT " + d.ptt + (d.txMine ? " (ton émission : coupée par la station faute de signal de vie)" : ""));
    if (d.online === false) info.push("le téléphone n'avait PLUS de réseau");
    else if (d.online === true) info.push("réseau du téléphone : en ligne");
    if (d.visible === false) info.push("page MASQUÉE (arrière-plan)");
    if (d.connectionState) info.push("liaison : " + d.connectionState);
    if (d.iceState) info.push("ICE : " + d.iceState);
    if (d.dcState) info.push("canal : " + d.dcState);
    if (d.reconnect) {
      const outcome = { ok: "réussie", timeout: "abandonnée (délai écoulé)", auth: "abandonnée (identifiants refusés)", cancelled: "annulée" }[d.reconnect.outcome] || d.reconnect.outcome;
      info.push("reconnexion automatique " + outcome + " après " + d.reconnect.seconds + " s, " + d.reconnect.attempts + " essai(s)");
    }
    if (d.detail) info.push(d.detail);
    const lines = [(entry.kind === "failed" ? "Échec de connexion" : "Perte de connexion") + " — " + fmt(entry.t),
                   "Raison : " + entry.title, "Explication : " + entry.explain, "Piste : " + entry.hint, "Détails : " + (info.join(" · ") || "aucun")];
    if (Array.isArray(entry.logs) && entry.logs.length) {
      lines.push("Dernières lignes du journal :");
      for (const l of entry.logs) lines.push("  " + fmt(l.t).split(" ").pop() + "  " + l.text);
    }
    return lines.join("\n");
  }

  function lossSummary(entry, formatTime) {
    const fmt = formatTime || ((t) => new Date(t).toLocaleString("fr-FR"));
    const back = entry.details && entry.details.reconnect && entry.details.reconnect.outcome === "ok" ? " · reconnecté en " + entry.details.reconnect.seconds + " s" : "";
    return fmt(entry.t) + " · " + entry.title + (entry.kind === "failed" ? " (échec de connexion)" : "") + back;
  }

  function loadLosses(storage) {
    try {
      const list = JSON.parse(storage.get("trx.losses") || "[]");
      return Array.isArray(list) ? list.filter((e) => e && typeof e.title === "string" && Number.isFinite(e.t)).slice(0, MAX_LOSSES) : [];
    } catch (e) { return []; }
  }

  function preampText(level) {
    return level > 0 ? "P.AMP " + Math.round(level) : "P.AMP";
  }

  function parseKilohertz(text) {      // « 14 200,5 » -> 14200500 Hz ; null si invalide
    const value = parseFloat(String(text).replace(/\s/g, "").replace(",", "."));
    if (!isFinite(value)) return null;
    const hz = Math.round(value * 1000);
    return hz >= 1 && hz <= 10000000000 ? hz : null;
  }

  // ------------------------------------------------------------------ sons d'alerte de la liaison

  /* Trois sons bien distincts entre eux et des bips d'émission : notes [fréquence Hz, durée ms, silence après ms].
   * lost : deux notes DESCENDANTES (répétées pendant la reconnexion) ; restored : deux notes MONTANTES ;
   * failed : trois notes graves et longues. Vibrations (Android) dans le même rythme. */
  const LINK_ALERTS = {
    lost: { notes: [[880, 160, 60], [587, 260, 0]], vibrate: [200, 100, 300] },
    restored: { notes: [[587, 140, 50], [880, 220, 0]], vibrate: [80, 60, 80] },
    failed: { notes: [[330, 420, 140], [330, 420, 140], [247, 700, 0]], vibrate: [400, 150, 400, 150, 700] },
  };
  const ALERT_VOLUMES = { off: 0, low: 0.08, normal: 0.2, high: 0.45 };

  function alertVolume(name) { return Object.prototype.hasOwnProperty.call(ALERT_VOLUMES, name) ? ALERT_VOLUMES[name] : ALERT_VOLUMES.normal; }

  function alertDurationMs(kind) {
    const alert = LINK_ALERTS[kind];
    return alert ? alert.notes.reduce((total, [, ms, gap]) => total + ms + gap, 0) : 0;
  }

  // ------------------------------------------------------------------ logique du client

  class TrxClient {
    /* env : RTCPeerConnection, getConfig() -> {ice_servers}, waitIceComplete(pc, ms), postOffer(body) -> {status, body},
     *       getUserMedia(constraints), isSecureContext, now(), setInterval/clearInterval, collectStats(pc)
     * ui  : status(text, kind), state(view), log(text, level), remoteStream(stream, track), stats(text),
     *       rtt(ms), modes(list), armed(bool), connected(bool) ; facultatif : linkAlert(kind) = son « lost » | « restored » | « failed » */
    constructor(env, ui) {
      this.env = env;
      this.ui = ui;
      this.pc = null; this.dc = null; this.micTrack = null;
      this.clientId = ""; this.connected = false; this.closed = true;
      this.armed = false; this.hello = null; this.state = null;
      this.pending = new Map(); this.nextId = 1;
      this.hbUntil = 0; this.lastPing = 0; this.lastStats = 0; this.timer = null;
      this._wasActive = false;
      this.wakeLock = null; this.keepAwake = true; this._wakeLogged = false; this._wakeWarned = false;
      this.memories = [];
      this.pendingHz = null; this.pendingSince = 0; this._nudgeTimer = null;
      this.storage = env.storage || { get() { return null; }, set() {} };
      this.bandMemory = loadBandMemory(this.storage); this._bandSeen = ""; this._bandSince = 0;
      this.losses = loadLosses(this.storage);
      this.connectedAt = 0; this.lastMessageAt = 0; this.lastRttMs = null; this.pingFailures = 0; this._helloTimer = null;
      this.autoWindowS = 0; this._credentials = null; this.reconnecting = null; this._reconnectTimer = null; this._token = null;
      this.recentLogs = [];
      this._txSilenceAlerted = false;
      const rawLog = ui.log.bind(ui);                                  // le journal de l'écran alimente aussi le rapport de perte de connexion
      ui.log = (text, level) => { this.recentLogs.push({ t: this._epoch(), text: String(text).slice(0, 200) }); if (this.recentLogs.length > 20) this.recentLogs.shift(); rawLog(text, level); };
    }

    _epoch() { return this.env.epoch ? this.env.epoch() : Date.now(); }

    _linkAlert(kind) {                   // l'interface joue le son ; une erreur de son ne doit jamais gêner la liaison
      try { if (this.ui.linkAlert) this.ui.linkAlert(kind); } catch (e) { /* son indisponible */ }
    }

    // ---- connexion

    async connect(opts, auto) {
      if (!auto) this._finishReconnect("cancelled");                 // l'utilisateur reprend la main : plus de reconnexion automatique
      this.disconnect(true);
      const token = {};
      this._token = token;
      if (!auto) {
        this._credentials = Object.assign({}, opts);                  // gardés EN MÉMOIRE seulement (jamais dans le stockage) pour la reconnexion automatique
        this.autoWindowS = Math.max(0, Math.min(MAX_RECONNECT_WINDOW_S, Math.round(Number(opts.reconnectWindowS)) || 0));
        if (this.ui.reconnecting) this.ui.reconnecting({ active: false, outcome: "none" });
      }
      this.closed = false;
      this.keepAwake = opts.keepAwake !== false;
      this.clientId = opts.clientId;
      this.ui.status(auto ? "Reconnexion…" : "Connexion…", "busy");
      let iceServers = [];                                              // la station indique ses serveurs STUN (vide : réseau local/VPN)
      this.rigAudio = [];
      try {
        const config = await this.env.getConfig();
        iceServers = (config.ice_servers || []).map((url) => ({ urls: url }));
        this.rigAudio = Array.isArray(config.rig_audio) ? config.rig_audio : [];
      } catch (err) {
        this.ui.log("Configuration réseau de la station indisponible : connexion sans serveur STUN.", "warn");
      }
      let pc;
      try {
        pc = new this.env.RTCPeerConnection({ iceServers: iceServers });
        this.pc = pc;
        pc.ontrack = (ev) => this.ui.remoteStream(ev.streams && ev.streams[0] ? ev.streams[0] : null, ev.track);
        let mic = false;
        if (opts.useMic) {
          if (!this.env.isSecureContext || !this.env.getUserMedia) {
            this.ui.log("Micro indisponible : il faut une page HTTPS. Réception seule.", "warn");
          } else {
            try {
              const processing = opts.audioProcessing !== false;
              const audio = { echoCancellation: processing, noiseSuppression: processing, autoGainControl: false, channelCount: 1 };
              if (opts.micDeviceId) audio.deviceId = { exact: opts.micDeviceId };
              const stream = await this.env.getUserMedia({ audio: audio });
              const track = stream.getAudioTracks()[0];
              const label = track.label || "micro sans nom";
              if (!opts.ignoreRigWarning && matchesRigDevice(label, this.rigAudio)) {
                track.stop();
                this.ui.log("Micro REFUSÉ : « " + label + " » est une entrée/sortie audio du poste lui-même (la réception serait renvoyée dans l'émission). " +
                            "Choisis un autre micro, ou coche « Ce n'est pas le poste » si c'est une erreur. Réception seule.", "bad");
              } else {
                this.micTrack = track;
                this.micTrack.enabled = false;                         // fermé tant que l'émission n'est pas confirmée
                pc.addTrack(this.micTrack, stream);
                mic = true;
                this.ui.log("Micro utilisé : " + label + ".", "");
              }
            } catch (err) {
              this.ui.log("Micro refusé ou absent (" + (err && err.name ? err.name : err) + ") : réception seule.", "warn");
            }
          }
        }
        if (!mic) pc.addTransceiver("audio", { direction: "recvonly" });

        const dc = pc.createDataChannel("control");
        this.dc = dc;
        dc.onmessage = (ev) => this._onMessage(ev.data);
        dc.onclose = () => this._onClosed("datachannel_closed");
        pc.onconnectionstatechange = () => {
          if (pc.connectionState === "failed") this._onClosed("connection_failed");
          else if (pc.connectionState === "closed") this._onClosed("connection_closed");
          else if (pc.connectionState === "disconnected") this.ui.log("Liaison réseau instable (disconnected) : elle peut se rétablir seule.", "warn");
        };
        pc.oniceconnectionstatechange = () => { if (pc.iceConnectionState === "failed") this._onClosed("ice_failed"); };

        await pc.setLocalDescription(await pc.createOffer());
        await this.env.waitIceComplete(pc, 3000);                      // la passerelle attend un SDP complet
        let res;
        try {
          res = await this.env.postOffer({
            client_id: opts.clientId, password: opts.password,
            sdp: pc.localDescription.sdp, type: pc.localDescription.type });
        } catch (netErr) {
          throw Object.assign(new Error("La station est injoignable (réseau, VPN ou adresse incorrecte)."), { code: "network", detail: String(netErr && netErr.message || netErr) });
        }
        if (res.status === 401) throw Object.assign(new Error("Identifiant ou mot de passe refusé (ou trop d'essais : attends quelques minutes)."), { code: "auth" });
        if (res.status === 503) throw Object.assign(new Error("La station est occupée (trop de connexions)."), { code: "busy" });
        if (res.status !== 200) throw Object.assign(new Error("La station a répondu " + res.status + "."), { code: "http", detail: "HTTP " + res.status });
        if (this._token !== token) throw Object.assign(new Error("connexion annulée"), { code: "cancelled" });
        await pc.setRemoteDescription(res.body);
        this._helloTimer = this.env.setTimeout(() => {                  // la liaison WebRTC doit s'ouvrir : sinon l'UDP est bloqué
          this._helloTimer = null;
          if (!this.connected && !this.closed) this._failAttempt("no_hello");
        }, auto ? RECONNECT_HELLO_MS : HELLO_TIMEOUT_MS);
      } catch (err) {
        if (this._token !== token) throw err;                           // une autre connexion ou une déconnexion a pris le relais
        if (this.reconnecting) { this.disconnect(true); throw err; }    // l'échec est traité par la boucle de reconnexion
        const entry = this._buildEntry(err.code || "client_error", Object.assign({}, err.detail ? { detail: err.detail } : (err.code ? {} : { detail: String(err && err.message || err) })));
        this.disconnect(true);
        this._credentials = null;
        this.ui.status("Erreur", "bad");
        this._recordLoss(entry);
        throw err;
      }
    }

    disconnect(silent) {
      this._token = null;
      if (this.timer !== null) { this.env.clearInterval(this.timer); this.timer = null; }
      if (this._helloTimer !== null) { this.env.clearTimeout(this._helloTimer); this._helloTimer = null; }
      if (this._nudgeTimer !== null) { this.env.clearTimeout(this._nudgeTimer); this._nudgeTimer = null; }
      this.pendingHz = null;
      for (const entry of this.pending.values()) { entry.reject(new Error("déconnecté")); }
      this.pending.clear();
      this._releaseWakeLock();
      if (this.micTrack) { try { this.micTrack.enabled = false; this.micTrack.stop(); } catch (e) { /* déjà arrêtée */ } this.micTrack = null; }
      if (this.dc) { this.dc.onclose = null; try { this.dc.close(); } catch (e) { /* déjà fermé */ } this.dc = null; }
      if (this.pc) { this.pc.onconnectionstatechange = null; this.pc.oniceconnectionstatechange = null; try { this.pc.close(); } catch (e) { /* déjà fermée */ } this.pc = null; }
      const wasConnected = this.connected;
      this.connected = false; this.closed = true; this.armed = false; this._wasActive = false; this._txSilenceAlerted = false;
      this.state = null; this.hello = null; this.memories = []; this._spectrumKey = undefined;
      this.ui.connected(false); this.ui.armed(false); this.ui.memories([]);
      if (!silent) {                                                    // déconnexion voulue : jamais de reconnexion automatique, mot de passe oublié
        if (this.reconnecting) this._finishReconnect("cancelled");
        this._credentials = null;
        this.ui.status("Déconnecté", ""); if (wasConnected) this.ui.log("Déconnecté.", "");
      }
    }

    _buildEntry(code, extra) {
      /* Rapport de la perte : raison, contexte (réseau, page, temps de réponse, PTT) et dernières lignes du journal. */
      const reason = LOSS_REASONS[code] || LOSS_REASONS.client_error;
      const now = this.env.now();
      const p = this._ptt();
      const dcState = this.dc ? this.dc.readyState : null;
      const wasConnected = this.connected;
      return {
        t: this._epoch(), kind: wasConnected ? "lost" : "failed", code: code in LOSS_REASONS ? code : "client_error",
        title: reason.title, explain: reason.explain, hint: reason.hint,
        details: Object.assign({
          sessionS: wasConnected && this.connectedAt ? Math.round((now - this.connectedAt) / 1000) : null,
          lastMsgAgoS: this.lastMessageAt ? Math.round((now - this.lastMessageAt) / 1000) : null,
          lastRttMs: this.lastRttMs, pingFailures: this.pingFailures,
          ptt: p ? p.state : null, txMine: this._mineActive(),
          online: this.env.isOnline ? this.env.isOnline() : null, visible: this.env.isVisible ? this.env.isVisible() : null,
          connectionState: this.pc ? this.pc.connectionState || null : null, iceState: this.pc ? this.pc.iceConnectionState || null : null, dcState: dcState,
        }, extra || {}),
        logs: this.recentLogs.slice(-8),
      };
    }

    _saveLosses() {
      try { this.storage.set("trx.losses", JSON.stringify(this.losses)); } catch (e) { /* stockage plein ou indisponible : l'historique reste en mémoire */ }
    }

    _recordLoss(entry) {
      this.losses = [entry].concat(this.losses).slice(0, MAX_LOSSES);
      this._saveLosses();
      if (this.ui.lossRecorded) this.ui.lossRecorded(entry);
      if (this.ui.losses) this.ui.losses(this.losses);
    }

    _failAttempt(code) {
      const entry = this._buildEntry(code);
      this.disconnect(true);
      if (this.reconnecting) { this._attemptEnded(code); return; }
      this._credentials = null;
      this.ui.status("Erreur", "bad");
      this.ui.log(entry.title + " : " + entry.explain, "bad");
      this._recordLoss(entry);
    }

    _onClosed(code) {
      if (this.closed) return;
      const wasConnected = this.connected;
      if (this.reconnecting && !wasConnected) { this.disconnect(true); this._attemptEnded(code); return; }   // un essai de reconnexion qui échoue
      const entry = this._buildEntry(code);
      this.disconnect(true);
      if (wasConnected && this._credentials && this.autoWindowS > 0) {                        // micro-coupure : on retente sans redemander le mot de passe
        this.ui.log("Connexion perdue : " + entry.title + ". Reconnexion automatique pendant " + this.autoWindowS + " s.", "bad");
        this._recordLoss(entry);
        this._startReconnect(entry);
        return;
      }
      this._credentials = null;
      this.ui.status("Déconnecté", "bad");
      this.ui.log((wasConnected ? "Connexion perdue : " : "Connexion impossible : ") + entry.title + ". L'émission éventuelle est coupée par la station.", wasConnected ? "bad" : "warn");
      this._recordLoss(entry);
      if (wasConnected) this._linkAlert("failed");                   // sans reconnexion automatique : la liaison est perdue pour de bon
    }

    // ---- reconnexion automatique (micro-coupures du réseau mobile) : mêmes identifiants, gardés en mémoire seulement

    _startReconnect(entry) {
      const now = this.env.now();
      this.reconnecting = { entry: entry, startedAt: now, deadline: now + this.autoWindowS * 1000, attempts: 0,
                            nextAt: now + RECONNECT_FIRST_DELAY_MS, busy: false, lastTitle: entry.title, alertAt: now };
      this.ui.status("Reconnexion…", "busy");
      this._linkAlert("lost");
      this._reconnectUi();
      this._reconnectTimer = this.env.setInterval(() => this._reconnectTick(), RECONNECT_TICK_MS);
    }

    _reconnectUi() {
      const r = this.reconnecting;
      if (r && this.ui.reconnecting) {
        this.ui.reconnecting({ active: true, remainingS: Math.max(0, Math.ceil((r.deadline - this.env.now()) / 1000)),
                               attempt: r.attempts, windowS: this.autoWindowS, lastError: r.attempts ? r.lastTitle : "" });
      }
    }

    _reconnectTick() {
      const r = this.reconnecting;
      if (!r) return;
      const now = this.env.now();
      if (now >= r.deadline) { this._giveUp("timeout"); return; }
      if (now - r.alertAt >= LINK_ALERT_REPEAT_MS) { r.alertAt = now; this._linkAlert("lost"); }   // rappel : la liaison n'est toujours pas revenue
      this._reconnectUi();
      if (r.busy || now < r.nextAt) return;
      if (this.env.isOnline && this.env.isOnline() === false) return;                 // pas de réseau : inutile d'essayer, on attend son retour
      this._attempt();
    }

    async _attempt() {
      const r = this.reconnecting;
      r.busy = true; r.attempts += 1;
      this._reconnectUi();
      try { await this.connect(this._credentials, true); }
      catch (err) { if (this.reconnecting === r && err.code !== "cancelled") this._attemptEnded(err.code || "client_error"); }
    }

    _attemptEnded(code) {
      const r = this.reconnecting;
      if (!r) return;
      r.busy = false;
      r.lastTitle = (LOSS_REASONS[code] || LOSS_REASONS.client_error).title;
      if (code === "auth") { this._giveUp("auth"); return; }                           // identifiants refusés : on n'insiste jamais (la station bloque après 5 essais)
      r.nextAt = this.env.now() + RECONNECT_RETRY_MS * Math.min(r.attempts, 3);
      this._reconnectUi();
    }

    _reconnected() {
      const r = this.reconnecting;
      const seconds = Math.round((this.env.now() - r.startedAt) / 1000), attempts = r.attempts;
      this._finishReconnect("ok");
      this.ui.log("Reconnecté après " + seconds + " s (" + attempts + " essai" + (attempts > 1 ? "s" : "") + "). Recoche « Émission autorisée » pour émettre.", "");
      this._linkAlert("restored");                                     // la station est en RÉCEPTION : rien ne reprend tout seul
    }

    _giveUp(outcome) {
      const r = this.reconnecting;
      if (!r) return;
      this.disconnect(true);                                                          // coupe aussi un essai en cours
      this._credentials = null;
      this._finishReconnect(outcome);
      const text = { timeout: "Reconnexion abandonnée : plus de liaison après " + this.autoWindowS + " s.",
                     auth: "Reconnexion abandonnée : identifiants refusés par la station." }[outcome];
      if (text) { this.ui.status("Déconnecté", "bad"); this.ui.log(text, "bad"); this._linkAlert("failed"); } else this.ui.status("Déconnecté", "");
    }

    _finishReconnect(outcome) {
      if (this._reconnectTimer !== null) { this.env.clearInterval(this._reconnectTimer); this._reconnectTimer = null; }
      const r = this.reconnecting;
      if (!r) return;
      this.reconnecting = null;
      const seconds = Math.round((this.env.now() - r.startedAt) / 1000);
      r.entry.details.reconnect = { outcome: outcome, attempts: r.attempts, seconds: seconds };
      this._saveLosses();
      if (this.ui.reconnecting) this.ui.reconnecting({ active: false, outcome: outcome, seconds: seconds, attempts: r.attempts });
      if (this.ui.losses) this.ui.losses(this.losses);
    }

    cancelReconnect() {
      if (this.reconnecting) this._giveUp("cancelled");
    }

    onNetworkOnline() {                                                               // le réseau revient : on retente tout de suite
      if (this.reconnecting && !this.reconnecting.busy) this.reconnecting.nextAt = this.env.now();
    }

    clearLosses() {
      this.losses = [];
      try { this.storage.set("trx.losses", "[]"); } catch (e) { /* ignoré */ }
      if (this.ui.losses) this.ui.losses(this.losses);
    }

    // ---- messages

    _sendRaw(obj) {
      if (this.dc && this.dc.readyState === "open") this.dc.send(JSON.stringify(obj));
    }

    send(cmd, params) {
      return new Promise((resolve, reject) => {
        if (!this.dc || this.dc.readyState !== "open") { reject(new Error("non connecté")); return; }
        const id = this.nextId++;
        const timeout = this.env.setTimeout(() => { this.pending.delete(id); reject(new Error("pas de réponse de la station")); }, COMMAND_TIMEOUT_MS);
        this.pending.set(id, { resolve: (m) => { this.env.clearTimeout(timeout); resolve(m); },
                               reject: (e) => { this.env.clearTimeout(timeout); reject(e); } });
        this._sendRaw(Object.assign({ cmd: cmd, id: id }, params || {}));
      });
    }

    _onMessage(raw) {
      let msg;
      try { msg = JSON.parse(raw); } catch (e) { return; }
      this.lastMessageAt = this.env.now();
      if (this._txSilenceAlerted) {                                     // la station répond de nouveau (silence bref pendant l'émission)
        this._txSilenceAlerted = false;
        this.ui.log("La station répond de nouveau.", "");
        this._linkAlert("restored");
      }
      if (msg.type === "hello") {
        if (this._helloTimer !== null) { this.env.clearTimeout(this._helloTimer); this._helloTimer = null; }
        this.hello = msg;
        this.connected = true;
        this.connectedAt = this.env.now(); this.pingFailures = 0; this.lastRttMs = null;
        if (this.timer !== null) this.env.clearInterval(this.timer);                // un second « hello » ne doit pas doubler la minuterie
        this.timer = this.env.setInterval(() => this._tick(), HEARTBEAT_TICK_MS);
        this.ui.status("Connecté", "ok");
        this.ui.connected(true);
        const caps = msg.capabilities;
        this.ui.modes(caps && Array.isArray(caps.modes) ? caps.modes : []);
        this.memories = sortMemories(msg.memories);
        this.ui.memories(this.memories);
        this.ui.log("Connecté à la station (protocole " + msg.protocol + ").", "");
        this._acquireWakeLock();
        if (this.reconnecting) this._reconnected();
      } else if (msg.type === "memories") {
        this.memories = sortMemories(msg.items);
        this.ui.memories(this.memories);
      } else if (msg.type === "state") {
        this.state = msg;
        this._afterState();
      } else if (msg.type === "result") {
        const entry = this.pending.get(msg.id);
        if (entry) { this.pending.delete(msg.id); entry.resolve(msg); }
      } else if (msg.type === "error") {
        this.ui.log("Erreur de la station : " + msg.code + (msg.detail ? " (" + msg.detail + ")" : ""), "warn");
      }
    }

    // ---- état

    _ptt() { return this.state && this.state.ptt ? this.state.ptt : null; }
    _mineActive() { const p = this._ptt(); return !!p && p.owner === this.clientId && ACTIVE_STATES.includes(p.state); }
    _mineTx() { const p = this._ptt(); return !!p && p.owner === this.clientId && p.state === "TX"; }

    _afterState() {
      if (this.micTrack) this.micTrack.enabled = this._mineTx();       // micro ouvert seulement en TX confirmé
      const active = this._mineActive();
      if (this._wasActive && !active) {                                // fin d'émission : la case reste cochée (jusqu'à décision de l'utilisateur)
        const p = this._ptt();
        const why = cutText(p && p.last_cut_reason);
        this.ui.log("Retour en réception" + (why ? " (" + why + ")" : "") + ".", "");
      }
      this._wasActive = active;
      this._trackSpectrum();
      const rig = (this.state && this.state.rig) || {};
      const now = this.env.now();
      if (this.pendingHz !== null && (rig.frequency_hz === this.pendingHz || now - this.pendingSince > PENDING_MAX_MS)) this.pendingHz = null;
      this._trackBand(now, rig, active);
      this.ui.state(this.view());
    }

    _trackSpectrum() {
      /* Spectre HF (second port du poste) : prévient l'utilisateur quand la station revient au mode normal, et quand il revient. */
      const sp = (this.state && this.state.spectrum) || {};
      const key = (sp.state || "off") + "|" + (sp.code || "");
      if (key === this._spectrumKey) return;
      const before = this._spectrumKey;
      this._spectrumKey = key;
      if (sp.state === "error") this.ui.log("Spectre HF : problème de configuration. " + String(sp.message || sp.code || "").slice(0, 400), "warn");
      else if (sp.state === "ok" && before && before.startsWith("error")) this.ui.log("Spectre HF de nouveau disponible.", "");
    }

    _trackBand(now, rig, active) {
      /* Mémorise la dernière fréquence et le dernier mode de chaque bande, une fois stables (registres de bande). */
      const p = this._ptt();
      if (this.pendingHz !== null || active || (p && p.state !== "RX") || !rig.frequency_hz || !rig.mode) return;
      const key = rig.frequency_hz + "|" + rig.mode;
      if (this._bandSeen !== key) { this._bandSeen = key; this._bandSince = now; return; }
      if (now - this._bandSince >= BAND_STABLE_MS) {
        const next = rememberBand(this.bandMemory, rig.frequency_hz, rig.mode);
        if (next) {
          this.bandMemory = next;
          try { this.storage.set("trx.bands", JSON.stringify(next)); } catch (e) { /* ignoré */ }
        }
      }
    }

    view() {
      const p = this._ptt() || {};
      const rig = (this.state && this.state.rig) || {};
      const audio = (this.state && this.state.audio) || {};
      const state = p.state || "RX";
      const mine = this._mineActive();
      const other = !!p.owner && !mine && state !== "RX";
      const caps = this.hello && this.hello.capabilities ? this.hello.capabilities.modes : [];
      const txHint = txModeHint(rig.mode, this.hello ? this.hello.tx_modes : [], caps);
      const fn = rig.functions || {}, lv = rig.levels || {};
      const capsInfo = this.hello && this.hello.capabilities ? this.hello.capabilities : {};
      const controls = [];
      const fnControl = (key, label) => { if (key in fn) controls.push({ key: key, label: label, on: !!fn[key] }); };
      fnControl("NR", "NR"); fnControl("NB", "NB");
      if ("PREAMP" in lv) controls.push({ key: "PREAMP", label: preampText(lv.PREAMP), on: lv.PREAMP > 0 });
      fnControl("AIP", "IP+");
      if ("AGC" in lv) controls.push({ key: "AGC", label: AGC_LABELS[Math.round(lv.AGC)] || "AGC", on: lv.AGC > 0 });
      fnControl("COMP", "COMP");
      const widths = capsInfo.filters && rig.mode ? capsInfo.filters[rig.mode] : null;
      if (Array.isArray(widths) && widths.length > 1 && rig.passband_hz) controls.push({ key: "FIL", label: filterLabel(widths, rig.passband_hz), on: true });
      fnControl("TUNER", "TUNER");
      if ("RFPOWER" in lv) controls.push({ key: "PWR", label: powerLabel(lv.RFPOWER, this.hello ? this.hello.max_power_w : 0), on: true });
      const instruments = [];
      const add = (key, label, text, fraction) => { if (key in lv) instruments.push({ key, label, text, fraction }); };
      add("COMP_METER", "COMP", Number(lv.COMP_METER).toFixed(1) + " dB", Math.min(1, Math.max(0, lv.COMP_METER / 30)));
      add("VD_METER", "Vd", Number(lv.VD_METER).toFixed(1) + " V", Math.min(1, Math.max(0, (lv.VD_METER - 10) / 6)));
      add("TEMP_METER", "Temp", Math.round(lv.TEMP_METER) + " °C", Math.min(1, Math.max(0, (lv.TEMP_METER - 20) / 50)));
      if ("ATT" in lv) instruments.push({ key: "ATT", label: "ATT", text: lv.ATT > 0 ? Math.round(lv.ATT) + " dB" : "off", fraction: 0 });
      const swr = "SWR" in lv ? { fraction: Math.min(1, Math.max(0, (lv.SWR - 1) / 2)), text: Number(lv.SWR).toFixed(1) } : null;
      const alcFraction = "ALC" in lv ? Math.min(1, Math.max(0, lv.ALC)) : null;
      const alc = alcFraction === null ? null : { fraction: alcFraction, text: Math.round(alcFraction * 100) + " %" };
      const power = "RFPOWER_METER" in lv ? Math.min(1, Math.max(0, lv.RFPOWER_METER)) : null;
      return {
        connected: this.connected, armed: this.armed,
        frequencyIcom: formatIcomFrequency(this.pendingHz !== null ? this.pendingHz : rig.frequency_hz), modeShort: shortMode(rig.mode),
        frequencyHz: this.pendingHz !== null ? this.pendingHz : (Number.isFinite(rig.frequency_hz) ? rig.frequency_hz : null), frequencyPending: this.pendingHz !== null, band: (bandOf(this.pendingHz !== null ? this.pendingHz : rig.frequency_hz) || {}).key || null,
        controls: controls, controlsLocked: state !== "RX", instruments: instruments, power: power, swr: swr, alc: alc,
        powerText: power === null ? "—" : Math.round(power * 100) + " %",
        squelch: "SQL" in lv ? lv.SQL : null, squelchMark: "SQL" in lv ? squelchMarkerFraction(lv.SQL) : null,
        memories: this.memories, rig: rig,
        frequency: formatFrequency(rig.frequency_hz), mode: modeLabel(rig.mode),
        passband: rig.passband_hz === null || rig.passband_hz === undefined ? "" : rig.passband_hz + " Hz",
        sText: sMeterText(rig.strength_db), sFraction: sMeterFraction(rig.strength_db),
        pttState: state, pttLabel: PTT_LABELS[state] || state, mine: mine, owner: p.owner || null, other: other,
        tot: state === "TX" && p.tot_remaining_s !== null && p.tot_remaining_s !== undefined ? Math.round(p.tot_remaining_s) : null,
        totWarning: !!p.tot_warning, fault: p.fault || "",
        rxLevel: audio.rx_db === undefined ? "—" : audio.rx_db + " dBFS", txLevel: audio.tx_db === undefined ? "—" : audio.tx_db + " dBFS",
        clients: (this.state && this.state.clients) || [], lastCut: cutText(p.last_cut_reason),
        rigConnected: rig.connected !== false,
        dataModeHint: txHint || dataModeHint(rig.mode, caps),
        txBlocked: !!txHint,
      };
    }

    // ---- écran maintenu allumé (Screen Wake Lock : HTTPS requis ; relâché par le navigateur quand la page est masquée)

    async _acquireWakeLock() {
      if (!this.keepAwake || !this.connected || this.wakeLock) return;
      if (!this.env.requestWakeLock) {
        if (!this._wakeWarned) {
          this._wakeWarned = true;
          this.ui.log("Écran maintenu allumé indisponible (il faut une page HTTPS et un navigateur récent) : l'écran s'éteindra.", "warn");
        }
        return;
      }
      try {
        const lock = await this.env.requestWakeLock();
        if (!this.connected || this.wakeLock) { try { await lock.release(); } catch (e) { /* déjà relâché */ } return; }
        this.wakeLock = lock;
        if (lock.addEventListener) lock.addEventListener("release", () => { if (this.wakeLock === lock) this.wakeLock = null; });
        if (!this._wakeLogged) { this._wakeLogged = true; this.ui.log("Écran maintenu allumé tant que cette page est au premier plan.", ""); }
      } catch (err) {
        this.ui.log("Écran non maintenu allumé (" + (err && err.name ? err.name : err) + ") : mode économie de batterie ?", "warn");
      }
    }

    _releaseWakeLock() {
      const lock = this.wakeLock;
      this.wakeLock = null;
      if (lock && lock.release) {
        try { const r = lock.release(); if (r && r.catch) r.catch(() => {}); } catch (e) { /* déjà relâché */ }
      }
    }

    // ---- minuterie : signal de vie, ping, statistiques

    _tick() {
      const now = this.env.now();
      if (this.lastMessageAt && now - this.lastMessageAt > STALE_MS) { this._onClosed("silence"); return; }    // la station envoie son état plusieurs fois par seconde
      if (!this._txSilenceAlerted && this.lastMessageAt && now - this.lastMessageAt > TX_SILENCE_MS && this._mineActive()) {
        this._txSilenceAlerted = true;                                 // l'utilisateur parle peut-être dans le vide : on le prévient sans attendre la coupure
        this.ui.log("Plus de nouvelles de la station depuis " + String(TX_SILENCE_MS / 1000).replace(".", ",") + " s pendant ton émission : arrête de parler.", "bad");
        this._linkAlert("lost");
      }
      if (this._mineActive() || now < this.hbUntil) this._sendRaw({ cmd: "heartbeat" });
      if (now - this.lastPing >= PING_EVERY_MS) {
        this.lastPing = now;
        this.send("get_state").then(() => { this.pingFailures = 0; this.lastRttMs = Math.round(this.env.now() - now); this.ui.rtt(this.lastRttMs); })
          .catch(() => { this.pingFailures += 1; });
      }
      if (this.env.collectStats && now - this.lastStats >= PING_EVERY_MS) {
        this.lastStats = now;
        Promise.resolve(this.env.collectStats(this.pc)).then((r) => {
          if (r && r.net) this.ui.stats(r.net);
          if (r && r.diag) this.ui.diag(r.diag);
        }).catch(() => {});
      }
    }

    // ---- actions de l'utilisateur

    setArmed(value) {
      this.armed = !!value && this.connected;
      this.ui.armed(this.armed);
    }

    async pressPtt() {
      if (!this.connected) return null;
      const mine = this._mineActive();
      const p = this._ptt();
      if (!mine && !this.armed) { this.ui.log("Coche d'abord « Émission autorisée ».", "warn"); return null; }
      if (!mine && p && p.state !== "RX") { this.ui.log("Une émission est en cours (" + (p.owner || "?") + ") : utilise STOP pour couper.", "warn"); return null; }
      this.hbUntil = this.env.now() + HEARTBEAT_GRACE_MS;
      const res = await this.send("toggle");
      if (!res.ok) { this.hbUntil = 0; this.ui.log(reasonText(res.reason, res.detail), "warn"); }
      return res;
    }

    async stop() {
      if (!this.connected) return null;
      const res = await this.send("stop");
      this.hbUntil = 0;
      return res;
    }

    async setFrequency(hz) {
      const res = await this.send("set_frequency", { hz: hz });
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    async setMode(mode, passband) {
      const res = await this.send("set_mode", { mode: mode, passband: passband || 0 });
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    _caps() {
      return this.hello && this.hello.capabilities ? this.hello.capabilities : {};
    }

    async _rigSetting(cmd, params) {
      const res = await this.send(cmd, params);
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    async toggleFunction(name) {
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const current = !!(rig.functions && rig.functions[name]);
      return this._rigSetting("set_function", { name: name, on: !current });
    }

    async cyclePreamp() {
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const known = this._caps().preamps;
      const values = [0].concat(Array.isArray(known) && known.length ? known : [10]);
      const i = values.indexOf(Math.round((rig.levels || {}).PREAMP || 0));
      return this._rigSetting("set_level", { name: "PREAMP", value: values[(i + 1) % values.length] });
    }

    async cycleAgc() {
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const i = AGC_CYCLE.indexOf(Math.round((rig.levels || {}).AGC));
      return this._rigSetting("set_level", { name: "AGC", value: AGC_CYCLE[(i + 1) % AGC_CYCLE.length] });
    }

    async cycleFilter() {
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const widths = this._caps().filters && rig.mode ? this._caps().filters[rig.mode] : null;
      if (!Array.isArray(widths) || widths.length < 2 || !rig.passband_hz) return { ok: false };
      const next = widths[(nearestIndex(widths, rig.passband_hz) + 1) % widths.length];
      return this.setMode(rig.mode, next);
    }

    async cyclePower() {
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const current = rig.levels ? rig.levels.RFPOWER : undefined;
      return this._rigSetting("set_level", { name: "RFPOWER", value: nextPower(current) });
    }

    nudgeFrequency(weight, steps) {
      /* Un ou plusieurs crans sur un chiffre : l'affichage suit tout de suite, une seule commande part peu après. */
      if (!this.connected || !steps) return false;
      const p = this._ptt();
      if (p && p.state !== "RX") { this.ui.log(reasonText("tx_active"), "warn"); return false; }
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const base = this.pendingHz !== null ? this.pendingHz : rig.frequency_hz;
      if (!Number.isFinite(base)) return false;
      this.pendingHz = nudgedFrequency(base, weight, steps);
      this.pendingSince = this.env.now();
      this.ui.state(this.view());
      if (this._nudgeTimer === null) this._nudgeTimer = this.env.setTimeout(() => { this._nudgeTimer = null; this._flushNudge(); }, NUDGE_FLUSH_MS);
      return true;
    }

    async _flushNudge() {
      let sent = null;
      while (this.pendingHz !== null && this.pendingHz !== sent && this.connected) {
        sent = this.pendingHz;
        try {
          const res = await this.setFrequency(sent);
          if (!res.ok) { this.pendingHz = null; this.ui.state(this.view()); return; }
        } catch (err) { this.pendingHz = null; this.ui.log(err.message, "warn"); return; }
      }
    }

    async goBand(key) {
      if (!this.connected) return { ok: false };
      if (this._ptt() && this._ptt().state !== "RX") { this.ui.log(reasonText("tx_active"), "warn"); return { ok: false, reason: "tx_active" }; }
      const rig = this.state && this.state.rig ? this.state.rig : {};
      const target = bandTarget(this.bandMemory, key, this.hello ? this.hello.tx_modes : [], this._caps().modes);
      if (!target) return { ok: false };
      if (target.mode && rig.mode !== target.mode) {
        const done = await this.setMode(target.mode, 0);                                       // le mode d'abord, puis la fréquence
        if (!done.ok) return done;
      }
      this.pendingHz = null;
      return this.setFrequency(target.hz);
    }

    async pressControl(key) {
      if (!this.connected) return { ok: false };
      if (this._ptt().state !== "RX") {
        this.ui.log(reasonText("tx_active"), "warn");                 // la station refuserait aussi : inutile de le lui demander
        return { ok: false, reason: "tx_active" };
      }
      if (key === "PWR") return this.cyclePower();
      if (key === "PREAMP") return this.cyclePreamp();
      if (key === "AGC") return this.cycleAgc();
      if (key === "FIL") return this.cycleFilter();
      return this.toggleFunction(key);
    }

    async setSquelch(value) {
      const res = await this.send("set_squelch", { value: value });
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    async saveMemory(fields) {
      const params = { name: fields.name, hz: fields.hz, mode: fields.mode, favorite: !!fields.favorite };
      if (fields.memoryId) params.memory_id = fields.memoryId;
      const res = await this.send("memory_save", params);
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    async deleteMemory(memoryId) {
      const res = await this.send("memory_delete", { memory_id: memoryId });
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    async recallMemory(memoryId) {
      const res = await this.send("memory_recall", { memory_id: memoryId });
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    // ---- mises en page (designer) : profil de CE compte, stocké sur la station ; aucun effet sur le poste
    async getLayout() {
      const res = await this.send("layout_get");
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;                          // { ok, profile, source: "user" | "factory", warnings }
    }

    async saveLayout(profile) {
      const res = await this.send("layout_save", { profile: profile });
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;                          // refus : res.errors liste les problèmes, en français
    }

    async resetLayout() {
      const res = await this.send("layout_reset");
      if (!res.ok) this.ui.log(reasonText(res.reason, res.detail), "warn");
      return res;
    }

    onVisibility(hidden) {               // un navigateur en arrière-plan ralentit ses minuteries : on coupe avant
      if (hidden && this._mineActive()) {
        this.ui.log("Page masquée : émission coupée par sécurité.", "warn");
        this.stop().catch(() => {});
      }
      if (!hidden) { this._acquireWakeLock(); this.onNetworkOnline(); }   // le navigateur a relâché le verrou ; au retour de la page, on retente sans attendre
    }
  }

  const api = { REASONS, CUT_REASONS, TrxClient, formatFrequency, sMeterText, sMeterFraction, levelFraction,
                reasonText, cutText, parseKilohertz, matchesRigDevice, dataModeHint, dataModeFor, DATA_MODES, MODE_LABELS,
                modeLabel, txModeHint, formatIcomFrequency, shortMode, sortMemories, chooseLayout, preampText, AGC_LABELS,
                squelchMarkerFraction, formatWidth, filterLabel, nearestIndex, AGC_CYCLE,
                POWER_STEPS, powerLabel, nextPower, parseFrequencyEntry, frequencyDigits, nudgedFrequency, STEPS_HZ, BANDS, bandOf, adaptMode,
                loadBandMemory, rememberBand, bandTarget, LOSS_REASONS, describeLoss, lossSummary, loadLosses, MAX_LOSSES,
                LINK_ALERTS, ALERT_VOLUMES, alertVolume, alertDurationMs };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxWeb = api; }
})(typeof window !== "undefined" ? window : globalThis);
