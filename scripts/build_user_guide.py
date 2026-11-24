# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique la page web du guide de l'opérateur (User-Guide/<langue>/*.md) publiée par GitHub Pages.

Source : les fichiers Markdown de `User-Guide/<langue>/`, lisibles tels quels sur GitHub (référence : `fr`).
Ordre de la page : README.md (introduction et sommaire), puis les parties `NN-*.md` dans l'ordre des numéros ; les
fiches de poste (`postes/*.md`) se placent juste après la partie 1 (préparer le poste). Le récapitulatif (dernière
partie) a des cases à cocher cliquables, gardées dans le navigateur quand c'est possible.

Le Markdown reconnu est volontairement réduit : titres (#, ##, ###), paragraphes, listes à puces ou numérotées
(imbriquées par indentation, blocs de code compris), cases `- [ ]`, tableaux, citations `>` (encadré ; un encadré
qui commence par « **Sécurité » (ou son équivalent dans la langue, UI["danger"]) est rouge), blocs de code ```,
`code`, **gras**, *italique*, liens [texte](cible) et adresses https:// nues. Un lien vers un autre fichier .md du
guide devient une ancre de la page.

Deux blocs pour les textes propres à un système (Debian, Raspberry Pi, Windows), lisibles aussi sur GitHub :
- ONGLETS : `<!-- onglets -->`, puis un titre `#### Nom` par onglet, puis `<!-- /onglets -->`. Le même nom d'onglet
  (« Debian », « Raspberry Pi », « Windows », jamais traduit) se choisit partout dans la page d'un seul clic, et le
  choix est gardé dans le navigateur. À l'impression et dans le PDF, tous les onglets s'impriment l'un sous l'autre.
- ACCORDÉON : `<details>`, `<summary>Titre</summary>`, le contenu, `</details>` (balises seules sur leur ligne) ; fermé
  à l'écran, ouvert à l'impression.

Résultat : `docs/site/guide/index.html` (français) et `docs/site/guide/<langue>/index.html` (en, de, es), avec un
choix de langue en tête de chaque page. Mêmes noms de fichiers dans chaque langue (User-Guide/<langue>/) : les ancres
de la page en dépendent. Pas de copie par version : le guide décrit la dernière version.
Usage : python scripts/build_user_guide.py   (les tests vérifient que la page publiée est à jour).
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "User-Guide"
SITE = ROOT / "docs" / "site" / "guide"
LANGS = ("fr", "en", "de", "es")     # langues publiées ; « fr » = référence (page à la racine de guide/)
LANG_NAMES = {"fr": "Français", "en": "English", "de": "Deutsch", "es": "Español"}
TABS_OPEN, TABS_CLOSE = "<!-- onglets -->", "<!-- /onglets -->"
# Drapeaux du choix de langue, en SVG comme dans la console web (Windows n'affiche pas les drapeaux en emoji).
FLAGS = {
    "fr": '<rect width="20" height="40" fill="#002395"/><rect x="20" width="20" height="40" fill="#fff"/>'
          '<rect x="40" width="20" height="40" fill="#ED2939"/>',
    "en": '<rect width="60" height="40" fill="#012169"/>'
          '<path d="M0,0 L60,40 M60,0 L0,40" stroke="#fff" stroke-width="8"/>'
          '<path d="M0,0 L60,40 M60,0 L0,40" stroke="#C8102E" stroke-width="3"/>'
          '<path d="M30,0 V40 M0,20 H60" stroke="#fff" stroke-width="13"/>'
          '<path d="M30,0 V40 M0,20 H60" stroke="#C8102E" stroke-width="8"/>',
    "de": '<rect width="60" height="14" fill="#000"/><rect y="13" width="60" height="14" fill="#DD0000"/>'
          '<rect y="26" width="60" height="14" fill="#FFCE00"/>',
    "es": '<rect width="60" height="40" fill="#AA151B"/><rect y="10" width="60" height="20" fill="#F1BF00"/>',
}
REPO_URL = "https://github.com/Bob56fr/openRemoteTRX"
PART = re.compile(r"^(\d\d)-[a-z0-9-]+\.md$")
ANNEXES = ("glossaire.md",)          # fichiers hors parties numérotées, placés avant le récapitulatif
QUICK_START = "demarrage-rapide.md"  # démarrage rapide : juste après l'introduction, avant la partie 00
PDF_NAME = "guide-openRemoteTRX-{lang}.pdf"   # fabriqué à la publication par scripts/build_user_guide_pdf.py
# Schéma SVG propre à la langue (images/…svg) ou capture d'écran COMMUNE à toutes les langues (../captures/…) :
# les captures sont faites une fois (en anglais) et servent à chaque langue du guide ; leur légende est traduite.
IMAGE = re.compile(r"^!\[([^\]]+)\]\((images/[a-z0-9-]+\.svg|\.\./captures/[a-z0-9-]+\.(?:png|jpg))\)$")
CAPTURES = "captures"                # User-Guide/captures/ -> docs/site/guide/captures/
CAPTURE_MAX_BYTES = 600_000          # poids maximal d'une capture d'écran (page publique, PDF, iframe du site)
UI = {
    "fr": {"progress": "{n} / {m} étapes cochées", "reset": "Tout décocher", "print": "Imprimer",
           "saved": "Les cases cochées sont gardées dans ce navigateur.",
           "unsaved": "Ce navigateur ne garde pas les cases : imprime la page pour garder une trace.",
           "source": "Source de ce guide sur GitHub", "footer": "Projet libre (AGPL-3.0-or-later)",
           "top": "Haut de page", "enlarge": "ouvrir le schéma en grand",
           "pdf": "Télécharger en PDF", "pdf_hint": "A4, une partie par page, à imprimer",
           "glossary_more": "Voir le glossaire",
           "bubbles_title": "Les mots soulignés en pointillé",
           "bubbles_note": "ont une définition : survole-les à la souris ou touche-les (Tab puis Entrée au clavier) "
                           "pour la voir sans quitter la page. Toutes les définitions sont dans le",
           "bubbles_link": "glossaire du guide de l'opérateur",
           "danger": "**Sécurité", "lang_label": "Langue", "tabs_label": "Choisir le système"},
    "en": {"progress": "{n} / {m} steps ticked", "reset": "Untick all", "print": "Print",
           "saved": "Ticked boxes are kept in this browser.",
           "unsaved": "This browser does not keep the boxes: print the page to keep a record.",
           "source": "Source of this guide on GitHub", "footer": "Free software (AGPL-3.0-or-later)",
           "top": "Back to top", "enlarge": "open the diagram full size",
           "pdf": "Download as PDF", "pdf_hint": "A4, one part per page, to print",
           "glossary_more": "See the glossary",
           "bubbles_title": "Words with a dotted underline",
           "bubbles_note": "have a definition: hover or tap them (Tab then Enter with a keyboard) to read it without "
                           "leaving the page. All definitions are in the",
           "bubbles_link": "glossary of the operator guide",
           "danger": "**Safety", "lang_label": "Language", "tabs_label": "Choose the system"},
    "de": {"progress": "{n} / {m} Schritte abgehakt", "reset": "Alle Haken entfernen", "print": "Drucken",
           "saved": "Die Haken werden in diesem Browser gespeichert.",
           "unsaved": "Dieser Browser speichert die Haken nicht: Drucken Sie die Seite, um sie festzuhalten.",
           "source": "Quelle dieser Anleitung auf GitHub", "footer": "Freie Software (AGPL-3.0-or-later)",
           "top": "Nach oben", "enlarge": "Schema in voller Größe öffnen",
           "pdf": "Als PDF herunterladen", "pdf_hint": "A4, ein Teil pro Seite, zum Drucken",
           "glossary_more": "Zum Glossar",
           "bubbles_title": "Gepunktet unterstrichene Wörter",
           "bubbles_note": "haben eine Erklärung: Fahren Sie mit der Maus darüber oder tippen Sie sie an (Tab, dann "
                           "Enter mit der Tastatur), um sie zu lesen, ohne die Seite zu verlassen. Alle Erklärungen "
                           "stehen im",
           "bubbles_link": "Glossar der Bedieneranleitung",
           "danger": "**Sicherheit", "lang_label": "Sprache", "tabs_label": "System wählen"},
    "es": {"progress": "{n} / {m} pasos marcados", "reset": "Desmarcar todo", "print": "Imprimir",
           "saved": "Las casillas marcadas se guardan en este navegador.",
           "unsaved": "Este navegador no guarda las casillas: imprime la página para conservar un registro.",
           "source": "Fuente de esta guía en GitHub", "footer": "Software libre (AGPL-3.0-or-later)",
           "top": "Volver arriba", "enlarge": "abrir el esquema en grande",
           "pdf": "Descargar en PDF", "pdf_hint": "A4, una parte por página, para imprimir",
           "glossary_more": "Ver el glosario",
           "bubbles_title": "Las palabras subrayadas con puntos",
           "bubbles_note": "tienen una definición: pasa el ratón por encima o tócalas (Tab y luego Intro con el "
                           "teclado) para leerla sin salir de la página. Todas las definiciones están en el",
           "bubbles_link": "glosario de la guía del operador",
           "danger": "**Seguridad", "lang_label": "Idioma", "tabs_label": "Elegir el sistema"},
}

# Infobulles : termes du glossaire (premier nom en gras d'une ligne, ou un autre nom en gras de la même ligne)
# marqués à leur PREMIÈRE occurrence de chaque section (## du Markdown, h3 de la page) ; définition = la ligne du glossaire. Liste FERMÉE : un
# mot courant (« poste », « station ») couvrirait la page de pointillés. Pas de bulle dans le glossaire lui-même,
# ni dans les titres, le code, les liens et les en-têtes de tableau.
GLOSSARY = "glossaire.md"
BUBBLES = {
    "fr": ("CAT", "Charge fictive", "ALC", "TOS", "Hamlib", "rigctld", "Passerelle", "Superviseur", "openRemoteTRX Console",
           "Assistant de configuration", "Tableau de bord", "station.toml", "Profil de poste", "PTT", "TOT",
           "TOT absolu", "Battement", "Bandes autorisées", "Opérateur sur place", "Mise en sécurité", "HTTPS", "certificat",
           "Empreinte du certificat", "VPN", "Profil VPN", "Port ouvert", "CGNAT", "ntfy", "Code ORT", "Appairage",
           "Visiteur", "Compte opérateur", "WebRTC", "Réseau local", "Porte audio d'émission", "SSH"),
    "en": ("CAT", "Dummy load", "ALC", "SWR", "Hamlib", "rigctld", "Gateway", "Supervisor", "openRemoteTRX Console",
           "Configuration wizard", "Dashboard", "station.toml", "Transceiver profile", "PTT", "TOT", "Absolute TOT",
           "Heartbeat", "Allowed bands", "Local operator", "Safety lockout", "HTTPS", "certificate",
           "Certificate fingerprint", "VPN", "VPN profile", "Open port", "CGNAT", "ntfy", "ORT code", "Pairing",
           "Visitor", "Operator account", "WebRTC", "Local network", "Transmit audio gate", "SSH"),
    "de": ("CAT", "Dummy-Load", "ALC", "SWR", "Hamlib", "rigctld", "Gateway", "Supervisor", "openRemoteTRX Console",
           "Konfigurationsassistent", "Dashboard", "station.toml", "Transceiver-Profil", "PTT", "TOT", "Absoluter TOT",
           "Heartbeat", "Erlaubte Bänder", "Operator vor Ort", "Sicherheitsabschaltung", "HTTPS", "Zertifikat",
           "Fingerabdruck des Zertifikats", "VPN", "VPN-Profil", "Portfreigabe", "CGNAT", "ntfy", "ORT-Code", "Kopplung",
           "Besucher", "Operator-Konto", "WebRTC", "LAN", "Sende-Audiotor", "SSH"),
    "es": ("CAT", "Carga ficticia", "ALC", "ROE", "Hamlib", "rigctld", "Pasarela", "Supervisor", "openRemoteTRX Console",
           "Asistente de configuración", "Panel", "station.toml", "Perfil de transceptor", "PTT", "TOT",
           "TOT absoluto", "Latido", "Bandas permitidas", "Operador local", "Bloqueo de seguridad", "HTTPS",
           "certificado", "Huella del certificado", "VPN", "Perfil VPN", "Puerto abierto", "CGNAT", "ntfy",
           "Código ORT", "Emparejamiento", "Visitante", "Cuenta de operador", "WebRTC", "Red local",
           "Puerta de audio de transmisión", "SSH"),
}
NO_BUBBLE_TAGS = ("code", "pre", "a", "h1", "h2", "h3", "h4", "th", "figcaption", "button", "summary", "svg")   # svg : schéma intégré

# Infobulles : même aspect dans le guide et dans le mode d'emploi de la console (build_console_doc.py).
BUBBLES_CSS = """
.terme{border-bottom:1px dotted var(--accent);cursor:help}
.terme:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
.bulle{position:absolute;z-index:10;max-width:min(22rem,calc(100vw - 16px));background:var(--carte);
  border:1px solid var(--accent);border-radius:.5rem;padding:.5rem .75rem;font-size:.9rem;line-height:1.45;
  box-shadow:0 6px 20px rgba(0,0,0,.45)}
.bulle>strong{display:block;margin-bottom:.15rem}
.bulle .plus{display:inline-block;margin-top:.35rem;font-size:.85rem}
@media print{.terme{border:0}.bulle{display:none}}
"""

CSS = """
:root{--fond:#0f141c;--carte:#171e29;--ligne:#2a3445;--texte:#dbe3ee;--doux:#9aa8bb;--accent:#4c9be8;--emission:#e0524a;
  --ok:#3fae72;--code:#0b1017;color-scheme:dark}
*{box-sizing:border-box}
html{background:var(--fond)}
body{margin:0;background:var(--fond);color:var(--texte);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:56rem;margin:0 auto;padding:1.2rem 16px 2.5rem}
h1{font-size:1.7rem;line-height:1.2;margin:.4rem 0 .6rem}
h2{font-size:1.35rem;margin:2.6rem 0 .7rem;padding-bottom:.3rem;border-bottom:1px solid var(--ligne)}
h3{font-size:1.1rem;margin:1.6rem 0 .4rem}
h4{font-size:1rem;margin:1.2rem 0 .3rem;color:var(--doux)}
p{margin:.45rem 0 .8rem}
a{color:var(--accent);overflow-wrap:anywhere}
code{background:var(--code);border:1px solid var(--ligne);border-radius:.3rem;padding:0 .3rem;font-size:.92em;
  overflow-wrap:anywhere}
pre{background:var(--code);border:1px solid var(--ligne);border-radius:.5rem;padding:.6rem .8rem;overflow-x:auto;
  font-size:.9rem;white-space:pre-wrap;overflow-wrap:anywhere}
pre code{background:none;border:0;padding:0}
ul,ol{margin:.3rem 0 .9rem 1.3rem;padding:0}
li{margin:.25rem 0}
li>p{margin:.2rem 0}
.table{overflow-x:auto;margin:.6rem 0 1rem}
table{width:100%;border-collapse:collapse;font-size:.95rem}
th,td{border-bottom:1px solid var(--ligne);padding:.45rem .4rem;text-align:left;vertical-align:top}
th{color:var(--doux);font-weight:600}
.note{background:var(--carte);border:1px solid var(--ligne);border-left:.3rem solid var(--accent);border-radius:.5rem;
  padding:.5rem 1rem;margin:1rem 0}
.note.danger{border-left-color:var(--emission)}
.partie{scroll-margin-top:1rem}
.haut{font-size:.85rem;color:var(--doux)}
.cases{list-style:none;margin:.3rem 0 1rem;padding:0}
.cases li{margin:.15rem 0}
.cases label{display:flex;gap:.6rem;align-items:flex-start;background:var(--carte);border:1px solid var(--ligne);
  border-radius:.5rem;padding:.45rem .7rem;cursor:pointer}
.cases input{width:1.15rem;height:1.15rem;margin:.2rem 0 0;flex:none;accent-color:var(--ok)}
.cases input:checked+span{color:var(--doux);text-decoration:line-through}
.outils{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;background:var(--carte);border:1px solid var(--ligne);
  border-radius:.6rem;padding:.6rem .9rem;margin:1rem 0}
.outils strong{margin-right:auto}
.barre{flex-basis:100%;height:.5rem;background:var(--code);border-radius:.3rem;overflow:hidden}
.barre span{display:block;height:100%;width:0;background:var(--ok)}
.memo{flex-basis:100%;color:var(--doux);font-size:.85rem;margin:0}
button{font:inherit;color:var(--texte);background:var(--fond);border:1px solid var(--ligne);border-radius:2rem;
  padding:.2rem .9rem;cursor:pointer}
button:hover{border-color:var(--accent)}
.schema{margin:1rem 0 1.2rem;text-align:center}
.schema-svg{display:block;width:100%;max-width:40rem;height:auto;margin:0 auto}
.capture{margin:1rem 0 1.2rem;text-align:center}
.capture img{display:block;max-width:100%;height:auto;margin:0 auto;border:1px solid var(--ligne);border-radius:.4rem}
.capture.portrait img{max-width:min(100%,20rem)}
figcaption{color:var(--doux);font-size:.9rem;margin-top:.4rem}
.telecharger{margin:.2rem 0 1rem;font-size:.95rem}
.telecharger a{display:inline-block;border:1px solid var(--ligne);border-radius:2rem;padding:.2rem .9rem;
  text-decoration:none}
.telecharger span{color:var(--doux);margin-left:.5rem;font-size:.85rem}
footer{margin-top:2.5rem;color:var(--doux);font-size:.9rem;border-top:1px solid var(--ligne);padding-top:.8rem}
.langues{display:flex;flex-wrap:wrap;gap:.4rem;justify-content:flex-end;margin:0 0 .4rem;font-size:.9rem}
.langues a,.langues strong{display:inline-flex;align-items:center;gap:.4rem;border:1px solid var(--ligne);
  border-radius:2rem;padding:.15rem .7rem .15rem .45rem;text-decoration:none}
.langues svg{width:1.4rem;height:auto;border-radius:.15rem;box-shadow:0 0 0 1px rgba(255,255,255,.25);flex:none}
.langues strong{background:var(--carte);border-color:var(--accent);font-weight:600}
.onglets{margin:.8rem 0 1.2rem;border:1px solid var(--ligne);border-radius:.6rem;background:var(--carte)}
.onglets-barre{display:flex;flex-wrap:wrap;gap:.3rem;padding:.45rem .5rem 0;border-bottom:1px solid var(--ligne)}
.onglets-barre button{border-radius:.5rem .5rem 0 0;border-bottom:0;margin-bottom:-1px;padding:.35rem 1rem;
  background:var(--fond);color:var(--doux)}
.onglets-barre button[aria-selected="true"]{background:var(--carte);color:var(--texte);border-color:var(--accent);
  border-bottom:1px solid var(--carte);font-weight:600}
.onglet{padding:.2rem 1rem .6rem}
.onglets.actifs .onglet>.onglet-titre{display:none}
.onglet-titre{color:var(--accent)}
details{background:var(--carte);border:1px solid var(--ligne);border-radius:.5rem;padding:.3rem .9rem;margin:.6rem 0}
details>summary{cursor:pointer;font-weight:600;padding:.2rem 0}
details[open]>summary{margin-bottom:.3rem}
@media (max-width:30rem){.onglets-barre button{flex:1 1 auto;padding:.35rem .5rem}.onglet{padding:.2rem .6rem .6rem}}
@media print{
  :root{--fond:#fff;--carte:#fff;--ligne:#bbb;--texte:#000;--doux:#444;--code:#f3f3f3;color-scheme:light}
  .outils button,.haut,.telecharger,footer,.langues,.onglets-barre{display:none}
  .onglet[hidden]{display:block!important}
  .onglets.actifs .onglet>.onglet-titre{display:block}
  a{color:#000}
  .partie{break-before:page}
}
"""
CSS += BUBBLES_CSS

# Hauteur envoyée au site qui affiche la page dans une iframe, et cases du récapitulatif gardées dans le navigateur
# (essai protégé : un navigateur ou une iframe sans stockage garde les cases le temps de la visite seulement).
SCRIPT = """
(function () {
  var KEY = "trx-guide-%(lang)s";
  var boxes = Array.prototype.slice.call(document.querySelectorAll(".cases input"));
  var saved = {}, store = null;
  try { store = window.localStorage; saved = JSON.parse(store.getItem(KEY) || "{}") || {}; } catch (e) { store = null; }
  var memo = document.getElementById("memo");
  if (memo) memo.textContent = memo.getAttribute(store ? "data-saved" : "data-unsaved");
  function update() {
    var done = boxes.filter(function (b) { return b.checked; }).length;
    var text = document.getElementById("progress");
    if (text) text.textContent = text.getAttribute("data-model").replace("{n}", done).replace("{m}", boxes.length);
    var bar = document.getElementById("bar");
    if (bar) bar.style.width = (boxes.length ? Math.round(100 * done / boxes.length) : 0) + "%%";
  }
  function save() {
    if (!store) return;
    var state = {};
    boxes.forEach(function (b) { if (b.checked) state[b.id] = 1; });
    try { store.setItem(KEY, JSON.stringify(state)); } catch (e) { /* stockage plein ou refusé */ }
  }
  boxes.forEach(function (b) {
    b.checked = !!saved[b.id];
    b.addEventListener("change", function () { save(); update(); });
  });
  var reset = document.getElementById("reset");
  if (reset) reset.addEventListener("click", function () {
    boxes.forEach(function (b) { b.checked = false; }); save(); update();
  });
  var print = document.getElementById("print");
  if (print) print.addEventListener("click", function () { window.print(); });
  update();
  if (window.parent === window) return;
  var last = 0;
  function send() {
    // hauteur du contenu, pas celle de la fenêtre : l'iframe rapetisse aussi quand un onglet plus court s'affiche
    var h = Math.ceil(document.body.getBoundingClientRect().height);
    if (h !== last) { last = h; window.parent.postMessage({ type: "trx-doc-height", height: h }, "*"); }
  }
  window.addEventListener("load", send);
  if (window.ResizeObserver) new ResizeObserver(send).observe(document.body);
  else window.addEventListener("resize", send);
})();
"""


# Onglets par système : un clic choisit ce système dans TOUS les groupes d'onglets de la page (même nom) et le garde
# dans le navigateur (essai protégé, comme les cases). Sans script, tous les onglets restent affichés l'un sous
# l'autre avec leur titre. Avant l'impression, tous les accordéons s'ouvrent (les onglets cachés, par la feuille de
# style d'impression).
TABS_JS = """
(function () {
  var KEY = "trx-guide-systeme";
  var groups = Array.prototype.slice.call(document.querySelectorAll(".onglets"));
  var details = Array.prototype.slice.call(document.querySelectorAll("details"));
  window.addEventListener("beforeprint", function () { details.forEach(function (d) { d.open = true; }); });
  if (!groups.length) return;
  var saved = null;
  try { saved = window.localStorage.getItem(KEY); } catch (e) { saved = null; }
  function show(group, key) {
    var buttons = group.querySelectorAll(".onglets-barre button");
    var found = false;
    Array.prototype.forEach.call(buttons, function (b) { if (b.getAttribute("data-os") === key) found = true; });
    if (!found) key = buttons[0].getAttribute("data-os");
    Array.prototype.forEach.call(buttons, function (b) {
      var on = b.getAttribute("data-os") === key;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      document.getElementById(b.getAttribute("aria-controls")).hidden = !on;
    });
  }
  function choose(key) {
    groups.forEach(function (g) { show(g, key); });
    try { window.localStorage.setItem(KEY, key); } catch (e) { /* stockage refusé */ }
  }
  groups.forEach(function (group) {
    group.classList.add("actifs");
    var bar = group.querySelector(".onglets-barre");
    bar.hidden = false;
    var buttons = Array.prototype.slice.call(bar.querySelectorAll("button"));
    buttons.forEach(function (b, i) {
      b.addEventListener("click", function () {
        var top = b.getBoundingClientRect().top;
        choose(b.getAttribute("data-os"));
        window.scrollBy(0, b.getBoundingClientRect().top - top);   // l'onglet touché reste sous le doigt
      });
      b.addEventListener("keydown", function (e) {
        var step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        var next = buttons[(i + step + buttons.length) % buttons.length];
        next.click();
        next.focus();
      });
    });
    show(group, saved || "");
  });
})();
"""


# Infobulles : survol de la souris, toucher (tablette, téléphone) ou clavier (Tab puis Entrée) ; Échap, un toucher
# ailleurs ou la souris qui s'en va (après un court délai) la ferment. Ni bibliothèque ni ressource externe.
BUBBLES_JS = """
(function () {
  var defs = document.getElementById("defs");
  if (!defs) return;
  var bubble = null, owner = null, timer = 0, hovered = false;
  function close() {
    clearTimeout(timer);
    if (bubble) { bubble.parentNode.removeChild(bubble); bubble = null; }
    if (owner) { owner.setAttribute("aria-expanded", "false"); owner.removeAttribute("aria-describedby"); owner = null; }
  }
  function later() { clearTimeout(timer); timer = setTimeout(close, 250); }
  function place() {
    var r = owner.getBoundingClientRect(), w = bubble.offsetWidth, h = bubble.offsetHeight;
    var vw = document.documentElement.clientWidth;
    var left = Math.max(8, Math.min(r.left, vw - w - 8)) + window.scrollX;
    var top = r.bottom + window.scrollY + 6;
    if (r.bottom + h + 12 > window.innerHeight && r.top > h + 12) top = r.top + window.scrollY - h - 6;
    bubble.style.left = left + "px";
    bubble.style.top = top + "px";
  }
  function open(term) {
    clearTimeout(timer);
    if (owner === term) return;
    close();
    var def = document.getElementById(term.getAttribute("data-def"));
    if (!def) return;
    bubble = document.createElement("div");
    bubble.className = "bulle";
    bubble.id = "bulle";
    bubble.setAttribute("role", "tooltip");
    var title = document.createElement("strong");
    title.textContent = def.getAttribute("data-terme");
    bubble.appendChild(title);
    var body = document.createElement("div");
    body.innerHTML = def.innerHTML;
    bubble.appendChild(body);
    var more = defs.getAttribute("data-more");
    if (more) {
      var a = document.createElement("a");
      a.className = "plus";
      a.href = more;
      if (/^https?:/.test(more)) { a.target = "_blank"; a.rel = "noopener"; }
      a.textContent = defs.getAttribute("data-more-label");
      a.addEventListener("click", close);
      bubble.appendChild(a);
    }
    bubble.addEventListener("pointerenter", function () { clearTimeout(timer); });
    bubble.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") later(); });
    document.body.appendChild(bubble);
    owner = term;
    term.setAttribute("aria-expanded", "true");
    term.setAttribute("aria-describedby", "bulle");
    place();
  }
  function termOf(node) { return node && node.closest ? node.closest(".terme") : null; }
  document.addEventListener("pointerover", function (e) {
    var t = termOf(e.target);
    if (t && e.pointerType === "mouse") { hovered = true; open(t); }
  });
  document.addEventListener("pointerout", function (e) {
    var t = termOf(e.target);
    if (t && e.pointerType === "mouse" && !t.contains(e.relatedTarget)) { hovered = false; later(); }
  });
  document.addEventListener("click", function (e) {
    var t = termOf(e.target);
    if (t) { if (owner === t && !hovered) close(); else open(t); return; }
    if (bubble && !bubble.contains(e.target)) close();
  });
  document.addEventListener("keydown", function (e) {
    var t = termOf(e.target);
    if (e.key === "Escape") { close(); return; }
    if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); if (owner === t) close(); else open(t); }
  });
  window.addEventListener("resize", function () { if (bubble) place(); });
})();
"""


class GuideError(Exception):
    pass


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", text.strip())


def guide_files(lang: str) -> list[Path]:
    """Fichiers du guide dans l'ordre de la page."""
    folder = GUIDE / lang
    parts = sorted(p for p in folder.glob("*.md") if PART.match(p.name))
    if not parts:
        raise GuideError(f"aucune partie NN-*.md dans {folder}")
    rigs = sorted((folder / "postes").glob("*.md"))
    annexes = [folder / name for name in ANNEXES if (folder / name).exists()]
    ordered: list[Path] = [folder / "README.md"]
    if (folder / QUICK_START).exists():
        ordered.append(folder / QUICK_START)
    for part in parts:
        if part == parts[-1]:
            ordered += annexes                 # annexes juste avant la dernière partie (le récapitulatif)
        ordered.append(part)
        if part.name.startswith("01-"):
            ordered += rigs
    if not any(p.name.startswith("01-") for p in parts):
        ordered += rigs
    return ordered


def anchor_of(path: Path, lang: str) -> str:
    rel = path.relative_to(GUIDE / lang)
    if rel.name == "README.md" and len(rel.parts) == 1:
        return "top"
    if rel.parts[0] == "postes":
        return "poste-" + rel.stem
    if not PART.match(rel.name):
        return rel.stem                        # annexe : « glossaire »
    return "p-" + rel.stem[:2]


def image_size(data: bytes, name: str) -> tuple[int, int]:
    """(largeur, hauteur) lues dans l'en-tête d'un PNG ou d'un JPEG ; tout autre contenu est refusé."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2):                  # début d'image : hauteur puis largeur
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + length
    raise GuideError(f"{name} : ni PNG ni JPEG lisible")


class Renderer:
    def __init__(self, lang: str, path: Path, anchors: dict[Path, str]) -> None:
        self.lang, self.path, self.anchors = lang, path, anchors
        self.file_anchor = anchors[path.resolve()]
        self.boxes = 0
        self.section = 0
        self.heading_ids: set[str] = set()
        self.images: list[Path] = []
        self.tab_groups = 0

    # ------------------------------------------------------------------ texte en ligne
    def link(self, target: str) -> tuple[str, bool]:
        """(adresse, externe ?). Un fichier .md du guide devient une ancre de la page ; tout autre chemin relatif
        devient une adresse du dépôt sur GitHub."""
        if re.match(r"^https?://", target):
            return target, True
        if target.startswith("#"):
            return target, False
        file_part, _, frag = target.partition("#")
        resolved = (self.path.parent / file_part).resolve()
        if resolved in self.anchors:
            anchor = self.anchors[resolved]
            return "#" + (f"{anchor}-{frag}" if frag else anchor), False
        if file_part.endswith(".md") and str(resolved).startswith(str(GUIDE.resolve())):
            raise GuideError(f"{self.path.name} : lien vers un fichier absent du guide : {target}")
        try:
            rel = resolved.relative_to(ROOT.resolve()).as_posix()
        except ValueError as exc:
            raise GuideError(f"{self.path.name} : lien hors du dépôt : {target}") from exc
        kind = "tree" if resolved.is_dir() else "blob"
        return f"{REPO_URL}/{kind}/main/{rel}" + (f"#{frag}" if frag else ""), True

    def inline(self, text: str) -> str:
        tokens: list[str] = []

        def keep(fragment: str) -> str:
            tokens.append(fragment)
            return f"\x00{len(tokens) - 1}\x00"

        text = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{esc(m.group(1))}</code>"), text)

        def link(m: re.Match[str]) -> str:
            href, external = self.link(m.group(2))
            attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
            return keep(f'<a href="{esc(href)}"{attrs}>') + m.group(1) + keep("</a>")

        text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
        text = re.sub(r"https?://[^\s<>()*]+[^\s<>().,;:!?*]",
                      lambda m: keep(f'<a href="{esc(m.group(0))}" target="_blank" rel="noopener noreferrer">'
                                     f"{esc(m.group(0))}</a>"), text)
        text = esc(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
        return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], text)

    # ------------------------------------------------------------------ blocs
    def heading(self, level: int, text: str) -> str:
        if level == 1:
            ident = self.file_anchor
            tag = "h2"
        else:
            ident = f"{self.file_anchor}-{slug(text)}"
            while ident in self.heading_ids:
                ident += "-"
            tag = f"h{min(level + 1, 4)}"
            if level == 2:
                self.section += 1
        self.heading_ids.add(ident)
        cls = ' class="partie"' if level == 1 else ""
        return f'<{tag} id="{esc(ident)}"{cls}>{self.inline(text)}</{tag}>'

    def figure(self, alt: str, rel: str) -> str:
        """Schéma SVG intégré à la page (aucune ressource externe), ou capture d'écran PNG / JPEG ; l'un et l'autre
        sont publiés à côté de la page pour les ouvrir en grand."""
        source = (self.path.parent / rel).resolve()
        if not source.is_file():
            raise GuideError(f"{self.path.name} : image absente : {rel}")
        if source.suffix != ".svg":
            return self.capture(alt, source)
        svg = source.read_text(encoding="utf-8")
        if "<script" in svg.lower() or "<foreignobject" in svg.lower() or "href=\"http" in svg.lower():
            raise GuideError(f"{rel} : un schéma ne contient ni script, ni objet étranger, ni lien externe")
        svg = re.sub(r"^<\?xml[^>]*>\s*", "", svg.strip())
        svg = svg.replace("<svg ", '<svg class="schema-svg" ', 1)
        self.images.append(source)
        published = source.relative_to((GUIDE / self.lang).resolve()).as_posix()
        return (f'<figure class="schema">{svg}<figcaption>{esc(alt)} · '
                f'<a href="{esc(published)}" target="_blank" rel="noopener">{esc(UI[self.lang]["enlarge"])}</a>'
                "</figcaption></figure>")

    def capture(self, alt: str, source: Path) -> str:
        """Capture d'écran : image publiée à côté de la page, dimensions écrites (la page ne saute pas au chargement,
        la hauteur donnée à l'iframe du site reste juste), toucher = l'ouvrir en grand."""
        data = source.read_bytes()
        rel = source.relative_to(GUIDE.resolve()).as_posix()          # captures/<nom>
        if source.parent != (GUIDE / CAPTURES).resolve():
            raise GuideError(f"{self.path.name} : une capture d'écran se place dans User-Guide/{CAPTURES}/")
        if len(data) > CAPTURE_MAX_BYTES:
            raise GuideError(f"{rel} : {len(data) // 1000} ko, {CAPTURE_MAX_BYTES // 1000} ko au plus "
                             "(réduire la largeur à 1400 px, ou JPEG pour une photo)")
        width, height = image_size(data, rel)
        self.images.append(source)
        cls = "capture portrait" if height > width else "capture"
        src = rel if self.lang == "fr" else f"../{rel}"         # page française à la racine de guide/
        return (f'<figure class="{cls}"><a href="{esc(src)}" target="_blank" rel="noopener">'
                f'<img src="{esc(src)}" alt="{esc(alt)}" width="{width}" height="{height}"></a>'
                f'<figcaption>{esc(alt)}</figcaption></figure>')

    def table(self, rows: list[str]) -> str:
        def cells(row: str) -> list[str]:
            return [c.strip() for c in row.strip().strip("|").split("|")]

        head = cells(rows[0])
        out = ['<div class="table"><table><thead><tr>' + "".join(f"<th>{self.inline(c)}</th>" for c in head)
               + "</tr></thead><tbody>"]
        for row in rows[2:]:
            out.append("<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in cells(row)) + "</tr>")
        return "".join(out) + "</tbody></table></div>"

    def block_end(self, lines: list[str], i: int, closing: str, what: str) -> int:
        """Fin du bloc ouvert à la ligne i ; un bloc du même genre ne s'imbrique pas (un accordéon dans un onglet,
        oui)."""
        j = i + 1
        while j < len(lines) and lines[j].strip() != closing:
            if lines[j].strip() == lines[i].strip():
                raise GuideError(f"{self.path.name} : {what} dans un autre {what} (non permis)")
            j += 1
        if j >= len(lines):
            raise GuideError(f"{self.path.name} : {what} non fermé ({closing} manquant)")
        return j

    def tabs(self, lines: list[str]) -> str:
        """Onglets par système : un `#### Nom` ouvre chaque onglet ; rien avant le premier."""
        first = next((k for k, l in enumerate(lines) if l.strip()), None)
        if first is None or not lines[first].startswith("#### "):
            raise GuideError(f"{self.path.name} : un bloc d'onglets commence par « #### Nom de l'onglet »")
        panels: list[tuple[str, list[str]]] = []
        for line in lines[first:]:
            if line.startswith("#### "):
                panels.append((line[5:].strip(), [line]))
            else:
                panels[-1][1].append(line)
        if len(panels) < 2:
            raise GuideError(f"{self.path.name} : un bloc d'onglets en a au moins deux")
        keys = [slug(name) for name, _ in panels]
        if len(set(keys)) != len(keys):
            raise GuideError(f"{self.path.name} : deux onglets du même nom dans un bloc")
        self.tab_groups += 1
        base = f"{self.file_anchor}-o{self.tab_groups}"
        bar = [f'<div class="onglets-barre" role="tablist" aria-label="{esc(UI[self.lang]["tabs_label"])}" hidden>']
        body = []
        for (name, content), key in zip(panels, keys):
            ident = f"{base}-{key}"
            bar.append(f'<button type="button" role="tab" id="{ident}-b" aria-controls="{ident}" '
                       f'aria-selected="false" data-os="{esc(key)}">{esc(name)}</button>')
            inner = self.render(content).replace("<h4 ", '<h4 class="onglet-titre" ', 1)
            body.append(f'<div class="onglet" role="tabpanel" id="{ident}" aria-labelledby="{ident}-b">{inner}</div>')
        return f'<div class="onglets">{"".join(bar)}</div>{"".join(body)}</div>'

    def details(self, lines: list[str]) -> str:
        """Accordéon : `<summary>Titre</summary>` d'abord, puis le contenu."""
        first = next((k for k, l in enumerate(lines) if l.strip()), None)
        match = re.match(r"^<summary>(.+)</summary>$", lines[first].strip()) if first is not None else None
        if not match:
            raise GuideError(f"{self.path.name} : <details> commence par <summary>Titre</summary>")
        return (f"<details><summary>{self.inline(match.group(1).strip())}</summary>"
                f"{self.render(lines[first + 1:])}</details>")

    def render(self, lines: list[str]) -> str:
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            if stripped == TABS_OPEN:
                j = self.block_end(lines, i, TABS_CLOSE, "bloc d'onglets")
                out.append(self.tabs(lines[i + 1:j]))
                i = j + 1
                continue
            if stripped == "<details>":
                j = self.block_end(lines, i, "</details>", "accordéon")
                out.append(self.details(lines[i + 1:j]))
                i = j + 1
                continue
            if stripped in (TABS_CLOSE, "</details>") or stripped.startswith("<summary>"):
                raise GuideError(f"{self.path.name} : {stripped} sans son ouverture")
            if stripped.startswith("```"):
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith("```"):
                    j += 1
                if j >= len(lines):
                    raise GuideError(f"{self.path.name} : bloc de code non fermé")
                out.append("<pre><code>" + esc("\n".join(lines[i + 1:j])) + "</code></pre>")
                i = j + 1
                continue
            match = re.match(r"^(#{1,4})\s+(.*)$", line)
            if match:
                out.append(self.heading(len(match.group(1)), match.group(2).strip()))
                i += 1
                continue
            image = IMAGE.match(stripped)
            if image:
                out.append(self.figure(image.group(1), image.group(2)))
                i += 1
                continue
            if stripped.startswith("|"):
                j = i
                while j < len(lines) and lines[j].strip().startswith("|"):
                    j += 1
                rows = lines[i:j]
                if len(rows) < 2 or not re.match(r"^\|[\s:|-]+\|$", rows[1].strip()):
                    raise GuideError(f"{self.path.name} : tableau sans ligne de séparation : {rows[0][:40]}")
                out.append(self.table(rows))
                i = j
                continue
            if stripped.startswith(">"):
                j = i
                quoted = []
                while j < len(lines) and lines[j].strip().startswith(">"):
                    quoted.append(re.sub(r"^\s*>\s?", "", lines[j]))
                    j += 1
                danger = " danger" if quoted and quoted[0].startswith(UI[self.lang]["danger"]) else ""
                out.append(f'<div class="note{danger}">' + self.render(quoted) + "</div>")
                i = j
                continue
            if re.match(r"^(-|\d+\.)\s", line):
                i = self.list_block(lines, i, out)
                continue
            j = i
            para = []
            while j < len(lines) and lines[j].strip() and not re.match(
                    r"^(#{1,4}\s|```|\||>|-\s|\d+\.\s|<!--|</?details>|<summary>)", lines[j].strip()):
                para.append(lines[j].strip())
                j += 1
            if not para:
                raise GuideError(f"{self.path.name} : ligne non reconnue : {line[:60]}")
            out.append("<p>" + self.inline(" ".join(para)) + "</p>")
            i = j
        return "\n".join(out)

    def list_block(self, lines: list[str], i: int, out: list[str]) -> int:
        ordered = bool(re.match(r"^\d+\.\s", lines[i]))
        items: list[list[str]] = []
        while i < len(lines):
            line = lines[i]
            match = re.match(r"^(-|\d+\.)\s+(.*)$", line)
            if match and bool(re.match(r"^\d", match.group(1))) == ordered:
                items.append([match.group(2)])
                i += 1
                continue
            if line.strip() == "" and i + 1 < len(lines) and lines[i + 1].startswith("  "):
                items[-1].append("")
                i += 1
                continue
            if line.startswith("  ") and items:
                items[-1].append(line)
                i += 1
                continue
            break
        boxes = all(re.match(r"^\[[ xX]\]\s", item[0]) for item in items)
        if boxes:
            out.append('<ul class="cases">')
            for item in items:
                self.boxes += 1
                ident = f"c{self.section}-{self.boxes}"
                text = re.sub(r"^\[[ xX]\]\s+", "", item[0])
                out.append(f'<li><label><input type="checkbox" id="{ident}"><span>{self.inline(text)}</span>'
                           "</label></li>")
            out.append("</ul>")
            return i
        tag = "ol" if ordered else "ul"
        out.append(f"<{tag}>")
        for item in items:
            first, rest = item[0], item[1:]
            indent = min((len(r) - len(r.lstrip()) for r in rest if r.strip()), default=0)
            body = [first] + [r[indent:] for r in rest]
            if len(body) == 1 or all(not r.strip() or not re.match(r"^(```|-\s|\d+\.\s|\|)", r.strip())
                                     for r in body[1:]) and "" not in body:
                out.append("<li>" + self.inline(" ".join(r.strip() for r in body)) + "</li>")
            else:
                out.append("<li>" + self.render(body) + "</li>")
        out.append(f"</{tag}>")
        return i


