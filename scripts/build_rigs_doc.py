# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Fabrique la page publique des postes essayés (GitHub Pages, thème sombre, iframe du site rf-diy.com).

Source : une fiche par poste dans `docs/postes/donnees/*.toml` (états venus d'essais réels). Aucune dépendance hors
stdlib. Résultat (une seule version, sans numéro de version de la station) :
  - `docs/site/postes/index.html` : tableau 1 (par poste : ce que propose Hamlib et ce qui est validé, partiel, en
    échec, non essayé, avec la section repliée « non exploité ») et tableau 2 (comparaison des postes : seulement le
    validé et le partiel), fonctions classées par thème, français / anglais ;
    puis la liste des postes à USB intégré (CAT et son), `docs/postes/usb-integre.toml` (documentation des
    fabricants, pas des essais) ;
  - `docs/site/postes/data.json` : les mêmes données, pour qui veut les lire (même origine que la page).
Usage : python scripts/build_rigs_doc.py   (après tout changement d'une fiche ; tests/test_rigs_doc.py le vérifie).
"""
from __future__ import annotations

import html
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_console_doc as base  # noqa: E402  (même style, même ajustement de hauteur dans l'iframe)

DATA = ROOT / "docs" / "postes" / "donnees"
USB_FILE = ROOT / "docs" / "postes" / "usb-integre.toml"
HAMLIB_ETATS = ("Stable", "Beta", "Alpha", "Untested")
SITE = ROOT / "docs" / "site"
FOLDER = "postes"
PAGES_URL = "https://bob56fr.github.io/openRemoteTRX/postes/"

THEMES = [
    ("securite", "Sécurité d'émission", "Transmit safety"),
    ("frequence", "Fréquence", "Frequency"),
    ("modes", "Modes et filtres", "Modes and filters"),
    ("reception", "Réception", "Receive"),
    ("emission", "Émission", "Transmit"),
    ("mesures", "Mesures", "Meters"),
    ("audio", "Audio USB", "USB audio"),
    ("spectre", "Spectre", "Spectrum"),
]
FEATURES = [   # (identifiant, thème, français, anglais)
    ("ptt_relu", "securite", "PTT par la CAT, état relu", "CAT PTT, state read back"),
    ("tot", "securite", "Coupure au bout du TOT", "Cut at the TOT"),
    ("battements", "securite", "Battements du client perdus", "Client heartbeats lost"),
    ("deconnexion", "securite", "Connexion du client fermée", "Client connection closed"),
    ("perte_cat", "securite", "Liaison CAT perdue pendant l'émission", "CAT link lost while transmitting"),
    ("hors_bande", "securite", "Refus hors des bandes autorisées", "Refusal outside the allowed bands"),
    ("operateur_local", "securite", "Opérateur sur place (micro du poste)", "Local operator (rig microphone)"),
    ("demarrage", "securite", "Réception au démarrage", "Receive at start-up"),
    ("frequence", "frequence", "Fréquence (écrite et relue)", "Frequency (written and read back)"),
    ("split", "frequence", "Split", "Split"),
    ("rit", "frequence", "RIT", "RIT"),
    ("xit", "frequence", "XIT / ΔTX", "XIT / ΔTX"),
    ("vfo", "frequence", "VFO actif lisible", "Active VFO readable"),
    ("modes_base", "modes", "Modes USB, LSB, CW, AM, FM", "USB, LSB, CW, AM, FM modes"),
    ("modes_donnees", "modes", "Modes données", "Data modes"),
    ("filtres", "modes", "Largeurs de filtre", "Filter widths"),
    ("preampli", "reception", "Préampli", "Preamp"),
    ("attenuateur", "reception", "Atténuateur", "Attenuator"),
    ("agc", "reception", "AGC", "AGC"),
    ("nr", "reception", "Réducteur de bruit (NR)", "Noise reduction (NR)"),
    ("nr_niveau", "reception", "Niveau du NR", "NR level"),
    ("nb", "reception", "Noise blanker (NB)", "Noise blanker (NB)"),
    ("nb_niveau", "reception", "Niveau du NB", "NB level"),
    ("anf", "reception", "Notch automatique (ANF)", "Auto notch (ANF)"),
    ("notch_manuel", "reception", "Notch manuel", "Manual notch"),
    ("squelch", "reception", "Squelch", "Squelch"),
    ("puissance", "emission", "Puissance réglée", "Power setting"),
    ("compresseur", "emission", "Compresseur", "Speech processor"),
    ("tuner", "emission", "Coupleur d'antenne", "Antenna tuner"),
    ("vox", "emission", "VOX (jamais proposé à distance)", "VOX (never offered remotely)"),
    ("s_metre", "mesures", "S-mètre", "S-meter"),
    ("puissance_mesuree", "mesures", "Puissance mesurée", "Measured power"),
    ("ros", "mesures", "ROS", "SWR"),
    ("alc", "mesures", "ALC", "ALC"),
    ("tension", "mesures", "Tension d'alimentation", "Supply voltage"),
    ("temperature", "mesures", "Température du poste", "Rig temperature"),
    ("audio_rx", "audio", "Son reçu par l'USB", "Receive audio over USB"),
    ("audio_tx", "audio", "Modulation par l'USB", "Modulation over USB"),
    ("spectre_hf", "spectre", "Spectre HF du poste", "Rig HF spectrum"),
]
ETATS = {   # état : (symbole, français, anglais)
    "valide": ("✓", "validé", "validated"),
    "partiel": ("◐", "partiel", "partial"),
    "echec": ("✗", "ne fonctionne pas", "does not work"),
    "non_teste": ("?", "non testé", "not tested"),
    "non_declare": ("·", "non disponible", "not available"),
}
NOTE_MARK = {"non_teste": "1", "non_declare": "2"}          # renvoi vers la note de bas de page
CAUSES = {   # qui empêche la fonction (état « non_declare ») : (français, anglais)
    "hamlib": ("Hamlib", "Hamlib"),
    "poste": ("le poste", "the rig"),
    "trx_distant": ("openRemoteTRX", "openRemoteTRX"),
}
FOOTNOTES = (
    ("(1) Non testé : la fonction existe peut-être, mais aucun essai réel ne l'a encore prouvée avec openRemoteTRX sur ce "
     "poste. Elle peut marcher ; tant qu'elle n'est pas essayée, on ne l'affirme pas.",
     "(1) Not tested: the feature may exist, but no real test has proved it yet with openRemoteTRX on this rig. It may "
     "work; until it is tested, we do not claim it."),
    ("(2) Non disponible : la fonction ne peut pas être utilisée à distance aujourd'hui, et la cause est indiquée : "
     "Hamlib (la bibliothèque qui parle au poste ne la propose pas pour ce modèle), le poste lui-même (sa liaison CAT "
     "ne la donne pas, ex. aucune donnée de spectre HF par la CAT du Yaesu FTDX10) ou openRemoteTRX (pas encore "
     "programmée). Une nouvelle version de Hamlib, du micrologiciel du poste ou d'openRemoteTRX peut la rendre disponible.",
     "(2) Not available: the feature cannot be used remotely today, and the cause is shown: Hamlib (the library that "
     "talks to the rig does not offer it for this model), the rig itself (its CAT link does not provide it, e.g. no HF "
     "spectrum data over the Yaesu FTDX10 CAT) or openRemoteTRX (not programmed yet). A new version of Hamlib, of the rig "
     "firmware or of openRemoteTRX may make it available."),
)
STATUTS = {"valide": ("validé", "validated"), "restreint": ("validé avec restrictions", "validated with restrictions"),
           "validation_en_cours": ("validation en cours", "validation in progress"), "refuse": ("refusé", "refused")}
COMPARED = ("valide", "restreint", "validation_en_cours")
STABILITES = {"ok": ("aucun défaut aléatoire pendant les essais", "no random fault during the tests"),
              "defauts": ("défauts constatés", "faults found")}
WEIGHTS = {"valide": 1.0, "partiel": 0.5, "echec": 0.0}
STARS_IF_FAULTS = 3.0                 # défauts aléatoires constatés : 3 étoiles au plus
NEEDS_NOTE = ("partiel", "echec")

EXTRA_CSS = """
[hidden]{display:none !important}
.en-t{display:none}body.en .fr-t{display:none}body.en .en-t{display:inline}
.choix button,.themes button{background:var(--carte);color:var(--texte);border:1px solid var(--ligne);border-radius:2rem;
  padding:.2rem .9rem;font:inherit;cursor:pointer;margin:.15rem}
.choix button[aria-pressed=true],.themes button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}
table{border-collapse:collapse;width:100%;margin:.4rem 0 1rem;font-size:.92rem}
th,td{border:1px solid var(--ligne);padding:.3rem .5rem;text-align:left;vertical-align:top}
th{background:var(--carte)}td.e{white-space:nowrap;font-weight:600}
tr.t th{background:transparent;color:var(--accent);font-size:1rem;padding-top:.8rem;border-left:0;border-right:0}
.e-valide{color:#7ed99a}.e-partiel{color:#f2d06b}.e-echec{color:#ff8a8a}.e-non_teste{color:#9cc8f2}.e-non_declare{opacity:.6}
.etoiles{color:#f2c94c;letter-spacing:.08em}.note-etoiles{font-size:1.05rem;margin:.2rem 0}
.note-detail{margin:.2rem 0 .6rem;font-size:.9rem}
.statut{display:inline-block;border-radius:1rem;padding:0 .6rem;font-size:.8rem;background:#3d3418;color:#f2d06b}
.statut.s-valide{background:#183d26;color:#7ed99a}.statut.s-refuse{background:#3d1818;color:#ff8a8a}
.wrap{overflow-x:auto}details{margin:.4rem 0 1rem}
section.poste{background:var(--carte);border:1px solid var(--ligne);border-radius:.6rem;padding:.4rem 1rem .8rem;margin:1rem 0}
"""
PAGE_JS = """
(function () {
  function lang(l) {
    document.body.classList.toggle("en", l === "en");
    document.querySelectorAll(".choix button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.l === l)); });
    try { localStorage.setItem("trx-postes-langue", l); } catch (e) {}
  }
  document.querySelectorAll(".choix button").forEach(function (b) { b.addEventListener("click", function () { lang(b.dataset.l); }); });
  var saved = null; try { saved = localStorage.getItem("trx-postes-langue"); } catch (e) {}
  lang(saved || (/^fr/i.test(navigator.language || "fr") ? "fr" : "en"));
  function theme(t) {
    document.querySelectorAll("[data-theme]").forEach(function (r) { r.hidden = t !== "tous" && r.dataset.theme !== t; });
    document.querySelectorAll(".themes button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.t === t)); });
  }
  document.querySelectorAll(".themes button").forEach(function (b) { b.addEventListener("click", function () { theme(b.dataset.t); }); });
  theme("tous");
})();
"""


class DocError(Exception):
    pass


def load_usb(path: Path = USB_FILE) -> dict:
    """Postes potentiellement compatibles (documentation des fabricants, pas des essais) : `usb` = CAT et son par un
    seul câble USB, `cat_seule` = USB pour la CAT, son par une interface externe."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def check_usb(usb: dict, rigs: list[dict]) -> None:
    """Liste cohérente, sinon DocError : champs, numéros Hamlib uniques, fiche existante et de même numéro, tout poste
    essayé présent dans la liste."""
    problems, seen = [], set()
    fiches = {r["id"]: r for r in rigs}
    if not usb.get("hamlib_version"):
        problems.append("usb-integre.toml : hamlib_version manquant")
    for group in ("usb", "cat_seule"):
        for e in usb.get(group, []):
            name = f"usb-integre.toml [{group}] {e.get('fabricant', '?')} {e.get('modele', '?')}"
            for key in ("fabricant", "modele", "hamlib_model", "hamlib_etat"):
                if key not in e:
                    problems.append(f"{name} : {key} manquant")
            if not isinstance(e.get("hamlib_model"), int):
                problems.append(f"{name} : hamlib_model doit être un nombre")
            elif e["hamlib_model"] in seen:
                problems.append(f"{name} : numéro Hamlib {e['hamlib_model']} en double")
            seen.add(e.get("hamlib_model"))
            if e.get("hamlib_etat") not in HAMLIB_ETATS:
                problems.append(f"{name} : hamlib_etat inconnu {e.get('hamlib_etat')!r} ({', '.join(HAMLIB_ETATS)})")
            if bool(e.get("remarque")) != bool(e.get("remarque_en")):
                problems.append(f"{name} : remarque et remarque_en vont ensemble")
            if "fiche" in e:
                rig = fiches.get(e["fiche"])
                if rig is None:
                    problems.append(f"{name} : fiche inconnue {e['fiche']!r}")
                elif rig["poste"].get("hamlib_model") != e.get("hamlib_model"):
                    problems.append(f"{name} : numéro Hamlib différent de la fiche {e['fiche']}")
    for rig in rigs:
        if rig["poste"].get("hamlib_model") not in seen:
            problems.append(f"{rig['id']} : poste essayé absent de usb-integre.toml")
    if not usb.get("usb"):
        problems.append("usb-integre.toml : aucun poste [[usb]]")
    if problems:
        raise DocError("\n".join(problems))


def load_rigs(folder: Path = DATA) -> list[dict]:
    rigs = []
    for path in sorted(folder.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        data["id"] = path.stem
        rigs.append(data)
    return rigs


def check(rigs: list[dict]) -> None:
    """Fiches cohérentes, sinon DocError (rien n'est écrit)."""
    known = {f[0] for f in FEATURES}
    problems = []
    for rig in rigs:
        name, poste = rig["id"], rig.get("poste", {})
        for key in ("fabricant", "modele", "hamlib_model", "statut", "resume", "resume_en"):
            if key not in poste:
                problems.append(f"{name} : [poste] {key} manquant")
        if poste.get("statut") not in STATUTS:
            problems.append(f"{name} : statut inconnu {poste.get('statut')!r}")
        if "stabilite" in poste and poste["stabilite"] not in STABILITES:
            problems.append(f"{name} : stabilite inconnue {poste['stabilite']!r} ({', '.join(STABILITES)})")
        if poste.get("stabilite") == "defauts" and not (poste.get("stabilite_note") and poste.get("stabilite_note_en")):
            problems.append(f"{name} : stabilite « defauts » exige stabilite_note et stabilite_note_en")
        if not rig.get("essais"):
            problems.append(f"{name} : aucun essai ([[essais]])")
        funcs = rig.get("fonctions", {})
        for fid, entry in funcs.items():
            if fid not in known:
                problems.append(f"{name} : fonction inconnue {fid!r} (liste FEATURES de scripts/build_rigs_doc.py)")
            elif entry.get("etat") not in ETATS:
                problems.append(f"{name} : {fid} : état inconnu {entry.get('etat')!r}")
            elif entry["etat"] in NEEDS_NOTE and not (entry.get("note") and entry.get("note_en")):
                problems.append(f"{name} : {fid} : un état « {entry['etat']} » exige note et note_en")
            elif entry["etat"] == "non_declare" and entry.get("cause") not in CAUSES:
                problems.append(f"{name} : {fid} : « non disponible » exige une cause ({', '.join(CAUSES)})")
        missing = known - set(funcs)
        if missing:
            problems.append(f"{name} : fonctions sans état : {', '.join(sorted(missing))}")
        if poste.get("statut") in ("valide", "restreint"):
            unsafe = [f[0] for f in FEATURES if f[1] == "securite" and funcs.get(f[0], {}).get("etat") != "valide"]
            if unsafe:
                problems.append(f"{name} : statut {poste['statut']} impossible, sécurité non validée : {', '.join(unsafe)}")
    if problems:
        raise DocError("\n".join(problems))


def rating(rig: dict) -> dict:
    """Note « fonctionne avec openRemoteTRX » : `stars` (0 à 5 par demi-étoile, None tant que la sécurité d'émission n'est
    pas entièrement validée ou que la stabilité n'est pas déclarée), `provisional` (fonctions pas encore testées),
    `counted` / `valid` (fonctions comptées / validées), `absent` (absentes du POSTE, non comptées), `limits` (limites de
    Hamlib ou d'openRemoteTRX, comptées ½), `untested`."""
    funcs = rig["fonctions"]
    absent, limits, untested, points, counted, valid = [], [], [], 0.0, 0, 0
    for fid, theme, fr, en in FEATURES:
        entry = funcs[fid]
        etat = entry["etat"]
        if etat == "non_declare" and entry.get("cause") == "poste":
            absent.append((fr, en))
            continue
        if etat == "non_teste":
            untested.append((fr, en))
            continue
        counted += 1
        if etat == "non_declare":
            limits.append((fr, en))
            points += 0.5
        else:
            points += WEIGHTS[etat]
            valid += etat == "valide"
    safe = all(funcs[f]["etat"] == "valide" for f, theme, *_ in FEATURES if theme == "securite")
    stability = rig["poste"].get("stabilite")
    stars = None
    if safe and stability in STABILITES and counted:
        stars = round(points / counted * 5 * 2) / 2
        if stability == "defauts":
            stars = min(stars, STARS_IF_FAULTS)
    return {"stars": stars, "provisional": bool(untested), "counted": counted, "valid": valid, "absent": absent,
            "limits": limits, "untested": untested, "safe": safe, "stability": stability}


def _stars(value: float) -> str:
    full = int(value)
    half = value - full >= 0.5
    return "★" * full + ("½" if half else "") + "☆" * (5 - full - half)


def _rating_html(rig: dict) -> list[str]:
    r = rating(rig)
    if r["stars"] is None:
        why = (_bi("note attendue : sécurité d'émission pas encore entièrement validée",
                   "rating pending: transmit safety not fully validated yet") if not r["safe"] else
               _bi("note attendue : stabilité pas encore évaluée", "rating pending: stability not assessed yet"))
        return [f'<p class="note-etoiles">{why}</p>']
    head = f'<span class="etoiles" title="{r["stars"]:g}/5">{_stars(r["stars"])}</span> {r["stars"]:g}/5'
    if r["provisional"]:
        head += " " + _bi(f"(provisoire : {len(r['untested'])} fonction(s) pas encore testée(s))",
                          f"(provisional: {len(r['untested'])} feature(s) not tested yet)")
    out = [f'<p class="note-etoiles">{head}</p>', "<ul class=\"note-detail\">",
           f'<li>{_bi(f"Fonctions utilisées par openRemoteTRX : {r["valid"]} sur {r["counted"]} validées.", f"Features used by openRemoteTRX: {r["valid"]} of {r["counted"]} validated.")}</li>']
    if r["absent"]:
        out.append("<li>" + _bi("Absent du poste (choix du constructeur, non compté) : " + ", ".join(fr for fr, _ in r["absent"]) + ".",
                                "Missing from the rig (manufacturer's choice, not counted): " + ", ".join(en for _, en in r["absent"]) + ".") + "</li>")
    if r["limits"]:
        out.append("<li>" + _bi("Limites de Hamlib ou d'openRemoteTRX (comptées ½) : " + ", ".join(fr for fr, _ in r["limits"]) + ".",
                                "Hamlib or openRemoteTRX limits (counted ½): " + ", ".join(en for _, en in r["limits"]) + ".") + "</li>")
    sfr, sen = STABILITES[r["stability"]]
    note = rig["poste"].get("stabilite_note", "")
    out.append("<li>" + _bi(f"Stabilité : {sfr}" + (f" ({note})" if note else "") + ".",
                            f"Stability: {sen}" + (f" ({rig['poste'].get('stabilite_note_en', note)})" if note else "") + ".") + "</li>")
    out.append("</ul>")
    return out


def _bi(fr: str, en: str) -> str:
    e = html.escape
    return f'<span class="fr-t">{e(fr)}</span><span class="en-t">{e(en)}</span>'


def _anchor(rig_id: str, fid: str) -> str:
    return f"p-{rig_id}-{fid}"


def number_partials(rigs: list[dict]) -> dict[tuple[str, str], int]:
    """Renvoi numéroté (à partir de 3) de chaque fonction « partiel » ou « ne fonctionne pas » : la note de bas de fiche
    dit ce qui ne marche pas (demande de l'utilisateur, 2026-11-19)."""
    marks, n = {}, len(FOOTNOTES)
    for rig in rigs:
        for fid, *_ in FEATURES:
            if rig["fonctions"][fid]["etat"] in NEEDS_NOTE:
                n += 1
                marks[(rig["id"], fid)] = n
    return marks


def _label(entry: dict, mark: tuple[str, int] | None = None) -> str:
    """Libellé d'un état, renvoi de note en exposant et cause d'une fonction non disponible. `mark` : (ancre, numéro)
    d'une fonction partielle ou en échec."""
    etat = entry["etat"]
    sym, fr, en = ETATS[etat]
    text = f"{sym} {_bi(fr, en)}"
    if mark is not None:
        text += f'<sup><a href="#{mark[0]}">({mark[1]})</a></sup>'
    if etat in NOTE_MARK:
        text += f'<sup><a href="#note{NOTE_MARK[etat]}">({NOTE_MARK[etat]})</a></sup>'
    if etat == "non_declare" and entry.get("cause") in CAUSES:
        cfr, cen = CAUSES[entry["cause"]]
        text += " (" + _bi(cfr, cen) + ")"
    return text


def _etat(entry: dict, mark: tuple[str, int] | None = None) -> str:
    return f'<td class="e e-{entry["etat"]}">{_label(entry, mark)}</td>'


def _footnotes(anchor: bool) -> str:
    return ('<div class="notes">' + "".join(
        f'<p{f" id=note{i}" if anchor else ""}><small>{_bi(fr, en)}</small></p>'
        for i, (fr, en) in enumerate(FOOTNOTES, 1)) + "</div>")


def _rig_title(rig: dict) -> str:
    p = rig["poste"]
    fr, en = STATUTS[p["statut"]]
    return (f'{html.escape(p["fabricant"])} {html.escape(p["modele"])} '
            f'<span class="statut s-{p["statut"]}">{_bi(fr, en)}</span>')


def _table1(rig: dict, marks: dict | None = None) -> list[str]:
    funcs = rig["fonctions"]
    marks = marks if marks is not None else number_partials([rig])
    partials: list[tuple[int, str, str, str, str]] = []
    out = [f'<section class="poste" id="{html.escape(rig["id"])}">', f"<h3>{_rig_title(rig)}</h3>", *_rating_html(rig),
           f'<p>{_bi(rig["poste"]["resume"], rig["poste"]["resume_en"])} '
           f'{_bi("Modèle Hamlib", "Hamlib model")} {rig["poste"]["hamlib_model"]}.</p>',
           "<p>" + "<br>".join(
               f'{html.escape(e["date"])} · {_bi("station", "station")} {html.escape(e["station"])} · Hamlib '
               f'{html.escape(e["hamlib"])} · {html.escape(e["systeme"])} : {_bi(e["quoi"], e.get("quoi_en", e["quoi"]))}'
               for e in rig["essais"]) + "</p>",
           '<div class="wrap"><table>',
           f'<tr><th>{_bi("Fonction", "Feature")}</th><th>Hamlib</th><th>{_bi("openRemoteTRX", "openRemoteTRX")}</th>'
           f'<th>{_bi("Remarque", "Note")}</th></tr>']
    for tid, tfr, ten in THEMES:
        out.append(f'<tr class="t" data-theme="{tid}"><th colspan="4">{_bi(tfr, ten)}</th></tr>')
        for fid, theme, fr, en in FEATURES:
            if theme != tid:
                continue
            entry = funcs[fid]
            declared = entry["etat"] != "non_declare"
            note = entry.get("note", "")
            number = marks.get((rig["id"], fid))
            mark = (_anchor(rig["id"], fid), number) if number else None
            if mark:
                partials.append((number, mark[0], fr, en, fid))
            out.append(f'<tr data-theme="{tid}"><td>{_bi(fr, en)}</td>'
                       f'<td>{_bi("proposé" if declared else "non proposé", "offered" if declared else "not offered")}</td>'
                       f'{_etat(entry, mark)}<td>{_bi(note, entry.get("note_en", note))}</td></tr>')
    out.append("</table></div>")
    if partials:                                     # ce qui ne marche pas, fonction par fonction
        out.append('<div class="notes">')
        for number, anchor, fr, en, fid in partials:
            entry = funcs[fid]
            sym, efr, een = ETATS[entry["etat"]]
            out.append(f'<p id="{anchor}"><small>({number}) {_bi(fr, en)}, {_bi(efr, een)} : '
                       f'{_bi(entry["note"], entry["note_en"])}</small></p>')
        out.append("</div>")
    hamlib = rig.get("hamlib", {})
    if hamlib.get("non_exploite"):
        out += ["<details>", f'<summary>{_bi("Proposé par Hamlib, non exploité par openRemoteTRX", "Offered by Hamlib, not used by openRemoteTRX")}'
                f' ({len(hamlib["non_exploite"])})</summary>',
                "<p>" + ", ".join(f"<code>{html.escape(n)}</code>" for n in hamlib["non_exploite"]) + "</p>", "</details>"]
    if hamlib.get("constats"):
        en = hamlib.get("constats_en", hamlib["constats"])
        out += [f'<p><strong>{_bi("Constats sur Hamlib", "Hamlib findings")}</strong></p>', "<ul>"]
        out += [f"<li>{_bi(fr, e)}</li>" for fr, e in zip(hamlib["constats"], en)]
        out.append("</ul>")
    out.append("</section>")
    return out


def _table2(rigs: list[dict], marks: dict | None = None) -> list[str]:
    shown = [r for r in rigs if r["poste"]["statut"] in COMPARED]
    if not shown:
        return [f'<p>{_bi("Aucun poste à comparer pour l’instant.", "No rig to compare yet.")}</p>']
    def stars_of(r):
        note = rating(r)
        if note["stars"] is None:
            return f'<br><small>{_bi("note attendue", "rating pending")}</small>'
        extra = f' <small>{_bi("provisoire", "provisional")}</small>' if note["provisional"] else ""
        return f'<br><span class="etoiles">{_stars(note["stars"])}</span> {note["stars"]:g}/5{extra}'
    head = "".join(f'<th><a href="#{html.escape(r["id"])}">{html.escape(r["poste"]["fabricant"])} '
                   f'{html.escape(r["poste"]["modele"])}</a>{stars_of(r)}</th>' for r in shown)
    out = ['<div class="wrap"><table>', f'<tr><th>{_bi("Fonction", "Feature")}</th>{head}</tr>']
    for tid, tfr, ten in THEMES:
        out.append(f'<tr class="t" data-theme="{tid}"><th colspan="{len(shown) + 1}">{_bi(tfr, ten)}</th></tr>')
        for fid, theme, fr, en in FEATURES:
            if theme != tid:
                continue
            cells = []
            for r in shown:
                entry = r["fonctions"][fid]
                note = entry.get("note", "")
                number = (marks or {}).get((r["id"], fid))
                mark = (_anchor(r["id"], fid), number) if number else None
                cells.append(f'<td class="e e-{entry["etat"]}" title="{html.escape(note)}">{_label(entry, mark)}</td>')
            out.append(f'<tr data-theme="{tid}"><td>{_bi(fr, en)}</td>{"".join(cells)}</tr>')
    out.append("</table></div>")
    out.append(_footnotes(anchor=True))
    return out


def _usb_tables(usb: dict, rigs: list[dict]) -> list[str]:
    fiches = {r["id"]: r for r in rigs}

    def rows(entries: list[dict], with_status: bool) -> list[str]:
        out = []
        for e in sorted(entries, key=lambda x: (x["fabricant"].lower(), x["modele"].lower())):
            note = _bi(e["remarque"], e["remarque_en"]) if e.get("remarque") else ""
            if e.get("a_confirmer"):
                note = (note + " " if note else "") + _bi("USB audio à confirmer.", "USB audio to be confirmed.")
            cells = [html.escape(e["fabricant"]), html.escape(e["modele"]), str(e["hamlib_model"]),
                     html.escape(e["hamlib_etat"])]
            if with_status:
                rig = fiches.get(e.get("fiche", ""))
                if rig:
                    fr, en = STATUTS[rig["poste"]["statut"]]
                    cells.append(f'<a href="#{html.escape(rig["id"])}"><span class="statut s-{rig["poste"]["statut"]}">'
                                 f'{_bi(fr, en)}</span></a>')
                else:
                    cells.append(_bi("non essayé", "not tried"))
            cells.append(note)
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        return out

    head = (f'<tr><th>{_bi("Marque", "Brand")}</th><th>{_bi("Modèle", "Model")}</th>'
            f'<th>{_bi("N° Hamlib", "Hamlib #")}</th>'
            f'<th>{_bi("Pilote Hamlib", "Hamlib driver")} {html.escape(usb["hamlib_version"])}</th>')
    out = [f'<h2 id="usb">{_bi("Postes à USB intégré (CAT et son)", "Rigs with built-in USB (CAT and audio)")}</h2>',
           "<p>" + _bi("Un seul câble USB entre le poste et la station : port série pour la CAT et carte son du poste. "
                       "Liste établie d’après la documentation des fabricants, PAS d’après des essais : un poste "
                       "« non essayé » est potentiellement compatible, rien de plus (sécurité d’émission, PTT par la CAT "
                       "et son restent à vérifier sur charge fictive). Une erreur ou un oubli : ouvrez un ticket.",
                       "One USB cable between the rig and the station: serial port for CAT and the rig’s sound card. "
                       "List based on the manufacturers’ documentation, NOT on tests: a “not tried” rig is potentially "
                       "compatible, nothing more (transmit safety, CAT PTT and audio still to be checked on a dummy "
                       "load). An error or a missing rig: open an issue.") + "</p>",
           '<div class="wrap"><table>', head + f'<th>openRemoteTRX</th><th>{_bi("Remarque", "Note")}</th></tr>',
           *rows(usb["usb"], True), "</table></div>"]
    if usb.get("cat_seule"):
        out += [f'<h3>{_bi("USB pour la CAT seulement", "USB for CAT only")}</h3>',
                "<p>" + _bi("Le son passe par une interface externe (Digirig, SignaLink…) : possible, mais pas en un "
                            "seul câble.",
                            "Audio goes through an external interface (Digirig, SignaLink…): possible, but not with a "
                            "single cable.") + "</p>",
                '<div class="wrap"><table>', head + f'<th>{_bi("Remarque", "Note")}</th></tr>',
                *rows(usb["cat_seule"], False), "</table></div>"]
    out.append("<p>" + _bi("Tout autre poste reconnu par Hamlib peut fonctionner avec une interface CAT et une "
                           "interface son externes.",
                           "Any other rig supported by Hamlib can work with external CAT and audio interfaces.") + "</p>")
    return out


def render(rigs: list[dict], usb: dict | None = None) -> str:
    usb = usb if usb is not None else load_usb()
    themes = "".join(f'<button type="button" data-t="{t}">{_bi(fr, en)}</button>' for t, fr, en in THEMES)
    legend = " · ".join(f'<span class="e-{k}">{v[0]}</span> {_bi(v[1], v[2])}' for k, v in ETATS.items())
    out = ["<!doctype html>", "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->", "<!-- Copyright (C) 2026 RF-DIY.COM -->",
           "<!-- Fabriqué par scripts/build_rigs_doc.py depuis docs/postes/donnees/ : ne pas modifier à la main. -->",
           '<html lang="fr">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           "<title>Postes essayés avec openRemoteTRX</title>",
           f"<style>{base.CSS.strip()}{EXTRA_CSS.strip()}</style>", "</head>", "<body>", "<main>",
           '<p class="choix"><button type="button" data-l="fr">Français</button><button type="button" data-l="en">English</button></p>',
           f'<h1>{_bi("Postes essayés avec openRemoteTRX", "Rigs tried with openRemoteTRX")}</h1>',
           "<p>" + _bi("Chaque état vient d’un essai réel sur le poste (qualification, charge fictive). Un résultat vaut pour "
                       "la version de Hamlib et le système indiqués.",
                       "Every state comes from a real test on the rig (qualification, dummy load). A result holds for the "
                       "Hamlib version and system shown.") + "</p>",
           "<p>" + _bi("Postes pas encore essayés : voir la liste des ", "Rigs not tried yet: see the list of ")
           + f'<a href="#usb">{_bi("postes à USB intégré", "rigs with built-in USB")}</a>.</p>',
           f"<p>{legend}</p>",
           f'<p class="themes"><button type="button" data-t="tous">{_bi("Tous les thèmes", "All topics")}</button>{themes}</p>',
           f'<h2>{_bi("Comparaison des postes", "Rig comparison")}</h2>',
           "<p>" + _bi("Postes validés ou en cours de validation ; le détail de chaque case est dans la fiche du poste "
                       "(survol d'une case = remarque).",
                       "Validated rigs or rigs being validated; each cell is detailed in the rig sheet (hover a cell = "
                       "note).") + "</p>"]
    marks = number_partials(rigs)
    out += _table2(rigs, marks)
    out.append(f'<h2>{_bi("Fiche de chaque poste : Hamlib et openRemoteTRX", "Each rig: Hamlib and openRemoteTRX")}</h2>')
    for rig in rigs:
        out += _table1(rig, marks)
    out.append(_footnotes(anchor=False))
    out += _usb_tables(usb, rigs)
    out += ["<footer>",
            f'<p><a href="../erreurs/">{_bi("Codes d’erreur", "Error codes")}</a> · <a href="../guide/">'
            f'{_bi("Guide de l’opérateur", "Operator guide")}</a> · <a href="data.json">data.json</a> · '
            f'<a href="{base.REPO_URL}" target="_blank" rel="noopener noreferrer">{_bi("code source", "source code")}</a> · '
            f'<a href="{base.SITE_URL}" target="_blank" rel="noopener noreferrer">rf-diy.com</a></p>',
            "</footer>", "</main>", f"<script>{base.RESIZE_JS.strip()}{PAGE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def data_json(rigs: list[dict], usb: dict | None = None) -> str:
    usb = usb if usb is not None else load_usb()
    out = {"format": 1, "page": PAGES_URL,
           "themes": [{"id": t, "fr": fr, "en": en} for t, fr, en in THEMES],
           "fonctions": [{"id": f, "theme": t, "fr": fr, "en": en} for f, t, fr, en in FEATURES],
           "etats": {k: {"fr": v[1], "en": v[2]} for k, v in ETATS.items()},
           "postes": [{**{k: v for k, v in r.items()}, "note": {k: v for k, v in rating(r).items()
                                                                  if k in ("stars", "provisional", "counted", "valid")}}
                      for r in rigs],
           "usb_integre": usb}
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


def build(site: Path = SITE, rigs: list[dict] | None = None) -> dict[Path, str]:
    rigs = rigs if rigs is not None else load_rigs()
    check(rigs)
    usb = load_usb()
    check_usb(usb, rigs)
    return {site / FOLDER / "index.html": render(rigs, usb), site / FOLDER / "data.json": data_json(rigs, usb)}


def stale_pages(site: Path = SITE) -> list[Path]:
    return [p for p, text in build(site).items()
            if not p.exists() or p.read_bytes().replace(b"\r\n", b"\n") != text.encode("utf-8")]


def main() -> int:
    try:
        pages = build()
    except DocError as exc:
        print("Page des postes NON fabriquée :\n" + str(exc), file=sys.stderr)
        return 1
    written = 0
    for path, text in pages.items():
        data = text.encode("utf-8")
        if path.exists() and path.read_bytes().replace(b"\r\n", b"\n") == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written += 1
    print(f"{written} fichier(s) écrit(s) sur {len(pages)} dans {(SITE / FOLDER).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
