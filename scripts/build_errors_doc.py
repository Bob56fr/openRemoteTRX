# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique les pages publiques du catalogue d'erreurs (GitHub Pages, thème sombre, iframe du site rf-diy.com).

Source : `trxstation/errors/catalog.json` (fabriqué par scripts/build_errors.py depuis catalog.yaml et les
catalogues des modules livrés dans le dépôt). Aucune dépendance hors stdlib.

Résultat (codes STABLES : une seule version des pages, sans numéro de version de la station, qui ne changent qu'avec
le catalogue ; un code abandonné garde sa page) :
  - `docs/site/erreurs/index.html` : liste de tous les codes par domaine, avec recherche ;
  - `docs/site/erreurs/<CODE>/index.html` : une page par code, en français, anglais, allemand et espagnol (lot T8).
Le champ `doc` de chaque code doit être l'adresse de sa page (`doc_url`) : sinon la fabrication s'arrête.
Usage : python scripts/build_errors_doc.py   (après python scripts/build_errors.py, à chaque changement du catalogue).
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_console_doc as base  # noqa: E402  (même style, même ajustement de hauteur dans l'iframe)

CATALOG_JSON = ROOT / "trxstation" / "errors" / "catalog.json"
SITE = ROOT / "docs" / "site"
FOLDER = "erreurs"
PAGES_URL = "https://bob56fr.github.io/openRemoteTRX/erreurs/"
CODE_RE = re.compile(r"^[A-Z]{3}-\d{4}$")
CITED_RE = re.compile(r"\b[A-Z]{3}-\d{4}\b")

# Domaines du cahier (§ 7) : premier chiffre d'un code ORT. Les autres préfixes ont leur propre domaine.
LANGS = ("fr", "en", "de", "es")
LANG_NAMES = {"fr": "Français", "en": "English", "de": "Deutsch", "es": "Español"}
DOMAINS = {
    "1": ("Système", "System", "System", "Sistema"),
    "2": ("CAT, Hamlib, rigctld, port série", "CAT, Hamlib, rigctld, serial port", "CAT, Hamlib, rigctld, serielle Schnittstelle",
          "CAT, Hamlib, rigctld, puerto serie"),
    "3": ("Audio", "Audio", "Audio", "Audio"),
    "4": ("Réseau, accès, clients", "Network, access, clients", "Netzwerk, Zugang, Clients", "Red, acceso, clientes"),
    "5": ("PTT et sécurité d'émission", "PTT and transmit safety", "PTT und Sendesicherheit", "PTT y seguridad de transmisión"),
    "6": ("Modules", "Modules", "Module", "Módulos"),
    "7": ("Monitor inter-stations", "Inter-station monitor", "Überwachung zwischen Stationen", "Monitorización entre estaciones"),
    "8": ("Superviseur et processus", "Supervisor and processes", "Supervisor und Prozesse", "Supervisor y procesos"),
    "9": ("Configuration et installation", "Configuration and installation", "Konfiguration und Installation",
          "Configuración e instalación"),
}
GRAVITES = {"info": ("info", "info", "Info", "info"), "avertissement": ("avertissement", "warning", "Warnung", "aviso"),
            "erreur": ("erreur", "error", "Fehler", "error"), "critique": ("critique", "critical", "kritisch", "crítico")}
