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
    puis les PRÉQUALIFICATIONS en cours (`docs/postes/autotest/*.toml`, rapports de l'Autotest importés par
    `scripts/import_autotest.py`), à part : elles ne changent ni les fiches ni les notes ;
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
AUTOTEST = ROOT / "docs" / "postes" / "autotest"      # préqualifications (scripts/import_autotest.py), étape 374
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
NEEDS_NOTE = ("partiel", "echec")

# Préqualifications par l'openRemoteTRX-Autotest (décision de l'utilisateur du 2026-11-23, étape 374) : montrées À
# PART, pour que le visiteur voie qu'un poste est en cours d'essai ; elles ne changent JAMAIS une fiche ni une note.
# Essais : mêmes codes et libellés que `STEPS` de autotest/web/runner.js (vérifié par les tests).
AUTOTEST_STEPS = [
    ("R1", "Port et vitesse", "Port and speed"), ("R2", "Modèle identifié", "Model identified"),
    ("R3", "Fréquence et mode lus", "Frequency and mode read"), ("R4", "S-mètre", "S-meter"),
    ("R5", "Temps de réponse", "Response time"), ("R6", "PTT lu", "PTT read"),
    ("R7", "Carte son du poste", "Radio sound card"),
    ("R8", "Écriture de fréquence et de mode", "Frequency and mode writing"),
    ("R9", "Fonctions du poste (ATT, P.AMP, NB, NR, RIT, split, VFO…)",
     "Radio functions (ATT, P.AMP, NB, NR, RIT, split, VFO…)"),
    ("R10", "Spectre (waterfall du poste)", "Spectrum (the radio's waterfall)"),
    ("E1", "Émission par la CAT", "CAT transmit"), ("E2", "Puissance lue", "Power read"),
    ("E3", "TOS lu", "SWR read"), ("E4", "Tonalité 1 kHz", "1 kHz tone"), ("E6", "STOP de la page", "Page STOP"),
    ("E7", "Accord du coupleur d'antenne", "Antenna tuner tuning"),
    ("RS", "Remise de l'état d'origine", "Original state restored"),
]
AUTOTEST_ETATS = {   # statut du rapport : (symbole, classe d'état de la page, français, anglais)
    "ok": ("✓", "valide", "réussi", "passed"),
    "avert": ("◐", "partiel", "à vérifier", "to check"),
    "echec": ("✗", "echec", "échec", "failed"),
    "na": ("·", "non_declare", "non disponible", "not available"),
    "saute": ("–", "non_teste", "sauté", "skipped"),
    "absent": ("?", "non_teste", "pas encore fait", "not done yet"),
}
AUTOTEST_SOURCES = {"projet": ("essai du projet", "project test"),
                    "utilisateur": ("rapport d'un utilisateur", "user report")}
AUTOTEST_MODES = {"A": ("mode A, navigateur sans Hamlib", "mode A, browser without Hamlib"),
                  "B": ("mode B, utilitaire avec Hamlib", "mode B, utility with Hamlib")}