class Bubbles:
    """Termes du glossaire à infobulle d'une langue, et pose des marques dans le HTML d'une partie."""

    def __init__(self, lang: str, anchors: dict[Path, str]) -> None:
        self.lang = lang
        self.defs: dict[str, tuple[str, str]] = {}          # id -> (terme, définition HTML)
        self.names: dict[str, str] = {}                     # nom (minuscules) -> id
        self.used: list[str] = []
        glossary = GUIDE / lang / GLOSSARY
        self.more = ("#" + anchors[glossary.resolve()]) if glossary.resolve() in anchors else ""
        wanted = BUBBLES.get(lang, ())
        if not wanted:
            self.pattern = None
            return
        renderer = Renderer(lang, glossary, {**anchors, glossary.resolve(): "glossaire"})
        found: dict[str, tuple[str, list[str], str]] = {}
        for line in glossary.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
            if len(cells) != 2:
                continue
            names = [n.replace("`", "").strip() for n in re.findall(r"\*\*(.+?)\*\*", cells[0])]
            for name in names:
                found[name] = (names[0], names, cells[1])
        for name in wanted:
            if name not in found:
                raise GuideError(f"infobulle : « {name} » absent de {lang}/{GLOSSARY} (terme en gras)")
            first, _names, definition = found[name]
            ident = "def-" + slug(first)
            self.defs.setdefault(ident, (first, renderer.inline(definition)))
            self.names[name.lower()] = ident
        alternatives = []
        for name in sorted(wanted, key=len, reverse=True):
            word = re.escape(name).replace("\\ ", "\\s+")
            if name.upper() == name:                      # sigle : casse exacte, pas de pluriel
                alternatives.append(word)
            else:
                alternatives.append(f"(?i:{word})(?:s|x)?")
        self.pattern = re.compile(r"(?<![\w-])(" + "|".join(alternatives) + r")(?![\w-])")

    def ident(self, found: str) -> str | None:
        key = re.sub(r"\s+", " ", found).lower()
        if key in self.names:
            return self.names[key]
        return self.names.get(key[:-1]) if key[-1:] in ("s", "x") else None

    def apply(self, part_html: str) -> str:
        """Marque la première occurrence de chaque terme par section ; rien dans les balises à éviter."""
        if self.pattern is None:
            return part_html
        out: list[str] = []
        skip = 0
        seen: set[str] = set()
        for piece in re.split(r"(<[^>]+>)", part_html):
            if piece.startswith("<"):
                tag = re.match(r"</?([a-z0-9]+)", piece)
                name = tag.group(1) if tag else ""
                if name in ("h2", "h3") and not piece.startswith("</"):   # partie (#) ou section (##)
                    seen = set()
                if name in NO_BUBBLE_TAGS:
                    skip += -1 if piece.startswith("</") else 1
                out.append(piece)
                continue
            if skip > 0 or not piece:
                out.append(piece)
                continue

            def mark(m: re.Match[str]) -> str:
                ident = self.ident(m.group(1))
                if ident is None or ident in seen:
                    return m.group(0)
                seen.add(ident)
                if ident not in self.used:
                    self.used.append(ident)
                return (f'<span class="terme" tabindex="0" role="button" aria-expanded="false" '
                        f'data-def="{ident}">{m.group(0)}</span>')

            out.append(self.pattern.sub(mark, piece))
        return "".join(out)

    def footer(self, ui: dict[str, str]) -> str:
        """Définitions utilisées, cachées, recopiées dans la bulle par le script."""
        if not self.used:
            return ""
        items = "".join(f'<div id="{i}" data-terme="{esc(self.defs[i][0])}">{self.defs[i][1]}</div>'
                        for i in self.used)
        more = f' data-more="{esc(self.more)}" data-more-label="{esc(ui["glossary_more"])}"' if self.more else ""
        return f'<div id="defs" hidden{more}>{items}</div>'