TXT = {
    "fr": {"message": "Message", "causes": "Causes possibles", "preco": "Que faire", "auto": "Ce que fait la station",
           "ntfy": "Alerte ntfy", "ntfy_oui": "oui par défaut, priorité {p}", "ntfy_non": "non par défaut",
           "machine": "Codes du protocole", "depuis": "Depuis la version", "prevu": "Code réservé : pas encore produit par la station.",
           "deprecated": "Code abandonné, gardé pour les anciens journaux. Remplacé par {r}.",
           "tous": "Tous les codes", "aucune": "rien d'automatique"},
    "en": {"message": "Message", "causes": "Possible causes", "preco": "What to do", "auto": "What the station does",
           "ntfy": "ntfy alert", "ntfy_oui": "yes by default, priority {p}", "ntfy_non": "no by default",
           "machine": "Protocol codes", "depuis": "Since version", "prevu": "Reserved code: not produced by the station yet.",
           "deprecated": "Retired code, kept for old logs. Replaced by {r}.",
           "tous": "All codes", "aucune": "nothing automatic"},
    "de": {"message": "Meldung", "causes": "Mögliche Ursachen", "preco": "Was zu tun ist", "auto": "Was die Station tut",
           "ntfy": "ntfy-Alarm", "ntfy_oui": "standardmäßig ja, Priorität {p}", "ntfy_non": "standardmäßig nein",
           "machine": "Protokollcodes", "depuis": "Seit Version", "prevu": "Reservierter Code: wird von der Station noch nicht erzeugt.",
           "deprecated": "Aufgegebener Code, für alte Protokolle beibehalten. Ersetzt durch {r}.",
           "tous": "Alle Codes", "aucune": "nichts Automatisches"},
    "es": {"message": "Mensaje", "causes": "Causas posibles", "preco": "Qué hacer", "auto": "Qué hace la estación",
           "ntfy": "Alerta ntfy", "ntfy_oui": "sí por defecto, prioridad {p}", "ntfy_non": "no por defecto",
           "machine": "Códigos del protocolo", "depuis": "Desde la versión", "prevu": "Código reservado: la estación aún no lo produce.",
           "deprecated": "Código abandonado, conservado para los registros antiguos. Sustituido por {r}.",
           "tous": "Todos los códigos", "aucune": "nada automático"},
}
INTRO = {
    "fr": "Chaque problème relevé par la station porte un code stable (par exemple <code>ORT-2104</code>), visible dans les "
          "journaux, les alertes ntfy et TRX Console. Tapez le code ou un mot pour retrouver sa page : causes, que faire, "
          "ce que fait la station.",
    "en": "Every problem detected by the station carries a stable code (for example <code>ORT-2104</code>), shown in logs, "
          "ntfy alerts and TRX Console. Type the code or a word to find its page: causes, what to do, what the station does.",
    "de": "Jedes von der Station erkannte Problem trägt einen festen Code (zum Beispiel <code>ORT-2104</code>), sichtbar in "
          "den Protokollen, den ntfy-Alarmen und in TRX Console. Geben Sie den Code oder ein Wort ein, um seine Seite zu "
          "finden: Ursachen, was zu tun ist, was die Station tut.",
    "es": "Cada problema detectado por la estación lleva un código estable (por ejemplo <code>ORT-2104</code>), visible en "
          "los registros, las alertas ntfy y TRX Console. Escribe el código o una palabra para encontrar su página: "
          "causas, qué hacer, qué hace la estación.",
}
TITLE = {"fr": "Codes d'erreur", "en": "Error codes", "de": "Fehlercodes", "es": "Códigos de error"}
EXTRA_CSS = """
[hidden]{display:none !important}
.g{display:inline-block;border-radius:1rem;padding:0 .55rem;font-size:.8rem;font-weight:600;vertical-align:middle}
.g-info{background:#1c2f45;color:#9cc8f2}.g-avertissement{background:#3d3418;color:#f2d06b}
.g-erreur{background:#45261c;color:#ffb08a}.g-critique{background:#5a1c1a;color:#ffb4ad}
.code{font-family:ui-monospace,Consolas,monospace;font-weight:700;white-space:nowrap}
.liste{list-style:none;margin:.3rem 0 1rem;padding:0}
.liste li{display:grid;grid-template-columns:6.2rem 1fr auto;gap:.6rem;align-items:baseline;padding:.3rem .6rem;
  border-bottom:1px solid var(--ligne)}
.liste a{text-decoration:none}.liste .t{min-width:0}
.vieux{opacity:.55;text-decoration:line-through}
.recherche{width:100%;padding:.55rem .8rem;border-radius:.5rem;border:1px solid var(--ligne);background:var(--carte);
  color:var(--texte);font:inherit;margin:.6rem 0}
.choix button{background:var(--carte);color:var(--texte);border:1px solid var(--ligne);border-radius:2rem;
  padding:.2rem .9rem;font:inherit;cursor:pointer}.choix button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
.lt{display:none}body.l-fr .lt[lang=fr],body.l-en .lt[lang=en],body.l-de .lt[lang=de],body.l-es .lt[lang=es]{display:inline}
section.langue{background:var(--carte);border:1px solid var(--ligne);border-radius:.6rem;padding:.4rem 1rem .8rem;margin:1rem 0}
.note{border-left:.3rem solid var(--emission);padding:.3rem .8rem;background:var(--carte);border-radius:.4rem}
@media (max-width:30rem){.liste li{grid-template-columns:5.6rem 1fr}.liste li .g{display:none}}
"""
FILTER_JS = """
(function () {
  var box = document.getElementById("q"), items = document.querySelectorAll(".liste li"), heads = document.querySelectorAll("h2[data-d]");
  function norm(s) { return s.toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, ""); }
  function filter() {
    var q = norm(box.value.trim()), seen = {};
    items.forEach(function (li) { var ok = !q || norm(li.textContent).indexOf(q) >= 0; li.hidden = !ok; if (ok) seen[li.dataset.d] = 1; });
    heads.forEach(function (h) { var hide = !seen[h.dataset.d]; h.hidden = hide; h.nextElementSibling.hidden = hide; });
  }
  box.addEventListener("input", filter);
  var m = /[?&]code=([A-Za-z]{3}-\\d{4})/.exec(location.search);
  if (m) { box.value = m[1].toUpperCase(); filter(); }
  function lang(l) {
    if (["fr", "en", "de", "es"].indexOf(l) < 0) l = "en";
    document.body.className = "l-" + l;
    document.querySelectorAll(".choix button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.l === l)); });
    try { localStorage.setItem("trx-erreurs-langue", l); } catch (e) {}
  }
  document.querySelectorAll(".choix button").forEach(function (b) { b.addEventListener("click", function () { lang(b.dataset.l); }); });
  var saved = null; try { saved = localStorage.getItem("trx-erreurs-langue"); } catch (e) {}
  lang(saved || (navigator.language || "fr").slice(0, 2).toLowerCase());
})();
"""


