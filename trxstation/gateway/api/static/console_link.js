// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
/* Raccourci « Console de la station » (étape 230) : la page remplit le modèle console-station.cmd (servi par la
   station) avec l'adresse par laquelle CE PC joint la station, le compte SSH et les ports annoncés dans
   hello.remote_console (opérateurs seulement). Aucun secret. Calculs purs, testés sous Node
   (tests/js/console_link_test.js) ; le bouton est dans ui.js. */
(function (root) {
  "use strict";

  const HOST_RE = /^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*|[0-9A-Fa-f:.]{2,45})$/;
  const USER_RE = /^[a-z_][a-z0-9_.-]{0,31}$/;          // comme [remote_console] ssh_user (config.py)

  function port(value, low) {
    return Number.isInteger(value) && value >= low && value <= 65535 ? value : null;
  }

  function host(hostname) {
    /* location.hostname -> adresse utilisable par ssh, ou null. IPv6 : crochets retirés. */
    if (typeof hostname !== "string") return null;
    const h = hostname.replace(/^\[(.*)\]$/, "$1");
    return h.length <= 253 && HOST_RE.test(h) ? h : null;
  }

  function settings(hello, hostname) {
    /* Réglages du raccourci, ou null si la station ne l'offre pas (ou valeurs douteuses : jamais de fichier faux). */
    const rc = hello && typeof hello === "object" ? hello.remote_console : null;
    if (!rc || typeof rc !== "object") return null;
    const h = host(hostname);
    const user = typeof rc.user === "string" && USER_RE.test(rc.user) ? rc.user : null;
    const sshPort = port(rc.ssh_port, 1), webPort = port(rc.web_port, 1024);
    if (!h || !user || sshPort === null || webPort === null) return null;
    return { host: h, user: user, sshPort: sshPort, webPort: webPort };
  }

  function build(template, s) {
    /* Modèle rempli, lignes en CRLF (cmd.exe), ou null. */
    if (typeof template !== "string" || !s || !template.includes("#PS-BEGIN#")) return null;
    const out = template.replace(/@@HOST@@/g, s.host).replace(/@@USER@@/g, s.user)
      .replace(/@@SSH_PORT@@/g, String(s.sshPort)).replace(/@@WEB_PORT@@/g, String(s.webPort));
    if (out.includes("@@")) return null;
    return out.replace(/\r\n/g, "\n").replace(/\n/g, "\r\n");
  }

  function fileName(s) {
    return "Console de la station (" + s.host.replace(/[^A-Za-z0-9.-]/g, "_") + ").cmd";
  }

  const api = { host, settings, build, fileName };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; } else { root.TrxConsoleLink = api; }
})(typeof window !== "undefined" ? window : globalThis);