def language_bar(lang: str, ui: dict[str, str]) -> str:
    """Choix de la langue : liens relatifs entre guide/ (français) et guide/<langue>/ (les autres)."""
    items = []
    for other in LANGS:
        name = (f'<svg viewBox="0 0 60 40" aria-hidden="true">{FLAGS[other]}</svg>'
                f'<span>{esc(LANG_NAMES[other])}</span>')
        if other == lang:
            items.append(f'<strong aria-current="page" lang="{other}">{name}</strong>')
            continue
        href = ("" if lang == "fr" else "../") + ("" if other == "fr" else f"{other}/")
        items.append(f'<a href="{href or "./"}" lang="{other}" hreflang="{other}">{name}</a>')
    return f'<nav class="langues" aria-label="{esc(ui["lang_label"])}">{"".join(items)}</nav>'


def render_page(lang: str, images: list[Path] | None = None) -> str:
    """Page complète ; `images` reçoit les schémas SVG utilisés (à publier à côté de la page)."""
    files = guide_files(lang)
    anchors = {p.resolve(): anchor_of(p, lang) for p in files}
    ui = UI[lang]
    body: list[str] = []
    title = ""
    total_boxes = 0
    bubbles = Bubbles(lang, anchors)
    for path in files:
        with_bubbles = path.name != GLOSSARY
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or not lines[0].startswith("# "):
            raise GuideError(f"{path.name} : la première ligne doit être le titre (# …)")
        renderer = Renderer(lang, path, anchors)
        if anchors[path.resolve()] == "top":
            title = lines[0][2:].strip()
            body.append(language_bar(lang, ui))
            body.append(f'<h1 id="top">{esc(title)}</h1>')
            # Nouvel onglet : l'iframe du site (sandbox sans allow-downloads) ne peut pas télécharger elle-même.
            body.append(f'<p class="telecharger"><a href="{esc(PDF_NAME.format(lang=lang))}" target="_blank" '
                        f'rel="noopener">{esc(ui["pdf"])}</a><span>{esc(ui["pdf_hint"])}</span></p>')
            intro = renderer.render(lines[1:])
            body.append(bubbles.apply(intro) if with_bubbles else intro)
            if images is not None:
                images += renderer.images
            continue
        html_part = renderer.render(lines)
        if with_bubbles:
            html_part = bubbles.apply(html_part)
        if images is not None:
            images += renderer.images
        if renderer.boxes:
            total_boxes += renderer.boxes
            tools = (f'<div class="outils"><strong id="progress" data-model="{esc(ui["progress"])}"></strong>'
                     f'<button type="button" id="print">{esc(ui["print"])}</button>'
                     f'<button type="button" id="reset">{esc(ui["reset"])}</button>'
                     '<div class="barre"><span id="bar"></span></div>'
                     f'<p class="memo" id="memo" data-saved="{esc(ui["saved"])}" data-unsaved="{esc(ui["unsaved"])}">'
                     "</p></div>")
            first_heading_end = html_part.index("</h2>") + len("</h2>")
            html_part = html_part[:first_heading_end] + tools + html_part[first_heading_end:]
        body.append(f'<section id="s-{anchors[path.resolve()]}">{html_part}'
                    f'<p class="haut"><a href="#top">{esc(ui["top"])}</a></p></section>')
    if total_boxes == 0:
        raise GuideError("aucune case à cocher : le récapitulatif manque")
    source = f"{REPO_URL}/tree/main/User-Guide/{lang}"
    out = ["<!doctype html>",
           "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
           "<!-- Copyright (C) 2026 RF-DIY.COM -->",
           "<!-- Fabriqué par scripts/build_user_guide.py à partir de User-Guide/ : ne pas modifier à la main. -->",
           f'<html lang="{lang}">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{esc(title)}</title>", f"<style>{CSS.strip()}</style>", "</head>", "<body>", "<main>",
           *body,
           f'<footer>{esc(ui["footer"])} · <a href="{source}" target="_blank" rel="noopener noreferrer">'
           f'{esc(ui["source"])}</a> · <a href="https://www.rf-diy.com" target="_blank" rel="noopener noreferrer">'
           "rf-diy.com</a></footer>",
           "</main>", bubbles.footer(ui), f"<script>{(SCRIPT % {'lang': lang}).strip()}</script>",
           f"<script>{BUBBLES_JS.strip()}</script>", f"<script>{TABS_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def build() -> dict[Path, str | bytes]:
    """{fichier publié: contenu} ; texte pour la page et les schémas, octets pour les captures d'écran."""
    pages: dict[Path, str | bytes] = {}
    for lang in LANGS:
        sub = SITE if lang == "fr" else SITE / lang
        images: list[Path] = []
        pages[sub / "index.html"] = render_page(lang, images)
        for image in images:
            data = image.read_bytes()
            if image.suffix == ".svg":
                pages[sub / image.relative_to((GUIDE / lang).resolve())] = data.decode("utf-8")
            else:                                              # capture commune : publiée une fois
                pages[SITE / CAPTURES / image.name] = data
    return pages


def main() -> int:
    try:
        pages = build()
    except GuideError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        print(f"Écrit : {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