AUTOTEST_ARRETS = {"stop": ("essais arrêtés par l'opérateur (STOP)", "tests stopped by the operator (STOP)")}
AUTOTEST_REQUIRED = ("fabricant", "modele", "date", "outil", "mode", "systeme", "source", "empreinte_trace",
                     "resume", "resume_en")

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
.note-verdict{font-size:1.05rem;margin:.2rem 0}
.verdict{display:inline-block;border-radius:1rem;padding:0 .6rem;font-size:.85rem;font-weight:700;white-space:nowrap}
.v-go{background:#183d26;color:#7ed99a}.v-nogo{background:#3d1818;color:#ff8a8a}.v-encours{background:#1c2c40;color:#9cc8f2}
.v-pre{background:#262a33;color:var(--doux);font-weight:600}
.barre{display:inline-flex;align-items:flex-end;gap:2px;height:1em;vertical-align:-.1em}
.barre i{display:block;width:.42em;border-radius:1px;background:#2f3a4b}
.barre i:nth-child(1){height:28%}.barre i:nth-child(2){height:46%}.barre i:nth-child(3){height:64%}
.barre i:nth-child(4){height:82%}.barre i:nth-child(5){height:100%}
.barre i.on:nth-child(1){background:#2f7a4a}.barre i.on:nth-child(2){background:#3a9a5c}
.barre i.on:nth-child(3){background:#47b86d}.barre i.on:nth-child(4){background:#5cd683}.barre i.on:nth-child(5){background:#7ef0a0}
.niveau{white-space:nowrap;font-size:.92rem}
.resume{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:.6rem 0}
.resume>div{background:var(--carte);border:1px solid var(--ligne);border-radius:.6rem;padding:.2rem 1rem .6rem}
.resume h2{font-size:1.1rem;margin:.5rem 0}.resume ul{list-style:none;padding:0;margin:0}.resume li{margin:.45rem 0}
@media (max-width:700px){.resume{grid-template-columns:1fr}}
details.poste>summary,details.bloc>summary{cursor:pointer}details.poste>summary h3,details.bloc>summary h2{display:inline}
details.poste>summary .note-verdict{margin:.3rem 0 .1rem}
.note-detail{margin:.2rem 0 .6rem;font-size:.9rem}
.statut{display:inline-block;border-radius:1rem;padding:0 .6rem;font-size:.8rem;background:#3d3418;color:#f2d06b}
.statut.s-valide{background:#183d26;color:#7ed99a}.statut.s-refuse{background:#3d1818;color:#ff8a8a}
.wrap{overflow-x:auto}details{margin:.4rem 0 1rem}
section.poste,details.poste{background:var(--carte);border:1px solid var(--ligne);border-radius:.6rem;padding:.4rem 1rem .8rem;margin:1rem 0}
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
  // Fiches repliées (étape 376) : un lien interne ouvre le bloc qui contient sa cible ; tout s'ouvre à l'impression.
  function reveal(id) {
    var el = id && document.getElementById(id);
    if (!el) return false;
    for (var p = el; p; p = p.parentElement) if (p.tagName === "DETAILS") p.open = true;
    el.scrollIntoView();
    if (window.parent !== window)
      window.parent.postMessage({ type: "trx-doc-scroll", top: Math.round(el.getBoundingClientRect().top + window.scrollY) }, "*");
    return true;
  }
  function fromHash() { reveal(decodeURIComponent(location.hash.slice(1))); }
  window.addEventListener("load", fromHash);
  window.addEventListener("hashchange", fromHash);
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a) return;
    var id = decodeURIComponent(a.getAttribute("href").slice(1));
    if (reveal(id)) { e.preventDefault(); try { history.replaceState(null, "", "#" + id); } catch (x) {} }
  });
  window.addEventListener("beforeprint", function () { document.querySelectorAll("details").forEach(function (d) { d.open = true; }); });
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


def load_autotest(folder: Path = AUTOTEST) -> list[dict]:
    """Préqualifications, la plus récente d'abord ; `id` = nom du fichier."""
    reports = []
    for path in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        data["id"] = path.stem
        reports.append(data)
    reports.sort(key=lambda r: (r.get("rapport", {}).get("date", ""), r.get("rapport", {}).get("heure_utc", "")),
                 reverse=True)
    return reports


def check_autotest(reports: list[dict]) -> None:
    """Préqualifications complètes, bilingues et différentes, sinon DocError."""
    codes = {c for c, *_ in AUTOTEST_STEPS}
    problems, seen = [], {}
    for rep in reports:
        name, r = rep["id"], rep.get("rapport", {})
        for key in AUTOTEST_REQUIRED:
            if not r.get(key):
                problems.append(f"autotest/{name} : [rapport] {key} manquant ou vide")
        if r.get("source") and r["source"] not in AUTOTEST_SOURCES:
            problems.append(f"autotest/{name} : source inconnue {r['source']!r}")
        if r.get("mode") and r["mode"] not in AUTOTEST_MODES:
            problems.append(f"autotest/{name} : mode inconnu {r['mode']!r}")
        if r.get("arret") and r["arret"] not in AUTOTEST_ARRETS:
            problems.append(f"autotest/{name} : arrêt inconnu {r['arret']!r}")
        digest = r.get("empreinte_trace")
        if digest in seen:
            problems.append(f"autotest/{name} : même trace que {seen[digest]} (rapport en double)")
        seen[digest] = name
        if not rep.get("essais"):
            problems.append(f"autotest/{name} : aucun essai")
        done = set()
        for e in rep.get("essais", []):
            code = e.get("code")
            if code not in codes:
                problems.append(f"autotest/{name} : essai inconnu {code!r}")
            elif code in done:
                problems.append(f"autotest/{name} : essai {code} en double")
            done.add(code)
            if e.get("statut") not in AUTOTEST_ETATS or e.get("statut") == "absent":
                problems.append(f"autotest/{name} : {code} : statut inconnu {e.get('statut')!r}")
            if not e.get("texte") or not e.get("texte_en"):
                problems.append(f"autotest/{name} : {code} : texte et texte_en obligatoires")
            if bool(e.get("note")) != bool(e.get("note_en")):
                problems.append(f"autotest/{name} : {code} : note et note_en vont ensemble")
    if problems:
        raise DocError("\n".join(problems))


def _autotest_section(reports: list[dict]) -> list[str]:
    out = [f'<h2 id="autotest">{_bi("Préqualifications en cours (Autotest)", "Prequalifications in progress (Autotest)")}</h2>',
           "<p>" + _bi("Postes en cours d’essai avec l’outil openRemoteTRX-Autotest (lecture, écriture, PTT par la CAT, "
                       "mesures et son du poste, quelques secondes d’émission sur charge fictive). Une préqualification "
                       "n’est PAS une qualification : la sécurité d’émission à distance (TOT, battements, coupures) n’y "
                       "est pas essayée, et elle ne donne ni fiche ni note au poste. Un résultat vaut pour les versions "
                       "indiquées.",
                       "Rigs being tried with the openRemoteTRX-Autotest tool (reading, writing, CAT PTT, the rig’s "
                       "meters and audio, a few seconds of transmission into a dummy load). A prequalification is NOT a "
                       "qualification: remote transmit safety (TOT, heartbeats, cut-offs) is not tested, and it gives "
                       "the rig neither a sheet nor a rating. A result holds for the versions shown.") + "</p>"]
    if not reports:
        return out + [f'<p>{_bi("Aucune préqualification en cours.", "No prequalification in progress.")}</p>']
    for rep in reports:
        r = rep["rapport"]
        by_code = {e["code"]: e for e in rep["essais"]}
        mfr, men = AUTOTEST_MODES[r["mode"]]
        sfr, sen = AUTOTEST_SOURCES[r["source"]]
        info = [f'{html.escape(r["date"])}', f'Autotest {html.escape(r["outil"])}', _bi(mfr, men)]
        if r.get("hamlib"):
            info.append(f'Hamlib {html.escape(r["hamlib"])}')
        info += [html.escape(r["systeme"]), _bi(sfr, sen)]
        if r.get("arret"):
            info.append(_bi(*AUTOTEST_ARRETS[r["arret"]]))
        hamlib_n = f' · {_bi("Modèle Hamlib", "Hamlib model")} {r["hamlib_model"]}' if r.get("hamlib_model") else ""
        out += [f'<details class="poste" id="at-{html.escape(rep["id"])}">',
                f'<summary><h3>{html.escape(r["fabricant"])} {html.escape(r["modele"])}</h3> '
                f'<span class="verdict v-pre">{_bi("préqualification", "prequalification")}</span>'
                f'<p>{_bi(r["resume"], r["resume_en"])}{hamlib_n}</p></summary>', "<p>" + " · ".join(info) + "</p>",
                '<div class="wrap"><table>',
                f'<tr><th>{_bi("Essai", "Test")}</th><th>{_bi("Résultat", "Result")}</th>'
                f'<th>{_bi("Détail", "Detail")}</th></tr>']
        for code, fr, en in AUTOTEST_STEPS:
            e = by_code.get(code)
            status = e["statut"] if e else "absent"
            sym, cls, efr, een = AUTOTEST_ETATS[status]
            detail = _bi(e["texte"], e["texte_en"]) if e else ""
            if e and e.get("note"):
                detail += f'<br><small>{_bi(e["note"], e["note_en"])}</small>'
            out.append(f'<tr><td>{code} · {_bi(fr, en)}</td><td class="e e-{cls}">{sym} {_bi(efr, een)}</td>'
                       f'<td>{detail}</td></tr>')
        out += ["</table></div>",
                f'<p><small>{_bi("Empreinte de la trace", "Trace fingerprint")} : '
                f'<code>{html.escape(r["empreinte_trace"][:16])}…</code></small></p>', "</details>"]
    return out


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


# VERDICT ET NIVEAU (décisions de l'utilisateur du 2026-11-23, étape 376) : la note sur 5 étoiles faisait lire un 4,5
# comme « insuffisant » alors que l'essentiel marchait. Deux notations :
#   a) verdict « Utilisable à distance » calculé sur une liste FERMÉE de fonctions vitales (sécurité d'émission, fréquence,
#      un mode de phonie modulable par l'USB, son reçu et modulation par l'USB) : GO, GO avec réserve, NO-GO, pas encore
#      évalué ; une étoile devant le GO, rien d'autre ;
#   b) niveau des fonctions COMPLÉMENTAIRES (toutes les autres), 1 à 5, en bargraph de S-mètre tout en verts, montré
#      seulement avec un GO.
VITAL = [fid for fid, theme, *_ in FEATURES if theme == "securite"] + ["frequence", "audio_rx", "audio_tx"]
VITAL_MODES = ("modes_base", "modes_donnees")      # le meilleur des deux compte (Icom : phonie USB en mode données)
VITAL_MODES_LABEL = ("Mode de phonie modulable par l'USB", "Voice mode modulated over USB")
BEST_ORDER = ("valide", "partiel", "non_teste", "echec", "non_declare")
VERDICTS = {   # verdict : (classe, français, anglais)
    "go": ("go", "GO", "GO"),
    "go_reserve": ("go", "GO avec réserve", "GO with reservation"),
    "no_go": ("nogo", "NO-GO", "NO-GO"),
    "en_cours": ("encours", "pas encore évalué", "not assessed yet"),
}
USABLE = ("go", "go_reserve")
LEVEL_STEPS = ((0.95, 5), (0.80, 4), (0.65, 3), (0.50, 2), (0.0, 1))
LEVEL_NAMES = {1: ("essentiel", "essential"), 2: ("base", "basic"), 3: ("bon", "good"), 4: ("très bon", "very good"),
               5: ("complet", "complete")}
LEVEL_IF_FAULTS = 3                    # défauts aléatoires constatés : niveau 3 au plus


def vital_entries(rig: dict) -> list[tuple[str, str, str, dict]]:
    """(id, français, anglais, état) des fonctions vitales ; les modes comptent pour une, la meilleure des deux."""
    funcs, names = rig["fonctions"], {f[0]: (f[2], f[3]) for f in FEATURES}
    out = [(fid, *names[fid], funcs[fid]) for fid in VITAL]
    modes = sorted((funcs[m] for m in VITAL_MODES), key=lambda e: BEST_ORDER.index(e["etat"]))
    out.insert(len(VITAL) - 2, ("modes", *VITAL_MODES_LABEL, modes[0]))
    return out


def _why(fr: str, en: str, entry: dict) -> tuple[str, str]:
    if entry.get("note"):
        return f"{fr} : {entry['note']}", f"{en}: {entry.get('note_en', entry['note'])}"
    sym, efr, een = ETATS[entry["etat"]]
    return f"{fr} : {efr}", f"{en}: {een}"


def verdict(rig: dict) -> dict:
    """{verdict, reasons [(fr, en)], missing [(fr, en)]} : `reasons` = réserves ou causes du NO-GO, `missing` = fonctions
    vitales pas encore essayées."""
    poste = rig["poste"]
    entries = vital_entries(rig)
    if poste.get("statut") == "refuse":
        return {"verdict": "no_go", "reasons": [(poste["resume"], poste["resume_en"])], "missing": []}
    bad = [_why(fr, en, e) for _, fr, en, e in entries if e["etat"] in ("echec", "non_declare")]
    if bad:
        return {"verdict": "no_go", "reasons": bad, "missing": []}
    missing = [(fr, en) for _, fr, en, e in entries if e["etat"] == "non_teste"]
    if missing:
        return {"verdict": "en_cours", "reasons": [], "missing": missing}
    reasons = [_why(fr, en, e) for _, fr, en, e in entries if e["etat"] == "partiel"]
    labels = [(fr, en) for _, fr, en, e in entries if e["etat"] == "partiel"]     # noms seuls, pour le résumé
    if poste.get("statut") == "restreint":
        reasons.insert(0, (poste["resume"], poste["resume_en"]))
        labels.insert(0, ("validé avec restrictions", "validated with restrictions"))
    if poste.get("stabilite") == "defauts":
        reasons.append((f"Stabilité : {poste['stabilite_note']}", f"Stability: {poste['stabilite_note_en']}"))
        labels.append(("défauts de stabilité", "stability faults"))
    return {"verdict": "go_reserve" if reasons else "go", "reasons": reasons, "missing": [], "labels": labels}


def level(rig: dict) -> dict:
    """Fonctions complémentaires : `level` (1 à 5, None sans GO), `valid` / `counted` (validées / essayées et comptées),
    `untested`, `absent` (absentes du POSTE, non comptées), `limits` (limites de Hamlib ou d'openRemoteTRX, ½)."""
    funcs = rig["fonctions"]
    skip = set(VITAL) | set(VITAL_MODES)
    absent, limits, untested, points, counted, valid = [], [], [], 0.0, 0, 0
    for fid, theme, fr, en in FEATURES:
        if fid in skip:
            continue
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
    value = None
    if verdict(rig)["verdict"] in USABLE and counted:
        ratio = points / counted
        value = next(n for threshold, n in LEVEL_STEPS if ratio >= threshold - 1e-9)
        if rig["poste"].get("stabilite") == "defauts":
            value = min(value, LEVEL_IF_FAULTS)
    return {"level": value, "valid": valid, "counted": counted, "untested": untested, "absent": absent,
            "limits": limits}


def _badge(v: str) -> str:
    cls, fr, en = VERDICTS[v]
    star = "★ " if v in USABLE else ""
    return f'<span class="verdict v-{cls}">{star}{_bi(fr, en)}</span>'


def _bar(n: int) -> str:
    """Bargraph de S-mètre : 5 segments de plus en plus hauts, allumés en verts de plus en plus vifs (aucun jaune ni
    rouge : rien d'inquiétant). Le sens est porté par le texte qui suit (segments cachés aux lecteurs d'écran)."""
    return ('<span class="barre" aria-hidden="true">'
            + "".join(f'<i class="{"on" if i <= n else ""}"></i>' for i in range(1, 6)) + "</span>")


def _level_text(lv: dict, short: bool = False) -> str:
    fr, en = LEVEL_NAMES[lv["level"]]
    text = f'{_bar(lv["level"])} {_bi(fr, en)} · {lv["valid"]}/{lv["counted"]}'
    if lv["untested"] and not short:
        text += " " + _bi(f"({len(lv['untested'])} pas encore essayée(s))", f"({len(lv['untested'])} not tried yet)")
    return text


def _verdict_html(rig: dict) -> list[str]:
    v, lv = verdict(rig), level(rig)
    head = _badge(v["verdict"])
    if lv["level"] is not None:
        head += f' <span class="niveau">{_bi("Fonctions complémentaires :", "Additional features:")} {_level_text(lv)}</span>'
    out = [f'<p class="note-verdict">{head}</p>', '<ul class="note-detail">']
    if v["verdict"] == "go":
        out.append("<li>" + _bi("Toutes les fonctions vitales sont validées (sécurité d’émission, fréquence, mode, son "
                                "reçu et modulation par l’USB).",
                                "All vital features are validated (transmit safety, frequency, mode, receive audio and "
                                "modulation over USB).") + "</li>")
    for fr, en in v["reasons"]:
        title = (_bi("Réserve", "Reservation") if v["verdict"] == "go_reserve" else _bi("Bloquant", "Blocking"))
        out.append(f"<li>{title} : {_bi(fr, en)}</li>")
    if v["missing"]:
        out.append("<li>" + _bi("Fonctions vitales pas encore essayées : " + ", ".join(fr for fr, _ in v["missing"]) + ".",
                                "Vital features not tried yet: " + ", ".join(en for _, en in v["missing"]) + ".") + "</li>")
    if lv["level"] is not None:
        out.append("<li>" + _bi(f"Fonctions complémentaires : {lv['valid']} validées sur {lv['counted']} essayées.",
                                f"Additional features: {lv['valid']} validated out of {lv['counted']} tried.") + "</li>")
        if lv["absent"]:
            out.append("<li>" + _bi("Absent du poste (choix du constructeur, non compté) : " + ", ".join(fr for fr, _ in lv["absent"]) + ".",
                                    "Missing from the rig (manufacturer's choice, not counted): " + ", ".join(en for _, en in lv["absent"]) + ".") + "</li>")
        if lv["limits"]:
            out.append("<li>" + _bi("Limites de Hamlib ou d'openRemoteTRX (comptées ½) : " + ", ".join(fr for fr, _ in lv["limits"]) + ".",
                                    "Hamlib or openRemoteTRX limits (counted ½): " + ", ".join(en for _, en in lv["limits"]) + ".") + "</li>")
    stability = rig["poste"].get("stabilite")
    if stability in STABILITES:
        sfr, sen = STABILITES[stability]
        note = rig["poste"].get("stabilite_note", "")
        out.append("<li>" + _bi(f"Stabilité : {sfr}" + (f" ({note})" if note else "") + ".",
                                f"Stability: {sen}" + (f" ({rig['poste'].get('stabilite_note_en', note)})" if note else "") + ".") + "</li>")
    out.append("</ul>")
    return out


def _summary(rigs: list[dict], reports: list[dict]) -> list[str]:
    """Résumé en tête : « Utilisable à distance » | « En cours d'évaluation » (NO-GO compris, avec sa raison)."""
    left, right = [], []
    def order(rig: dict) -> tuple:            # GO d'abord, puis le niveau le plus haut
        v, lv = verdict(rig)["verdict"], level(rig)["level"] or 0
        return (list(VERDICTS).index(v), -lv, rig["poste"]["fabricant"], rig["poste"]["modele"])
    for rig in sorted(rigs, key=order):
        p, v, lv = rig["poste"], verdict(rig), level(rig)
        name = f'<a href="#{html.escape(rig["id"])}">{html.escape(p["fabricant"])} {html.escape(p["modele"])}</a>'
        line = f"{name} {_badge(v['verdict'])}"
        if lv["level"] is not None:
            line += f' <span class="niveau">{_level_text(lv, short=True)}</span>'
        if v["verdict"] == "no_go" and v["reasons"]:
            line += f'<br><small>{_bi(*v["reasons"][0])}</small>'
        elif v["verdict"] == "go_reserve" and v.get("labels"):
            line += "<br><small>" + _bi("réserve : " + ", ".join(fr for fr, _ in v["labels"]),
                                        "reservation: " + ", ".join(en for _, en in v["labels"])) + "</small>"
        elif v["verdict"] == "en_cours":
            line += "<br><small>" + _bi(f"qualification en cours : {len(v['missing'])} fonction(s) vitale(s) à essayer",
                                        f"qualification in progress: {len(v['missing'])} vital feature(s) to try") + "</small>"
        (left if v["verdict"] in USABLE else right).append(f"<li>{line}</li>")
    for rep in reports:
        r = rep["rapport"]
        ok = sum(1 for e in rep["essais"] if e["statut"] == "ok")
        right.append(f'<li><a href="#at-{html.escape(rep["id"])}">{html.escape(r["fabricant"])} {html.escape(r["modele"])}</a> '
                     f'<span class="verdict v-pre">{_bi("préqualification", "prequalification")}</span><br><small>'
                     + _bi(f"Autotest : {ok} essais réussis sur {len(AUTOTEST_STEPS)}, sécurité à distance pas essayée",
                           f"Autotest: {ok} tests passed out of {len(AUTOTEST_STEPS)}, remote safety not tried")
                     + "</small></li>")
    none = f'<li><small>{_bi("aucun pour l’instant", "none yet")}</small></li>'
    return ['<div class="resume">',
            f'<div><h2>{_bi("Utilisables à distance", "Usable remotely")}</h2><ul>{"".join(left) or none}</ul></div>',
            f'<div><h2>{_bi("En cours d’évaluation", "Being assessed")}</h2><ul>{"".join(right) or none}</ul></div>',
            "</div>",
            "<p><small>" + _bi("★ GO : toutes les fonctions vitales (sécurité d’émission, fréquence, mode, son reçu et "
                               "modulation par l’USB) sont validées sur charge fictive ; on peut commencer à piloter son "
                               "poste à distance. La barre dit ce qui marche parmi les autres fonctions (filtres, NR, NB, "
                               "coupleur, spectre…), de 1 « essentiel » à 5 « complet » : une fonction pas encore "
                               "essayée ne la fait pas baisser.",
                               "★ GO: every vital feature (transmit safety, frequency, mode, receive audio and modulation "
                               "over USB) is validated on a dummy load; you can start operating your rig remotely. The bar "
                               "shows what works among the other features (filters, NR, NB, tuner, spectrum…), from 1 "
                               "“essential” to 5 “complete”: a feature not tried yet does not lower it.")
            + "</small></p>"]


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
    return f'{html.escape(p["fabricant"])} {html.escape(p["modele"])}'


def _table1(rig: dict, marks: dict | None = None) -> list[str]:
    funcs = rig["fonctions"]
    marks = marks if marks is not None else number_partials([rig])
    partials: list[tuple[int, str, str, str, str]] = []
    verdict_lines = _verdict_html(rig)
    out = [f'<details class="poste" id="{html.escape(rig["id"])}">', f"<summary><h3>{_rig_title(rig)}</h3>",
           verdict_lines[0], "</summary>", *verdict_lines[1:],
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
    out.append("</details>")
    return out


def _table2(rigs: list[dict], marks: dict | None = None) -> list[str]:
    shown = [r for r in rigs if r["poste"]["statut"] in COMPARED]
    if not shown:
        return [f'<p>{_bi("Aucun poste à comparer pour l’instant.", "No rig to compare yet.")}</p>']
    def stars_of(r):
        lv = level(r)
        bar = f'<br><span class="niveau">{_level_text(lv, short=True)}</span>' if lv["level"] is not None else ""
        return f'<br>{_badge(verdict(r)["verdict"])}{bar}'
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


def _usb_tables(usb: dict, rigs: list[dict], reports: list[dict] | None = None) -> list[str]:
    fiches = {r["id"]: r for r in rigs}
    prequal = {}                                   # numéro Hamlib -> préqualification la plus récente
    for rep in reports or []:
        prequal.setdefault(rep["rapport"].get("hamlib_model"), rep)

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
                elif e["hamlib_model"] in prequal:
                    cells.append(f'<a href="#at-{html.escape(prequal[e["hamlib_model"]]["id"])}">'
                                 f'<span class="statut s-validation_en_cours">'
                                 f'{_bi("préqualification en cours", "prequalification in progress")}</span></a>')
                else:
                    cells.append(_bi("non essayé", "not tried"))
            cells.append(note)
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        return out

    head = (f'<tr><th>{_bi("Marque", "Brand")}</th><th>{_bi("Modèle", "Model")}</th>'
            f'<th>{_bi("N° Hamlib", "Hamlib #")}</th>'
            f'<th>{_bi("Pilote Hamlib", "Hamlib driver")} {html.escape(usb["hamlib_version"])}</th>')
    out = [f'<details class="bloc" id="usb"><summary><h2>{_bi("Postes à USB intégré (CAT et son)", "Rigs with built-in USB (CAT and audio)")}</h2></summary>',
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
    out.append("</details>")
    return out


def render(rigs: list[dict], usb: dict | None = None, reports: list[dict] | None = None) -> str:
    usb = usb if usb is not None else load_usb()
    reports = reports if reports is not None else load_autotest()
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
           + f'<a href="#usb">{_bi("postes à USB intégré", "rigs with built-in USB")}</a> ; '
           + _bi("postes en cours d’essai : ", "rigs being tried: ")
           + f'<a href="#autotest">{_bi("préqualifications (Autotest)", "prequalifications (Autotest)")}</a>.</p>',
           *_summary(rigs, reports),
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
    out.append("<p>" + _bi("Toucher un poste pour ouvrir sa fiche.", "Tap a rig to open its sheet.") + "</p>")
    for rig in rigs:
        out += _table1(rig, marks)
    out.append(_footnotes(anchor=False))
    out += _autotest_section(reports)
    out += _usb_tables(usb, rigs, reports)
    out += ["<footer>",
            f'<p><a href="../erreurs/">{_bi("Codes d’erreur", "Error codes")}</a> · <a href="../guide/">'
            f'{_bi("Guide de l’opérateur", "Operator guide")}</a> · <a href="data.json">data.json</a> · '
            f'<a href="{base.REPO_URL}" target="_blank" rel="noopener noreferrer">{_bi("code source", "source code")}</a> · '
            f'<a href="{base.SITE_URL}" target="_blank" rel="noopener noreferrer">rf-diy.com</a></p>',
            "</footer>", "</main>", f"<script>{base.RESIZE_JS.strip()}{PAGE_JS.strip()}</script>", "</body>", "</html>", ""]
    return "\n".join(out)


def data_json(rigs: list[dict], usb: dict | None = None, reports: list[dict] | None = None) -> str:
    usb = usb if usb is not None else load_usb()
    reports = reports if reports is not None else load_autotest()
    out = {"format": 1, "page": PAGES_URL,
           "themes": [{"id": t, "fr": fr, "en": en} for t, fr, en in THEMES],
           "fonctions": [{"id": f, "theme": t, "fr": fr, "en": en} for f, t, fr, en in FEATURES],
           "etats": {k: {"fr": v[1], "en": v[2]} for k, v in ETATS.items()},
           "postes": [{**{k: v for k, v in r.items()},
                       "verdict": verdict(r)["verdict"],
                       "niveau": {k: v for k, v in level(r).items() if k in ("level", "valid", "counted")}}
                      for r in rigs],
           "usb_integre": usb,
           "prequalifications": reports}
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"


def build(site: Path = SITE, rigs: list[dict] | None = None) -> dict[Path, str]:
    rigs = rigs if rigs is not None else load_rigs()
    check(rigs)
    usb = load_usb()
    check_usb(usb, rigs)
    reports = load_autotest()
    check_autotest(reports)
    return {site / FOLDER / "index.html": render(rigs, usb, reports),
            site / FOLDER / "data.json": data_json(rigs, usb, reports)}


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