class DocError(Exception):
    pass


def doc_url(code: str) -> str:
    return f"{PAGES_URL}{code}/"


def load_catalog(path: Path = CATALOG_JSON) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def domain_of(code: str) -> str:
    prefix, num = code.split("-")
    return num[0] if prefix == "ORT" else prefix


def domain_names(key: str, prefixes: dict) -> tuple[str, ...]:
    """Nom du domaine dans chaque langue de LANGS."""
    if key in DOMAINS:
        return DOMAINS[key]
    entry = prefixes.get(key, {})
    names = [entry.get("nom", key) if lang == "fr" else entry.get(lang, entry.get("en", {})).get("nom", key) for lang in LANGS]
    return tuple(n[:1].upper() + n[1:] for n in names)


def _texts(entry: dict, lang: str) -> dict:
    """Champs traduits d'une entrée dans une langue (bloc `en`, `de`, `es` ; repli sur l'anglais)."""
    return entry if lang == "fr" else {**entry, **entry.get(lang, entry["en"])}


def _langs(values: dict, esc=html.escape) -> str:
    """Un texte par langue, un seul visible (classe l-<langue> du corps)."""
    return "".join(f'<span class="lt" lang="{lang}">{esc(values[lang])}</span>' for lang in LANGS)


def check(data: dict) -> None:
    problems = []
    codes = data["codes"]
    for code, entry in codes.items():
        if not CODE_RE.match(code):
            problems.append(f"{code} : code mal formé")
            continue
        if entry.get("doc") != doc_url(code):
            problems.append(f"{code} : doc = {entry.get('doc')!r}, attendu {doc_url(code)!r}")
        if entry.get("deprecated"):
            cited = CITED_RE.findall(entry.get("remplace_par") or "")
            if not cited:
                problems.append(f"{code} : abandonné, `remplace_par` ne cite aucun code")
            problems += [f"{code} : remplace_par cite {c}, absent du catalogue" for c in cited if c not in codes]
    if problems:
        raise DocError("\n".join(problems))


