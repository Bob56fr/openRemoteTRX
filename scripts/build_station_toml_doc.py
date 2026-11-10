# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique la notice des réglages de station.toml (page HTML, thème sombre) publiée par GitHub Pages et affichée dans
une iframe du site rf-diy.com, plus sa version Markdown pour le dépôt.

La LISTE des réglages et leurs valeurs par défaut viennent du code (`trxstation.config`) ; les explications de
`docs/station-toml/contenu.toml`. Un réglage sans explication, ou une explication sans réglage, arrête la fabrication
(et les tests) : la notice suit le code à chaque livraison.

Résultat :
  - `docs/site/station-toml/index.html` : dernière version (adresse fixe, celle de l'iframe du site) ;
  - `docs/site/station-toml/<version>/index.html` : une copie par version, gardée ;
  - `docs/station-toml.md` : la même notice en Markdown (lecture sur GitHub).
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

# Ordre de la notice : du plus courant au plus technique. (section, classe ou None pour la racine, tableau ?)
SECTIONS: list[tuple[str, type | None, bool]] = [
    ("rig", cfgmod.Rig, False), ("audio", cfgmod.Audio, False), ("network", cfgmod.Network, False),
    ("safety", cfgmod.Safety, False), ("bands", cfgmod.Band, True), ("clients", cfgmod.ClientAuth, True),
    ("access", cfgmod.Access, False), ("swr", cfgmod.Swr, False), ("breizh", cfgmod.Breizh, False), ("netprobe", cfgmod.Netprobe, False), ("presence", cfgmod.Presence, False),
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


def load_content(path: Path = CONTENT) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


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


def default_text(value: object) -> str:
    """Valeur par défaut, écrite comme dans station.toml."""
    if value is dataclasses.MISSING:
        return "obligatoire"
    if value is None:
        return "vide"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '""' if value == "" else f'"{value}"'
    if isinstance(value, list):
        return "[" + ", ".join(default_text(v) for v in value) + "]"
    return str(value)


def _header(section: str, array: bool) -> str:
    if section == "racine":
        return "(début du fichier)"
    return f"[[{section}]]" if array else f"[{section}]"


def render(version: str, content: dict, versions: list[str], up: str = "") -> str:
    check(content)
    esc = html.escape
    page = content["page"]
    out = ["<!doctype html>",
           "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
           "<!-- Copyright (C) 2026 RF-DIY.COM -->",
           "<!-- Fabriqué par scripts/build_station_toml_doc.py à partir de trxstation/config.py et de "
           "docs/station-toml/contenu.toml : ne pas modifier à la main. -->",
           '<html lang="fr">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{esc(page['titre'])} ({esc(version)})</title>",
           f"<style>{base.CSS.strip()}{EXTRA_CSS.strip()}</style>", "</head>", "<body>", "<main>",
           f"<h1>{esc(page['titre'])}</h1>",
           f'<p class="version">TRX distant version {esc(version)}</p>',
           page["intro"].strip(), f'<div class="lecture">{page["lecture"].strip()}</div>',
           '<ul class="sommaire">' + "".join(f'<li><a href="#{base._slug(s)}">{esc(_header(s, a))}</a></li>'
                                             for s, _, a in SECTIONS) + "</ul>"]
    for section, cls, array in SECTIONS:
        sec = content["sections"][section]
        relu = ("relu par la station en quelques secondes, sans redémarrer" if sec.get("relu") == "chaud"
                else "pris en compte au redémarrage de la station (TRX Console le propose)")
        out += [f'<h2 id="{base._slug(section)}">{esc(sec["titre"])}</h2>', sec["intro"].strip(),
                f'<p class="defaut">Se modifie : {sec["ou"]} — {relu}.</p>']
        for key, value in fields_of(section, cls):
            item = content["reglages"][f"{section}.{key}"]
            badge = '<span class="courant">courant</span>' if item["niveau"] == "courant" else '<span class="pro">expert</span>'
            new = f' <span class="neuf">depuis {esc(item["depuis"])}</span>' if item.get("depuis") else ""
            rows = [f"<dt>À quoi il sert</dt><dd>{item['role']}</dd>",
                    f"<dt>Par défaut</dt><dd>{item.get('defaut') or '<code>' + esc(default_text(value)) + '</code>'}</dd>"]
            if item.get("bornes"):
                rows.append(f"<dt>Valeurs</dt><dd>{item['bornes']}</dd>")
            if item.get("exemple"):
                rows.append(f"<dt>Exemple</dt><dd>{item['exemple']}</dd>")
            if item.get("securite"):
                rows.append(f'<dt>Sécurité</dt><dd class="secu">{item["securite"]}</dd>')
            out.append(f'<details id="{base._slug(section + "-" + key)}"><summary><span class="cle">{esc(key)}</span> '
                       f'{badge}{new}</summary><div class="corps"><dl>{"".join(rows)}</dl></div></details>')
    others = [v for v in versions if v != version]
    archive = ("Autres versions : " + ", ".join(f'<a href="{up}{esc(v)}/">{esc(v)}</a>' for v in others) + ". ") if others else ""
    if up:
        archive = f'<a href="{up}">Dernière version</a>. ' + archive
    out += ["<footer>",
            f'<p>{archive}Mode d\'emploi de TRX Console : <a href="{up}../console/">console</a>. Projet libre '
            f'(AGPL-3.0-or-later) : <a href="{base.REPO_URL}" target="_blank" rel="noopener noreferrer">code source</a> · '
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
           f"# {page['titre']}", "", f"TRX distant version {version}. Page du site : "
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
    content = load_content()
    versions = sorted(set(published_versions(site)) | {version}, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    return {site / FOLDER / "index.html": render(version, content, versions),
            site / FOLDER / version / "index.html": render(version, content, versions, up="../"),
            MARKDOWN: render_markdown(version, content)}


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
