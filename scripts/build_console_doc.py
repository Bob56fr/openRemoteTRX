# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le mode d'emploi de TRX Console (page HTML, thème sombre) publié par GitHub Pages.

La liste des menus vient du code (`trxstation.console.Console.items`) ; les explications de
`docs/console/contenu.toml`. Un menu sans explication (ou une explication sans menu) arrête la fabrication.

Résultat dans `docs/site/` :
  - `console/index.html` : dernière version (adresse fixe, celle de l'iframe du site rf-diy.com) ;
  - `console/<version>/index.html` : une copie par version, gardée (l'utilisateur d'une ancienne version lit la sienne) ;
  - `index.html` : accueil minimal vers la page.
Usage : python scripts/build_console_doc.py   (à relancer à chaque étape qui touche la console ; les tests vérifient
que la page publiée est à jour).
"""
from __future__ import annotations

import html
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "docs" / "console" / "contenu.toml"
SITE = ROOT / "docs" / "site"
REPO_URL = "https://github.com/Bob56fr/openRemoteTRX"
SITE_URL = "https://www.rf-diy.com"
VERSION_DIR = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")

CSS = """
:root{--fond:#0f141c;--carte:#171e29;--ligne:#2a3445;--texte:#dbe3ee;--doux:#9aa8bb;--accent:#4c9be8;--emission:#e0524a;
  --ok:#3fae72;--code:#0b1017;color-scheme:dark}
*{box-sizing:border-box}
html{background:var(--fond)}
body{margin:0;background:var(--fond);color:var(--texte);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:56rem;margin:0 auto;padding:1.2rem 16px 2.5rem}
h1{font-size:1.7rem;line-height:1.2;margin:.4rem 0 .2rem}
h2{font-size:1.3rem;margin:2.2rem 0 .7rem;padding-bottom:.3rem;border-bottom:1px solid var(--ligne)}
h3{font-size:1.05rem;margin:0}
p{margin:.45rem 0 .8rem}
a{color:var(--accent)}
code{background:var(--code);border:1px solid var(--ligne);border-radius:.3rem;padding:0 .3rem;font-size:.92em;
  overflow-wrap:anywhere}
pre{background:var(--code);border:1px solid var(--ligne);border-radius:.5rem;padding:.6rem .8rem;overflow-x:auto;
  font-size:.9rem;white-space:pre-wrap;overflow-wrap:anywhere}
ul,ol{margin:.3rem 0 .9rem 1.3rem;padding:0}
li{margin:.2rem 0}
.version{color:var(--doux);font-size:.95rem;margin:0 0 1rem}
.lecture{background:var(--carte);border:1px solid var(--ligne);border-left:.3rem solid var(--accent);border-radius:.5rem;
  padding:.5rem 1rem;margin:1rem 0}
.sommaire{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0 0;padding:0;list-style:none}
.sommaire a{display:inline-block;background:var(--carte);border:1px solid var(--ligne);border-radius:2rem;
  padding:.25rem .9rem;text-decoration:none;color:var(--texte)}
.etapes{list-style:none;margin:0;padding:0;counter-reset:e}
.etapes>li{counter-increment:e;display:grid;grid-template-columns:2.2rem 1fr;gap:.8rem;background:var(--carte);
  border:1px solid var(--ligne);border-radius:.6rem;padding:.8rem 1rem;margin:.7rem 0}
.etapes>li::before{content:counter(e);width:2rem;height:2rem;border-radius:50%;background:var(--accent);color:#fff;
  font-weight:700;display:flex;align-items:center;justify-content:center}
.etapes>li>div{min-width:0}
details{background:var(--carte);border:1px solid var(--ligne);border-radius:.6rem;margin:.55rem 0}
summary{cursor:pointer;padding:.65rem 1rem;display:flex;gap:.7rem;align-items:baseline;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"\\25B8";color:var(--doux);transition:transform .15s}
details[open]>summary::before{transform:rotate(90deg)}
.num{flex:none;min-width:2.1rem;text-align:center;font-weight:700;color:#fff;background:var(--accent);border-radius:.4rem;
  padding:0 .3rem}
.corps{padding:0 1rem .8rem 1rem}
dl{display:grid;grid-template-columns:minmax(7rem,max-content) 1fr;gap:.35rem 1rem;margin:.2rem 0 .6rem}
dt{color:var(--doux)}
dd{margin:0;min-width:0}
.sudo{color:var(--emission);font-weight:600}
.libre{color:var(--ok);font-weight:600}
.expert{border-top:1px dashed var(--ligne);margin-top:.5rem;padding-top:.4rem}
.expert::before{content:"Pour aller plus loin";display:block;color:var(--doux);font-size:.85rem;text-transform:uppercase;
  letter-spacing:.04em}
.bloc{background:var(--carte);border:1px solid var(--ligne);border-radius:.6rem;padding:.6rem 1rem;margin:.7rem 0}
footer{margin-top:2.5rem;color:var(--doux);font-size:.9rem;border-top:1px solid var(--ligne);padding-top:.8rem}
@media (max-width:30rem){dl{grid-template-columns:1fr}dt{margin-top:.3rem}}
"""

# Hauteur envoyée au site qui affiche la page dans une iframe (le site l'applique à l'iframe : pas de double défilement).
RESIZE_JS = """
(function () {
  if (window.parent === window) return;
  var last = 0;
  function send() {
    var h = Math.ceil(document.documentElement.scrollHeight);
    if (h !== last) { last = h; window.parent.postMessage({ type: "trx-doc-height", height: h }, "*"); }
  }
  window.addEventListener("load", send);
  document.addEventListener("toggle", send, true);
  if (window.ResizeObserver) new ResizeObserver(send).observe(document.body);
  else window.addEventListener("resize", send);
})();
"""


class DocError(Exception):
    pass


def project_version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def console_menus() -> list[tuple[str, str, str]]:
    """[(numéro, libellé, nom de la méthode)] dans l'ordre du menu, lus dans le code de la console."""
    sys.path.insert(0, str(ROOT))
    from trxstation.console import Console
    con = Console(ROOT / "absent" / "station.toml", update_state=lambda: None, previous=lambda: None, home=ROOT,
                  editor="nano")
    return [(key, label, fn.__name__) for key, label, fn in con.items]


def load_content(path: Path = CONTENT) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def check(menus: list[tuple[str, str, str]], content: dict) -> None:
    documented = set(content.get("menus", {}))
    names = {name for _, _, name in menus}
    problems = [f"menu {key} « {label} » ({name}) sans explication dans {CONTENT.name}"
                for key, label, name in menus if name not in documented]
    problems += [f"explication [menus.{name}] sans menu correspondant dans la console" for name in sorted(documented - names)]
    for name, fields in content.get("menus", {}).items():
        missing = [f for f in ("role", "quand", "modifie", "admin") if f not in fields]
        if missing:
            problems.append(f"[menus.{name}] : champ(s) manquant(s) {', '.join(missing)}")
    text = CONTENT.read_text(encoding="utf-8") if CONTENT.exists() else ""
    if re.search(r"<\s*(script|iframe|img|link|style)\b", text, re.I):
        problems.append("contenu : balise interdite (script, iframe, img, link, style)")
    if re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text):
        problems.append("contenu : adresse IP trouvée (exemples génériques seulement)")
    if problems:
        raise DocError("\n".join(problems))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render(version: str, menus: list[tuple[str, str, str]], content: dict, versions: list[str], up: str = "") -> str:
    """`up` : chemin vers le dossier console/ depuis la page ("" pour console/index.html, "../" pour une version)."""
    check(menus, content)
    page = content["page"]
    esc = html.escape
    out = ["<!doctype html>",
           "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
           "<!-- Copyright (C) 2026 RF-DIY.COM -->",
           "<!-- Fabriqué par scripts/build_console_doc.py à partir de docs/console/contenu.toml : ne pas modifier à la main. -->",
           '<html lang="fr">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{esc(page['titre'])} ({esc(version)})</title>",
           f"<style>{CSS.strip()}</style>", "</head>", "<body>", "<main>",
           f"<h1>{esc(page['titre'])}</h1>",
           f'<p class="version">TRX distant version {esc(version)}</p>',
           page["intro"].strip(),
           f'<div class="lecture">{page["lecture"].strip()}</div>',
           '<ul class="sommaire"><li><a href="#premier-deploiement">Premier déploiement</a></li>'
           '<li><a href="#menus">Les menus</a></li><li><a href="#depannage">Dépannage avancé</a></li></ul>',
           '<h2 id="premier-deploiement">Premier déploiement, pas à pas</h2>', '<ol class="etapes">']
    for step in content.get("parcours", []):
        out.append(f"<li><div><h3>{esc(step['titre'])}</h3>{step['texte'].strip()}</div></li>")
    out += ["</ol>", '<h2 id="menus">Les menus de la console</h2>',
            "<p>Tape le numéro du menu puis Entrée ; <code>q</code> pour quitter. Les réponses aux questions "
            "(oui, non, OUI, EMETTRE...) ne tiennent compte ni des majuscules ni des accents. "
            '<span class="sudo">Mot de passe</span> : le menu demande ton mot de passe de session (sudo).</p>']
    for key, label, name in menus:
        item = content["menus"][name]
        rights = ('<span class="sudo">mot de passe de session demandé</span>' if item["admin"]
                  else '<span class="libre">non</span>')
        extra = f'<div class="expert">{item["expert"].strip()}</div>' if item.get("expert") else ""
        out.append(f'<details id="menu-{esc(key)}"><summary><span class="num">{esc(key)}</span>'
                   f"<h3>{esc(label)}</h3></summary><div class=\"corps\"><dl>"
                   f"<dt>À quoi il sert</dt><dd>{item['role']}</dd>"
                   f"<dt>Quand</dt><dd>{item['quand']}</dd>"
                   f"<dt>Ce qu'il modifie</dt><dd>{item['modifie']}</dd>"
                   f"<dt>Droits</dt><dd>{rights}</dd></dl>{extra}</div></details>")
    out.append('<h2 id="depannage">Dépannage avancé</h2>')
    for block in content.get("expert", []):
        out.append(f'<div class="bloc" id="{_slug(block["titre"])}"><h3>{esc(block["titre"])}</h3>{block["texte"].strip()}</div>')
    others = [v for v in versions if v != version]
    archive = ("Autres versions : " + ", ".join(f'<a href="{up}{esc(v)}/">{esc(v)}</a>' for v in others) + ". ") if others else ""
    if up:
        archive = f'<a href="{up}">Dernière version</a>. ' + archive
    out += ["<footer>",
            f'<p>{archive}Projet libre (AGPL-3.0-or-later) : <a href="{REPO_URL}" target="_blank" rel="noopener noreferrer">'
            f'code source</a> · <a href="{SITE_URL}" target="_blank" rel="noopener noreferrer">rf-diy.com</a></p>',
            "</footer>", "</main>", f"<script>{RESIZE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def published_versions(site: Path = SITE) -> list[str]:
    folder = site / "console"
    found = [p.name for p in folder.iterdir() if p.is_dir() and VERSION_DIR.match(p.name)] if folder.is_dir() else []
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)


def build(site: Path = SITE, version: str | None = None) -> dict[Path, str]:
    """Pages à écrire {chemin: contenu}. La page d'une version ANTÉRIEURE n'est jamais réécrite."""
    version = version or project_version()
    menus, content = console_menus(), load_content()
    versions = sorted(set(published_versions(site)) | {version},
                      key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    home = ("<!doctype html>\n<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->\n<!-- Copyright (C) 2026 RF-DIY.COM -->\n"
            '<html lang="fr"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=console/">'
            "<title>TRX distant</title></head><body style=\"background:#0f141c;color:#dbe3ee;font-family:system-ui\">"
            '<p><a style="color:#4c9be8" href="console/">Mode d\'emploi de TRX Console</a></p></body></html>\n')
    return {site / "console" / "index.html": render(version, menus, content, versions),
            site / "console" / version / "index.html": render(version, menus, content, versions, up="../"),
            site / "index.html": home}


def main() -> int:
    try:
        pages = build()
    except DocError as exc:
        print("Mode d'emploi NON fabriqué :\n" + str(exc), file=sys.stderr)
        return 1
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(f"écrit : {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