def _message(text: str) -> str:
    """Message échappé, variables {nom} en code."""
    return re.sub(r"\{([a-z][a-z0-9_]*)\}", r"<code>{\1}</code>", html.escape(text))


def _badge(gravite: str, lang: str) -> str:
    label = GRAVITES[gravite][LANGS.index(lang)]
    return f'<span class="g g-{gravite}">{html.escape(label)}</span>'


def _head(title: str, lang: str = "fr") -> list[str]:
    return ["<!doctype html>", "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->", "<!-- Copyright (C) 2026 RF-DIY.COM -->",
            "<!-- Fabriqué par scripts/build_errors_doc.py depuis trxstation/errors/catalog.json : ne pas modifier à la main. -->",
            f'<html lang="{lang}">', "<head>", '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(title)}</title>",
            f"<style>{base.CSS.strip()}{EXTRA_CSS.strip()}</style>", "</head>"]


def _footer(up: str) -> list[str]:
    return ["<footer>",
            f'<p><a href="{up}">Tous les codes / All codes</a> · '
            f'<a href="{up}../console/">TRX Console</a> · <a href="{up}../station-toml/">station.toml</a> · '
            f'<a href="{base.REPO_URL}" target="_blank" rel="noopener noreferrer">code source</a> · '
            f'<a href="{base.SITE_URL}" target="_blank" rel="noopener noreferrer">rf-diy.com</a></p>',
            "</footer>"]


def _section(code: str, entry: dict, lang: str, codes: dict) -> list[str]:
    t = TXT[lang]
    src = _texts(entry, lang)
    esc = html.escape
    out = [f'<section class="langue" lang="{lang}" id="{lang}">',
           f"<h2>{esc(src['titre'])} {_badge(entry['gravite'], lang)}</h2>"]
    if entry.get("deprecated"):
        r = CITED_RE.sub(lambda m: f'<a href="../{m[0]}/">{m[0]}</a>', esc(entry["remplace_par"]))
        out.append('<p class="note">' + esc(t["deprecated"]).replace("{r}", r) + "</p>")
    if entry.get("prevu"):
        out.append(f'<p class="note">{esc(t["prevu"])}</p>')
    action = entry["action_auto"]
    rows = [f"<dt>{t['message']}</dt><dd>{_message(src['message'])}</dd>",
            f"<dt>{t['causes']}</dt><dd><ul>" + "".join(f"<li>{esc(c)}</li>" for c in src["causes"]) + "</ul></dd>",
            f"<dt>{t['preco']}</dt><dd>{esc(src['preconisation'])}</dd>",
            f"<dt>{t['auto']}</dt><dd>" + (esc(t["aucune"]) if action == "aucune" else f"<code>{esc(action)}</code>") + "</dd>",
            f"<dt>{t['ntfy']}</dt><dd>" + (esc(t["ntfy_oui"].format(p=entry["priorite_ntfy"])) if entry["ntfy_defaut"]
                                           else esc(t["ntfy_non"])) + "</dd>"]
    if entry.get("codes_machine"):
        rows.append(f"<dt>{t['machine']}</dt><dd>" + ", ".join(f"<code>{esc(c)}</code>" for c in entry["codes_machine"]) + "</dd>")
    rows.append(f"<dt>{t['depuis']}</dt><dd>{esc(entry['depuis_version'])}</dd>")
    out += [f"<dl>{''.join(rows)}</dl>", "</section>"]
    return out


