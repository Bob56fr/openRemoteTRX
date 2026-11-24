# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique la notice des réglages de station.toml (page HTML, thème sombre) publiée par GitHub Pages et affichée dans
une iframe du site rf-diy.com, plus sa version Markdown pour le dépôt.

La LISTE des réglages et leurs valeurs par défaut viennent du code (`trxstation.config`) ; les explications de
`docs/station-toml/contenu.toml` (français, référence) et de ses traductions `contenu.en.toml`, `contenu.de.toml`,
`contenu.es.toml` (mêmes sections, mêmes réglages, mêmes champs). Un réglage sans explication, ou une explication sans
réglage, dans N'IMPORTE QUELLE langue, arrête la fabrication (et les tests) : la notice suit le code à chaque livraison.

Résultat :
  - `docs/site/station-toml/index.html` (français) et `…/en/`, `…/de/`, `…/es/` : dernière version (adresse fixe, celle
    de l'iframe du site), avec un choix de langue par drapeaux (les mêmes que le guide de l'opérateur) ;
  - `docs/site/station-toml/<version>/[<langue>/]index.html` : une copie par version, gardée ;
  - `docs/station-toml.md` : la notice française en Markdown (lecture sur GitHub).
Usage : python scripts/build_station_toml_doc.py   (à relancer à chaque livraison qui touche station.toml).
"""
from __future__ import annotations

import dataclasses
import html
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_console_doc as base  # noqa: E402  (même style, même ajustement de hauteur dans l'iframe)
from trxstation import config as cfgmod  # noqa: E402

CONTENT = ROOT / "docs" / "station-toml" / "contenu.toml"
SITE = ROOT / "docs" / "site"
MARKDOWN = ROOT / "docs" / "station-toml.md"
FOLDER = "station-toml"
LANGS = base.LANGS                                  # fr, en, de, es ; « fr » = référence, page à la racine de station-toml/
FLAGS = base.GUIDE.FLAGS                            # drapeaux en SVG du guide de l'opérateur
LANG_NAMES = base.GUIDE.LANG_NAMES
# Champs qui ne se traduisent pas : ils doivent être les mêmes dans toutes les langues.
SHARED_FIELDS = ("niveau", "depuis")
# Textes de la page (hors contenu).
UI: dict[str, dict[str, str]] = {
    "fr": {"version": "openRemoteTRX version {version}", "role": "À quoi il sert", "default": "Par défaut",
           "values": "Valeurs", "example": "Exemple", "safety": "Sécurité", "courant": "courant", "expert": "expert",
           "since": "depuis {version}", "where": "Se modifie : {where} — {when}.",
           "hot": "relu par la station en quelques secondes, sans redémarrer",
           "restart": "pris en compte au redémarrage de la station (openRemoteTRX Console le propose)",
           "required": "obligatoire", "empty": "vide", "file_start": "(début du fichier)",
           "latest": "Dernière version", "others": "Autres versions : {list}.",
           "console": "Mode d'emploi d'openRemoteTRX Console : <a href=\"{href}\">console</a>.",
           "footer": "Projet libre (AGPL-3.0-or-later)", "source": "code source", "langs": "Langue"},
    "en": {"version": "openRemoteTRX version {version}", "role": "What it does", "default": "Default",
           "values": "Values", "example": "Example", "safety": "Safety", "courant": "common", "expert": "expert",
           "since": "since {version}", "where": "Changed with: {where} — {when}.",
           "hot": "read again by the station within seconds, no restart needed",
           "restart": "applied when the station restarts (openRemoteTRX Console offers to do it)",
           "required": "required", "empty": "empty", "file_start": "(start of the file)",
           "latest": "Latest version", "others": "Other versions: {list}.",
           "console": "openRemoteTRX Console manual: <a href=\"{href}\">console</a>.",
           "footer": "Free software (AGPL-3.0-or-later)", "source": "source code", "langs": "Language"},
    "de": {"version": "openRemoteTRX Version {version}", "role": "Wozu er dient", "default": "Standardwert",
           "values": "Werte", "example": "Beispiel", "safety": "Sicherheit", "courant": "üblich", "expert": "Experte",
           "since": "seit {version}", "where": "Änderung über: {where} — {when}.",
           "hot": "wird von der Station innerhalb von Sekunden neu gelesen, ohne Neustart",
           "restart": "wird beim Neustart der Station übernommen (die openRemoteTRX Console bietet ihn an)",
           "required": "Pflichtangabe", "empty": "leer", "file_start": "(Anfang der Datei)",
           "latest": "Neueste Version", "others": "Weitere Versionen: {list}.",
           "console": "Bedienungsanleitung der openRemoteTRX Console: <a href=\"{href}\">Console</a>.",
           "footer": "Freie Software (AGPL-3.0-or-later)", "source": "Quellcode", "langs": "Sprache"},
    "es": {"version": "openRemoteTRX versión {version}", "role": "Para qué sirve", "default": "Por defecto",
           "values": "Valores", "example": "Ejemplo", "safety": "Seguridad", "courant": "habitual", "expert": "experto",
           "since": "desde {version}", "where": "Se modifica con: {where} — {when}.",
           "hot": "la estación lo vuelve a leer en pocos segundos, sin reiniciar",
           "restart": "se aplica al reiniciar la estación (openRemoteTRX Console lo propone)",
           "required": "obligatorio", "empty": "vacío", "file_start": "(inicio del archivo)",
           "latest": "Última versión", "others": "Otras versiones: {list}.",
           "console": "Manual de openRemoteTRX Console: <a href=\"{href}\">consola</a>.",
           "footer": "Software libre (AGPL-3.0-or-later)", "source": "código fuente", "langs": "Idioma"},
}

# Ordre de la notice : du plus courant au plus technique. (section, classe ou None pour la racine, tableau ?)
SECTIONS: list[tuple[str, type | None, bool]] = [
    ("rig", cfgmod.Rig, False), ("audio", cfgmod.Audio, False), ("network", cfgmod.Network, False),
    ("safety", cfgmod.Safety, False), ("bands", cfgmod.Band, True), ("clients", cfgmod.ClientAuth, True),
    ("access", cfgmod.Access, False), ("swr", cfgmod.Swr, False), ("power", cfgmod.Power, False), ("breizh", cfgmod.Breizh, False), ("netprobe", cfgmod.Netprobe, False), ("presence", cfgmod.Presence, False), ("monitor_link", cfgmod.MonitorLink, False), ("diffusion", cfgmod.Diffusion, False), ("remote_console", cfgmod.RemoteConsole, False), ("dashboard", cfgmod.Dashboard, False), ("freedv", cfgmod.Freedv, False), ("sdr", cfgmod.Sdr, False),
    ("spectrum", cfgmod.Spectrum, False),
    ("selcall", cfgmod.Selcall, False), ("cluster", cfgmod.Cluster, False), ("cluster.source", cfgmod.ClusterSource, True),
    ("supervisor", cfgmod.Supervisor, False), ("modules", cfgmod.Modules, False), ("update", cfgmod.Update, False),
    ("tools", cfgmod.Tools, False), ("racine", None, False),
]
ROOT_KEYS = ("schema_version", "config_revision")
EXTRA_CSS = """
.courant,.pro{display:inline-block;border-radius:1rem;padding:0 .55rem;font-size:.8rem;font-weight:600;vertical-align:middle}
.courant{background:#1d3b2a;color:#7fdcaa}
.pro{background:#2c2f3a;color:#aab4c6}
.cle{font-family:ui-monospace,Consolas,monospace;font-weight:700}
.defaut{color:var(--doux);font-size:.9rem}
.secu{color:#ffb4ad}
.neuf{display:inline-block;border:1px solid var(--accent);color:var(--accent);border-radius:1rem;padding:0 .5rem;font-size:.75rem}
.langues{display:flex;flex-wrap:wrap;gap:.4rem;justify-content:flex-end;margin:0 0 .4rem;font-size:.9rem;color:var(--texte)}
.langues a,.langues strong{display:inline-flex;align-items:center;gap:.4rem;border:1px solid var(--ligne);
  border-radius:2rem;padding:.15rem .7rem .15rem .45rem;text-decoration:none}
.langues svg{width:1.4rem;height:auto;border-radius:.15rem;box-shadow:0 0 0 1px rgba(255,255,255,.25);flex:none}
.langues strong{background:var(--carte);border-color:var(--accent);font-weight:600}
"""


class DocError(Exception):
    pass


def fields_of(section: str, cls: type | None) -> list[tuple[str, object]]:
    """(clé, valeur par défaut) d'une section, dans l'ordre du code."""
    if cls is None:
        return [(k, getattr(cfgmod.Config(), k)) for k in ROOT_KEYS]
    out = []
    for f in dataclasses.fields(cls):
        if f.default is not dataclasses.MISSING:
            value = f.default
        elif f.default_factory is not dataclasses.MISSING:
            value = f.default_factory()
        else:
            value = dataclasses.MISSING
        out.append((f.name, value))
    return out


def content_path(lang: str) -> Path:
    return CONTENT if lang == "fr" else CONTENT.with_name(f"contenu.{lang}.toml")


def load_content(path: Path = CONTENT) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_all() -> dict[str, dict]:
    return {lang: load_content(content_path(lang)) for lang in LANGS}


def check_all(contents: dict[str, dict]) -> None:
    """Chaque langue est complète, et ses traductions ont les MÊMES sections, réglages et champs que le français."""
    problems = []
    for lang, content in contents.items():
        try:
            check(content)
        except DocError as exc:
            problems += [f"[{lang}] {line}" for line in str(exc).splitlines()]
    ref = contents["fr"]
    for lang, content in contents.items():
        if lang == "fr":
            continue
        for name in ("titre", "intro", "lecture"):
            if not content.get("page", {}).get(name):
                problems.append(f"[{lang}] page.{name} absent")
        for s, sec in ref.get("sections", {}).items():
            other = content.get("sections", {}).get(s, {})
            if set(other) != set(sec):
                problems.append(f"[{lang}] section {s} : champs {sorted(other)} au lieu de {sorted(sec)}")
            if other.get("relu") != sec.get("relu"):
                problems.append(f"[{lang}] section {s} : « relu » doit rester « {sec.get('relu')} »")
        for key, item in ref.get("reglages", {}).items():
            other = content.get("reglages", {}).get(key)
            if other is None:
                continue                                    # déjà signalé par check()
            if set(other) != set(item):
                problems.append(f"[{lang}] {key} : champs {sorted(other)} au lieu de {sorted(item)}")
            for name in SHARED_FIELDS:
                if other.get(name) != item.get(name):
                    problems.append(f"[{lang}] {key} : « {name} » doit être le même qu'en français")
    if problems:
        raise DocError("\n".join(problems))


def check(content: dict) -> None:
    """Chaque réglage du code a son explication, et inversement ; chaque section aussi."""
    expected = {f"{s}.{k}" for s, cls, _ in SECTIONS for k, _ in fields_of(s, cls)}
    documented = set(content.get("reglages", {}))
    problems = [f"réglage sans explication : {k}" for k in sorted(expected - documented)]
    problems += [f"explication d'un réglage qui n'existe plus : {k}" for k in sorted(documented - expected)]
    for s, _, _ in SECTIONS:
        if s not in content.get("sections", {}):
            problems.append(f"section sans explication : {s}")
    for key, item in content.get("reglages", {}).items():
        if not item.get("role"):
            problems.append(f"{key} : « role » vide")
        if item.get("niveau") not in ("courant", "expert"):
            problems.append(f"{key} : niveau « courant » ou « expert » attendu")
    known = {s for s, _, _ in SECTIONS}
    problems += [f"section inconnue : {s}" for s in content.get("sections", {}) if s not in known]
    if problems:
        raise DocError("\n".join(problems))


def default_text(value: object, lang: str = "fr") -> str:
    """Valeur par défaut, écrite comme dans station.toml."""
    if value is dataclasses.MISSING:
        return UI[lang]["required"]
    if value is None:
        return UI[lang]["empty"]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '""' if value == "" else f'"{value}"'
    if isinstance(value, list):
        return "[" + ", ".join(default_text(v, lang) for v in value) + "]"
    return str(value)


def _header(section: str, array: bool, lang: str = "fr") -> str:
    if section == "racine":
        return UI[lang]["file_start"]
    return f"[[{section}]]" if array else f"[{section}]"


def _sub(lang: str) -> str:
    return "" if lang == "fr" else f"{lang}/"


def language_bar(lang: str, root: str, version_dir: str) -> str:
    """Choix de la langue par drapeaux (liens relatifs : ils marchent aussi dans l'iframe du site)."""
    items = []
    for other in LANGS:
        name = (f'<svg viewBox="0 0 60 40" aria-hidden="true">{FLAGS[other]}</svg>'
                f'<span>{html.escape(LANG_NAMES[other])}</span>')
        if other == lang:
            items.append(f'<strong aria-current="page" lang="{other}">{name}</strong>')
        else:
            href = root + version_dir + _sub(other)
            items.append(f'<a href="{href or "./"}" lang="{other}" hreflang="{other}">{name}</a>')
    return f'<nav class="langues" aria-label="{html.escape(UI[lang]["langs"])}">{"".join(items)}</nav>'


def render(version: str, content: dict, versions: list[str], lang: str = "fr", versioned: bool = False,
           site: Path = SITE) -> str:
    check(content)
    esc = html.escape
    ui = UI[lang]
    page = content["page"]
    root = "../" * ((1 if versioned else 0) + (0 if lang == "fr" else 1))     # vers station-toml/
    out = ["<!doctype html>",
           "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
           "<!-- Copyright (C) 2026 RF-DIY.COM -->",
           "<!-- Fabriqué par scripts/build_station_toml_doc.py à partir de trxstation/config.py et de "
           "docs/station-toml/contenu*.toml : ne pas modifier à la main. -->",
           f'<html lang="{lang}">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{esc(page['titre'])} ({esc(version)})</title>",
           f"<style>{base.CSS.strip()}{EXTRA_CSS.strip()}</style>", "</head>", "<body>", "<main>",
           language_bar(lang, root, f"{version}/" if versioned else ""),
           f"<h1>{esc(page['titre'])}</h1>",
           f'<p class="version">{esc(ui["version"].format(version=version))}</p>',
           page["intro"].strip(), f'<div class="lecture">{page["lecture"].strip()}</div>',
           '<ul class="sommaire">' + "".join(f'<li><a href="#{base._slug(s)}">{esc(_header(s, a, lang))}</a></li>'
                                             for s, _, a in SECTIONS) + "</ul>"]
    for section, cls, array in SECTIONS:
        sec = content["sections"][section]
        relu = ui["hot"] if sec.get("relu") == "chaud" else ui["restart"]
        out += [f'<h2 id="{base._slug(section)}">{esc(sec["titre"])}</h2>', sec["intro"].strip(),
                f'<p class="defaut">{ui["where"].format(where=sec["ou"], when=relu)}</p>']
        for key, value in fields_of(section, cls):
            item = content["reglages"][f"{section}.{key}"]
            badge = (f'<span class="courant">{esc(ui["courant"])}</span>' if item["niveau"] == "courant"
                     else f'<span class="pro">{esc(ui["expert"])}</span>')
            new = f' <span class="neuf">{esc(ui["since"].format(version=item["depuis"]))}</span>' if item.get("depuis") else ""
            rows = [f"<dt>{esc(ui['role'])}</dt><dd>{item['role']}</dd>",
                    f"<dt>{esc(ui['default'])}</dt>"
                    f"<dd>{item.get('defaut') or '<code>' + esc(default_text(value, lang)) + '</code>'}</dd>"]
            if item.get("bornes"):
                rows.append(f"<dt>{esc(ui['values'])}</dt><dd>{item['bornes']}</dd>")
            if item.get("exemple"):
                rows.append(f"<dt>{esc(ui['example'])}</dt><dd>{item['exemple']}</dd>")
            if item.get("securite"):
                rows.append(f'<dt>{esc(ui["safety"])}</dt><dd class="secu">{item["securite"]}</dd>')
            out.append(f'<details id="{base._slug(section + "-" + key)}"><summary><span class="cle">{esc(key)}</span> '
                       f'{badge}{new}</summary><div class="corps"><dl>{"".join(rows)}</dl></div></details>')
    # Anciennes versions : seulement celles qui existent dans cette langue (les plus anciennes sont en français seul).
    others = [v for v in versions if v != version and (lang == "fr" or (site / FOLDER / v / lang / "index.html").is_file())]
    archive = (esc(ui["others"]).replace("{list}", ", ".join(f'<a href="{root}{esc(v)}/{_sub(lang)}">{esc(v)}</a>'
                                                              for v in others)) + " ") if others else ""
    if versioned:
        archive = f'<a href="{root}{_sub(lang)}">{esc(ui["latest"])}</a>. ' + archive
    console = ui["console"].format(href=f"{root}../console/{_sub(lang)}")
    out += ["<footer>",
            f'<p>{archive}{console} {esc(ui["footer"])} : '
            f'<a href="{base.REPO_URL}" target="_blank" rel="noopener noreferrer">{esc(ui["source"])}</a> · '
            f'<a href="{base.SITE_URL}" target="_blank" rel="noopener noreferrer">rf-diy.com</a></p>',
            "</footer>", "</main>", f"<script>{base.RESIZE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def _md(fragment: str) -> str:
    """HTML simple du contenu -> Markdown léger (code, gras), sur une ligne."""
    text = re.sub(r"\s+", " ", fragment)
    text = re.sub(r"</?code>", "`", text)
    text = re.sub(r"</?strong>", "**", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def render_markdown(version: str, content: dict) -> str:
    check(content)
    page = content["page"]
    out = ["<!-- Fabriqué par scripts/build_station_toml_doc.py : ne pas modifier à la main "
           "(explications : docs/station-toml/contenu.toml). -->", "",
           f"# {page['titre']}", "", f"openRemoteTRX version {version}. Page du site : "
           "https://bob56fr.github.io/openRemoteTRX/station-toml/", "", _md(page["intro"]), "", _md(page["lecture"]), ""]
    for section, cls, array in SECTIONS:
        sec = content["sections"][section]
        out += [f"## {_md(sec['titre'])}", "", _md(sec["intro"]), "",
                f"Se modifie : {_md(sec['ou'])} " + ("(relu sans redémarrer)." if sec.get("relu") == "chaud" else "(au redémarrage)."), "",
                "| Clé | Niveau | Par défaut | À quoi il sert |", "|---|---|---|---|"]
        for key, value in fields_of(section, cls):
            item = content["reglages"][f"{section}.{key}"]
            extra = " ".join(x for x in (_md(item.get("bornes", "")) and "Valeurs : " + _md(item["bornes"]),
                                         _md(item.get("securite", "")) and "**Sécurité** : " + _md(item["securite"]),
                                         _md(item.get("exemple", "")) and "Exemple : " + _md(item["exemple"]),
                                         item.get("depuis") and f"(depuis {item['depuis']})") if x)
            default = _md(item["defaut"]) if item.get("defaut") else "`" + default_text(value) + "`"
            cell = (_md(item["role"]) + (" " + extra if extra else "")).replace("|", "\\|")
            out.append(f"| `{key}` | {item['niveau']} | {default.replace('|', '/')} | {cell} |")
        out.append("")
    return "\n".join(out)


def published_versions(site: Path = SITE) -> list[str]:
    folder = site / FOLDER
    found = [p.name for p in folder.iterdir() if p.is_dir() and base.VERSION_DIR.match(p.name)] if folder.is_dir() else []
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)


def build(site: Path = SITE, version: str | None = None) -> dict[Path, str]:
    """Pages à écrire {chemin: contenu}. La page d'une version ANTÉRIEURE n'est jamais réécrite."""
    version = version or base.project_version()
    contents = load_all()
    check_all(contents)
    versions = sorted(set(published_versions(site)) | {version}, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    pages: dict[Path, str] = {}
    for lang in LANGS:
        sub = _sub(lang)
        pages[site / FOLDER / sub / "index.html"] = render(version, contents[lang], versions, lang=lang, site=site)
        pages[site / FOLDER / version / sub / "index.html"] = render(version, contents[lang], versions, lang=lang,
                                                                       versioned=True, site=site)
    pages[MARKDOWN] = render_markdown(version, contents["fr"])
    return pages


def main() -> int:
    try:
        pages = build()
    except DocError as exc:
        print("Notice de station.toml NON fabriquée :\n" + str(exc), file=sys.stderr)
        return 1
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(f"écrit : {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
