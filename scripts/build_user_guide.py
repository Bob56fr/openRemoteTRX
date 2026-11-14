# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique la page web du guide de l'opérateur (User-Guide/<langue>/*.md) publiée par GitHub Pages.

Source : les fichiers Markdown de `User-Guide/<langue>/`, lisibles tels quels sur GitHub (référence : `fr`).
Ordre de la page : README.md (introduction et sommaire), puis les parties `NN-*.md` dans l'ordre des numéros ; les
fiches de poste (`postes/*.md`) se placent juste après la partie 1 (préparer le poste). Le récapitulatif (dernière
partie) a des cases à cocher cliquables, gardées dans le navigateur quand c'est possible.

Le Markdown reconnu est volontairement réduit : titres (#, ##, ###), paragraphes, listes à puces ou numérotées
(imbriquées par indentation, blocs de code compris), cases `- [ ]`, tableaux, citations `>` (encadré ; un encadré
qui commence par « **Sécurité » est rouge), blocs de code ```, `code`, **gras**, *italique*, liens [texte](cible) et
adresses https:// nues. Un lien vers un autre fichier .md du guide devient une ancre de la page.

Résultat : `docs/site/guide/index.html` (français) et `docs/site/guide/<langue>/index.html` (autres langues, quand
elles existeront). Pas de copie par version : le guide décrit la dernière version.
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
LANGS = ("fr",)                      # langues publiées ; « fr » = référence (page à la racine de guide/)
REPO_URL = "https://github.com/Bob56fr/openRemoteTRX"
PART = re.compile(r"^(\d\d)-[a-z0-9-]+\.md$")
UI = {
    "fr": {"progress": "{n} / {m} étapes cochées", "reset": "Tout décocher", "print": "Imprimer",
           "saved": "Les cases cochées sont gardées dans ce navigateur.",
           "unsaved": "Ce navigateur ne garde pas les cases : imprime la page pour garder une trace.",
           "source": "Source de ce guide sur GitHub", "footer": "Projet libre (AGPL-3.0-or-later)",
           "top": "Haut de page"},
}

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
footer{margin-top:2.5rem;color:var(--doux);font-size:.9rem;border-top:1px solid var(--ligne);padding-top:.8rem}
@media print{
  :root{--fond:#fff;--carte:#fff;--ligne:#bbb;--texte:#000;--doux:#444;--code:#f3f3f3;color-scheme:light}
  .outils button,.haut,footer{display:none}
  a{color:#000}
  .partie{break-before:page}
}
"""

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
    var h = Math.ceil(document.documentElement.scrollHeight);
    if (h !== last) { last = h; window.parent.postMessage({ type: "trx-doc-height", height: h }, "*"); }
  }
  window.addEventListener("load", send);
  if (window.ResizeObserver) new ResizeObserver(send).observe(document.body);
  else window.addEventListener("resize", send);
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
    ordered: list[Path] = [folder / "README.md"]
    for part in parts:
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
    return "p-" + rel.stem[:2]


class Renderer:
    def __init__(self, lang: str, path: Path, anchors: dict[Path, str]) -> None:
        self.lang, self.path, self.anchors = lang, path, anchors
        self.file_anchor = anchors[path.resolve()]
        self.boxes = 0
        self.section = 0
        self.heading_ids: set[str] = set()

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
            return "#" + (frag or self.anchors[resolved]), False
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

    def table(self, rows: list[str]) -> str:
        def cells(row: str) -> list[str]:
            return [c.strip() for c in row.strip().strip("|").split("|")]

        head = cells(rows[0])
        out = ['<div class="table"><table><thead><tr>' + "".join(f"<th>{self.inline(c)}</th>" for c in head)
               + "</tr></thead><tbody>"]
        for row in rows[2:]:
            out.append("<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in cells(row)) + "</tr>")
        return "".join(out) + "</tbody></table></div>"

    def render(self, lines: list[str]) -> str:
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
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
                danger = " danger" if quoted and quoted[0].startswith("**Sécurité") else ""
                out.append(f'<div class="note{danger}">' + self.render(quoted) + "</div>")
                i = j
                continue
            if re.match(r"^(-|\d+\.)\s", line):
                i = self.list_block(lines, i, out)
                continue
            j = i
            para = []
            while j < len(lines) and lines[j].strip() and not re.match(r"^(#{1,4}\s|```|\||>|-\s|\d+\.\s)",
                                                                        lines[j].strip()):
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


def render_page(lang: str) -> str:
    files = guide_files(lang)
    anchors = {p.resolve(): anchor_of(p, lang) for p in files}
    ui = UI[lang]
    body: list[str] = []
    title = ""
    total_boxes = 0
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or not lines[0].startswith("# "):
            raise GuideError(f"{path.name} : la première ligne doit être le titre (# …)")
        renderer = Renderer(lang, path, anchors)
        if anchors[path.resolve()] == "top":
            title = lines[0][2:].strip()
            body.append(f'<h1 id="top">{esc(title)}</h1>')
            body.append(renderer.render(lines[1:]))
            continue
        html_part = renderer.render(lines)
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
           "</main>", f"<script>{(SCRIPT % {'lang': lang}).strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def build() -> dict[Path, str]:
    pages: dict[Path, str] = {}
    for lang in LANGS:
        sub = SITE if lang == "fr" else SITE / lang
        pages[sub / "index.html"] = render_page(lang)
    return pages


def main() -> int:
    try:
        pages = build()
    except GuideError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(f"Écrit : {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