def render_code(code: str, entry: dict, codes: dict) -> str:
    esc = html.escape
    out = _head(f"{code} : {entry['titre']}") + ["<body>", "<main>",
           f'<h1><span class="code">{esc(code)}</span></h1>',
           '<p class="version"><a href="../">← Tous les codes</a> · '
           + " · ".join(f'<a href="#{lang}">{LANG_NAMES[lang]} ↓</a>' for lang in LANGS[1:]) + "</p>"]
    for lang in LANGS:
        out += _section(code, entry, lang, codes)
    out += _footer("../") + ["</main>", f"<script>{base.RESIZE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def render_index(data: dict) -> str:
    esc = html.escape
    codes, prefixes = data["codes"], data.get("prefixes", {})
    groups: dict[str, list[str]] = {}
    for code in sorted(codes, key=lambda c: (c.split("-")[0] != "ORT", c)):
        groups.setdefault(domain_of(code), []).append(code)
    names = lambda k: dict(zip(LANGS, domain_names(k, prefixes)))  # noqa: E731
    out = _head("Codes d'erreur de TRX distant / Error codes") + ['<body class="l-fr">', "<main>",
           f"<h1>{_langs(TITLE)}</h1>",
           f'<p class="version">{len(codes)} codes · <span class="choix">'
           + " ".join(f'<button type="button" data-l="{lang}">{LANG_NAMES[lang]}</button>' for lang in LANGS) + "</span></p>",
           '<div class="lecture"><p>' + _langs(INTRO, esc=lambda s: s) + "</p></div>",
           '<input id="q" class="recherche" type="search" placeholder="ORT-2104, rigctld, TOT…" aria-label="Rechercher / Search">',
           '<ul class="sommaire">' + "".join(f'<li><a href="#d-{esc(k)}">{_langs(names(k))}</a></li>' for k in groups) + "</ul>"]
    for key, items in groups.items():
        out.append(f'<h2 id="d-{esc(key)}" data-d="{esc(key)}">{_langs(names(key))}</h2>')
        lines = []
        for code in items:
            e = codes[code]
            cls = ' class="vieux"' if e.get("deprecated") else ""
            lines.append(f'<li data-d="{esc(key)}"><a class="code" href="{code}/"{cls}>{esc(code)}</a>'
                         f'<span class="t">{_langs({lang: _texts(e, lang)["titre"] for lang in LANGS})}</span>'
                         '<span>' + "".join(f'<span class="lt" lang="{lang}">{_badge(e["gravite"], lang)}</span>' for lang in LANGS)
                         + "</span></li>")
        out.append('<ul class="liste">' + "".join(lines) + "</ul>")
    out += _footer("") + ["</main>", f"<script>{FILTER_JS.strip()}</script>",
                                   f"<script>{base.RESIZE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def build(site: Path = SITE, data: dict | None = None) -> dict[Path, str]:
    data = data if data is not None else load_catalog()
    check(data)
    pages = {site / FOLDER / "index.html": render_index(data)}
    for code, entry in data["codes"].items():
        pages[site / FOLDER / code / "index.html"] = render_code(code, entry, data["codes"])
    return pages


def stale_pages(site: Path = SITE) -> list[Path]:
    """Pages à écrire, à retirer (code disparu du catalogue : impossible en principe) ou périmées."""
    pages = build(site)
    out = [p for p, text in pages.items()
           if not p.exists() or p.read_bytes().replace(b"\r\n", b"\n") != text.encode("utf-8")]
    folder = site / FOLDER
    if folder.is_dir():
        out += [d / "index.html" for d in folder.iterdir() if d.is_dir() and d / "index.html" not in pages]
    return out


def main() -> int:
    try:
        pages = build()
    except DocError as exc:
        print("Pages des codes d'erreur NON fabriquées :\n" + str(exc), file=sys.stderr)
        return 1
    written = 0
    for path, text in pages.items():
        data = text.encode("utf-8")
        if path.exists() and path.read_bytes().replace(b"\r\n", b"\n") == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written += 1
    print(f"{written} page(s) écrite(s) sur {len(pages)} dans {(SITE / FOLDER).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
