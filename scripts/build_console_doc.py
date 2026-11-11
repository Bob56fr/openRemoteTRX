# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique le mode d'emploi de TRX Console (pages HTML, thème sombre) publié par GitHub Pages, dans chaque langue.

La liste des menus (thèmes, numéros, libellés) vient du code (`trxstation.console`, catalogues `trxstation/i18n/`) ;
les explications de `docs/console/contenu.toml` (français, référence) et `contenu.<langue>.toml` (en, de, es).
Toutes les langues doivent avoir les MÊMES menus, champs, étapes et blocs : sinon la fabrication et les tests
échouent (un nouveau menu s'écrit donc dans les 4 langues). La table `[ui]` porte les textes de la page.

Résultat dans `docs/site/` :
  - `console/index.html` (français) et `console/<langue>/index.html` : dernière version (adresses fixes ; celle en
    français est celle de l'iframe du site rf-diy.com) ;
  - `console/<version>/index.html` et `console/<version>/<langue>/index.html` : une copie par version, gardée ;
  - `index.html` : accueil minimal vers la page.
Usage : python scripts/build_console_doc.py   (à relancer à chaque étape qui touche la console ; les tests vérifient
que la page publiée est à jour).
"""
from __future__ import annotations

import html
import json
import re
import sys
import textwrap
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "docs" / "console" / "contenu.toml"
LANGS = ("fr", "en", "de", "es")                         # même liste que trxstation.i18n.LANGS (vérifié par les tests)
UI_KEYS = ("lang_name", "version", "nav_first", "nav_menus", "nav_expert", "h_first", "h_menus", "menus_intro", "dt_role",
           "dt_when", "dt_changes", "dt_rights", "rights_yes", "rights_no", "more", "latest", "others", "footer",
           "source", "langs")


def content_path(lang: str) -> Path:
    return CONTENT if lang == "fr" else CONTENT.with_name(f"contenu.{lang}.toml")
# Aide de la touche « h » de la console : mêmes textes, en texte simple, livrés avec la station (package-data).
HELP = ROOT / "trxstation" / "console_help.json"
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
.plus{display:block;color:var(--doux);font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;margin:0}
.theme{margin:1.4rem 0 .3rem;color:var(--doux);font-size:1rem;text-transform:uppercase;letter-spacing:.04em}
.langues{margin:0 0 1rem;color:var(--doux);font-size:.95rem}
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


def console_menus(lang: str = "fr") -> list[tuple[str, str, str, str, str]]:
    """[(numéro « thème.n », libellé, nom de la méthode, numéro du thème, titre du thème)] dans l'ordre du menu, lus
    dans le code de la console, dans la langue demandée."""
    sys.path.insert(0, str(ROOT))
    from trxstation.console import MENU_THEMES, Console
    con = Console(ROOT / "absent" / "station.toml", update_state=lambda: None, previous=lambda: None, home=ROOT,
                  editor="nano", lang=lang)
    titles = {theme: con.t(f"theme.{tid}") for theme, tid, _ in MENU_THEMES}
    return [(key, label, fn.__name__, key.split(".")[0], titles[key.split(".")[0]]) for key, label, fn in con.items]


def load_content(path: Path = CONTENT) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_all() -> dict[str, dict]:
    return {lang: load_content(content_path(lang)) for lang in LANGS}


def check(menus: list[tuple], content: dict, lang: str = "fr") -> None:
    path = content_path(lang)
    documented = set(content.get("menus", {}))
    names = {m[2] for m in menus}
    problems = [f"menu {m[0]} « {m[1]} » ({m[2]}) sans explication dans {path.name}"
                for m in menus if m[2] not in documented]
    problems += [f"explication [menus.{name}] sans menu correspondant dans la console ({path.name})"
                 for name in sorted(documented - names)]
    for name, fields in content.get("menus", {}).items():
        missing = [f for f in ("role", "quand", "modifie", "admin") if f not in fields]
        if missing:
            problems.append(f"[menus.{name}] ({path.name}) : champ(s) manquant(s) {', '.join(missing)}")
    missing_ui = [k for k in UI_KEYS if k not in content.get("ui", {})]
    if missing_ui:
        problems.append(f"[ui] ({path.name}) : clé(s) manquante(s) {', '.join(missing_ui)}")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if re.search(r"<\s*(script|iframe|img|link|style)\b", text, re.I):
        problems.append(f"{path.name} : balise interdite (script, iframe, img, link, style)")
    if re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text):
        problems.append(f"{path.name} : adresse IP trouvée (exemples génériques seulement)")
    if problems:
        raise DocError("\n".join(problems))


def check_all(contents: dict[str, dict]) -> None:
    """Chaque langue complète, et la même structure que le français (menus, champs, étapes, blocs, [ui])."""
    problems = []
    ref = contents["fr"]
    for lang in LANGS:
        c = contents.get(lang)
        if c is None:
            problems.append(f"{content_path(lang).name} absent")
            continue
        try:
            check(console_menus(lang), c, lang)
        except DocError as exc:
            problems.append(str(exc))
        if lang == "fr":
            continue
        for name, fields in ref.get("menus", {}).items():
            other = c.get("menus", {}).get(name, {})
            if set(fields) != set(other):
                problems.append(f"[menus.{name}] : champs différents du français dans {content_path(lang).name}")
            elif other.get("admin") != fields.get("admin"):
                problems.append(f"[menus.{name}] : admin différent du français dans {content_path(lang).name}")
        for part in ("parcours", "expert"):
            if len(c.get(part, [])) != len(ref.get(part, [])):
                problems.append(f"{content_path(lang).name} : {len(c.get(part, []))} [[{part}]] au lieu de "
                                f"{len(ref.get(part, []))} (français)")
        if set(c.get("page", {})) != set(ref.get("page", {})):
            problems.append(f"{content_path(lang).name} : [page] n'a pas les mêmes clés que le français")
    if problems:
        raise DocError("\n".join(problems))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def render(version: str, menus: list[tuple], content: dict, versions: list[str], lang: str = "fr",
           versioned: bool = False, site: Path = SITE) -> str:
    """Page d'une langue. `versioned` : copie gardée dans console/<version>/ (liens relatifs adaptés)."""
    check(menus, content, lang)
    page, ui = content["page"], content["ui"]
    esc = html.escape
    depth = (1 if versioned else 0) + (0 if lang == "fr" else 1)
    root = "../" * depth                                    # vers console/

    def page_url(v: str | None, lg: str) -> str:
        return root + (f"{v}/" if v else "") + ("" if lg == "fr" else f"{lg}/")

    links = []
    for lg in LANGS:
        name = esc(load_content(content_path(lg))["ui"]["lang_name"])
        links.append(f"<strong>{name}</strong>" if lg == lang else
                     f'<a href="{page_url(version if versioned else None, lg)}" hreflang="{lg}">{name}</a>')
    out = ["<!doctype html>",
           "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
           "<!-- Copyright (C) 2026 RF-DIY.COM -->",
           "<!-- Fabriqué par scripts/build_console_doc.py à partir de docs/console/contenu*.toml : ne pas modifier à la main. -->",
           f'<html lang="{lang}">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{esc(page['titre'])} ({esc(version)})</title>",
           f"<style>{CSS.strip()}</style>", "</head>", "<body>", "<main>",
           f"<h1>{esc(page['titre'])}</h1>",
           f'<p class="version">{esc(ui["version"].format(version=version))}</p>',
           f'<p class="langues">{esc(ui["langs"])} {" · ".join(links)}</p>',
           page["intro"].strip(),
           f'<div class="lecture">{page["lecture"].strip()}</div>',
           f'<ul class="sommaire"><li><a href="#premier-deploiement">{esc(ui["nav_first"])}</a></li>'
           f'<li><a href="#menus">{esc(ui["nav_menus"])}</a></li><li><a href="#depannage">{esc(ui["nav_expert"])}</a></li></ul>',
           f'<h2 id="premier-deploiement">{esc(ui["h_first"])}</h2>', '<ol class="etapes">']
    for step in content.get("parcours", []):
        out.append(f"<li><div><h3>{esc(step['titre'])}</h3>{step['texte'].strip()}</div></li>")
    out += ["</ol>", f'<h2 id="menus">{esc(ui["h_menus"])}</h2>', ui["menus_intro"].strip()]
    current_theme = None
    for key, label, name, theme, theme_title in menus:
        if theme != current_theme:
            current_theme = theme
            out.append(f'<h3 class="theme" id="theme-{esc(theme)}">{esc(theme)}) {esc(theme_title)}</h3>')
        item = content["menus"][name]
        rights = (f'<span class="sudo">{esc(ui["rights_yes"])}</span>' if item["admin"]
                  else f'<span class="libre">{esc(ui["rights_no"])}</span>')
        extra = (f'<div class="expert"><p class="plus">{esc(ui["more"])}</p>{item["expert"].strip()}</div>'
                 if item.get("expert") else "")
        out.append(f'<details id="menu-{esc(key.replace(".", "-"))}"><summary><span class="num">{esc(key)}</span>'
                   f"<h3>{esc(label)}</h3></summary><div class=\"corps\"><dl>"
                   f"<dt>{esc(ui['dt_role'])}</dt><dd>{item['role']}</dd>"
                   f"<dt>{esc(ui['dt_when'])}</dt><dd>{item['quand']}</dd>"
                   f"<dt>{esc(ui['dt_changes'])}</dt><dd>{item['modifie']}</dd>"
                   f"<dt>{esc(ui['dt_rights'])}</dt><dd>{rights}</dd></dl>{extra}</div></details>")
    out.append(f'<h2 id="depannage">{esc(ui["nav_expert"])}</h2>')
    for n, block in enumerate(content.get("expert", []), 1):
        out.append(f'<div class="bloc" id="bloc-{n}"><h3>{esc(block["titre"])}</h3>{block["texte"].strip()}</div>')
    others = [v for v in versions if v != version]

    def archived(v: str) -> str:            # une ancienne version n'a peut-être que la page en français
        has = lang == "fr" or (site / "console" / v / lang / "index.html").is_file()
        return page_url(v, lang if has else "fr")
    archive = (esc(ui["others"]) + " " + ", ".join(f'<a href="{archived(v)}">{esc(v)}</a>' for v in others) + ". ") if others else ""
    if versioned:
        archive = f'<a href="{page_url(None, lang)}">{esc(ui["latest"])}</a>. ' + archive
    out += ["<footer>",
            f'<p>{archive}{esc(ui["footer"])} : <a href="{REPO_URL}" target="_blank" rel="noopener noreferrer">'
            f'{esc(ui["source"])}</a> · <a href="{SITE_URL}" target="_blank" rel="noopener noreferrer">rf-diy.com</a></p>',
            "</footer>", "</main>", f"<script>{RESIZE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def html_to_text(fragment: str, width: int = 76, french: bool = True) -> str:
    """HTML simple du contenu (p, ul, li, code, strong, em, a) -> texte pour le terminal, coupé à `width`."""
    text = re.sub(r"\s+", " ", fragment)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"</(p|ul|ol)\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if french:      # typographie française : jamais de « : ; ? ! » ni de guillemet seuls en début ou fin de ligne
            para = re.sub(r" ([:;?!»])", " \\1", para).replace("« ", "« ")
        lines.append(textwrap.fill(para, width, subsequent_indent="  " if para.startswith("- ") else "",
                                   break_on_hyphens=False, break_long_words=False).replace(" ", " "))
    return "\n".join(lines).strip()


def help_json(contents: dict[str, dict]) -> str:
    """Contenu de trxstation/console_help.json : pour chaque langue et chaque menu, ses explications en texte simple."""
    langs = {}
    for lang, content in contents.items():
        menus = {}
        for name, fields in content.get("menus", {}).items():
            menus[name] = {key: html_to_text(fields.get(key, ""), french=lang == "fr")
                           for key in ("role", "quand", "modifie", "expert")}
            menus[name]["admin"] = bool(fields.get("admin"))
        langs[lang] = {"menus": menus}
    return json.dumps({"langs": langs}, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def published_versions(site: Path = SITE) -> list[str]:
    folder = site / "console"
    found = [p.name for p in folder.iterdir() if p.is_dir() and VERSION_DIR.match(p.name)] if folder.is_dir() else []
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)


def build(site: Path = SITE, version: str | None = None) -> dict[Path, str]:
    """Pages à écrire {chemin: contenu}. La page d'une version ANTÉRIEURE n'est jamais réécrite."""
    version = version or project_version()
    contents = load_all()
    check_all(contents)
    versions = sorted(set(published_versions(site)) | {version},
                      key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    home = ("<!doctype html>\n<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->\n<!-- Copyright (C) 2026 RF-DIY.COM -->\n"
            '<html lang="fr"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=console/">'
            "<title>TRX distant</title></head><body style=\"background:#0f141c;color:#dbe3ee;font-family:system-ui\">"
            '<p><a style="color:#4c9be8" href="console/">Mode d\'emploi de TRX Console</a></p></body></html>\n')
    pages: dict[Path, str] = {}
    for lang in LANGS:
        sub = "" if lang == "fr" else lang + "/"
        menus, content = console_menus(lang), contents[lang]
        pages[site / "console" / sub / "index.html"] = render(version, menus, content, versions, lang=lang, site=site)
        pages[site / "console" / version / sub / "index.html"] = render(version, menus, content, versions, lang=lang,
                                                                         versioned=True, site=site)
    pages[site / "index.html"] = home
    pages[HELP] = help_json(contents)
    return pages


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
