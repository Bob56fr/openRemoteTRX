# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""openRemoteTRX-Autotest (autotest/web/, docs/prequalif-web-cahier-des-charges.md) : tests Node de la logique et de
la garde d'émission, page qui ne contacte AUCUN serveur, liste fermée des commandes CI-V, un seul chemin d'émission."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "autotest" / "web"
CODE = sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")) + [WEB / "index.html"]


def test_logic_and_transmit_guard_under_node() -> None:
    node = shutil.which("node")
    if not node:
        return                                                                          # Node absent : test ignoré
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "autotest_test.js")], capture_output=True, text=True,
                          encoding="utf-8", timeout=300)   # ~2 min 30 : parcours complets simulés
    assert done.returncode == 0, done.stdout + done.stderr


def test_every_file_has_its_licence_header_and_every_script_exists() -> None:
    for f in CODE:
        assert "SPDX-License-Identifier: AGPL-3.0-or-later" in f.read_text(encoding="utf-8")[:300], f.name
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^":?]+)"', html):              # « ?lang=en » : choix de la langue
        assert (WEB / ref).is_file(), ref


def test_the_page_contacts_no_server_during_the_test() -> None:
    """« Le test est anonyme, rien ne part » (§ 4) : ni requête, ni police ou script venus d'ailleurs ; la CSP l'impose."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in html and "default-src 'self'" in html
    for f in CODE:
        text = f.read_text(encoding="utf-8")
        if f.name == "hamlib.js":
            # Mode B (lot PQ5) : SEULE exception, l'API du programme local qui SERT la page (même origine, chemins
            # relatifs « api/… ») ; la CSP de la page publiée (connect-src 'none') l'empêche de toute façon.
            calls = re.findall(r'fetch\(\(base \|\| ""\) \+ ("api/[a-z_]+"|path)', text)
            assert len(calls) == text.count("fetch(") and calls, calls
            assert set(re.findall(r'"(api/[a-z_]+)"', text)) <= {"api/cmd", "api/ptt_off", "api/connect", "api/disconnect",
                                                                  "api/info", "api/models", "api/ports"}
            text = text.replace("fetch(", "")
        for bad in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "@import", "googleapis"):
            assert bad not in text, (f.name, bad)
        urls = re.findall(r"https?://[^\s\"'<>)]+", text)
        if f.name == "index.html":
            assert set(urls) <= {"https://github.com/Bob56fr/openRemoteTRX", "https://www.rf-diy.com"}, urls  # liens, cliqués ou non
        else:
            assert urls == [], (f.name, urls)


def test_closed_list_of_civ_commands_and_a_single_way_to_transmit() -> None:
    civ = (WEB / "civ.js").read_text(encoding="utf-8")
    block = civ[civ.index("const CMD = {"):civ.index("};", civ.index("const CMD = {"))]
    cmds = set(re.findall(r"\[(0x[0-9A-F]{2}(?:, 0x[0-9A-F]{2})?)\]", block))
    assert cmds == {"0x19, 0x00", "0x03", "0x04", "0x05", "0x06", "0x14, 0x0A", "0x15, 0x02", "0x15, 0x11", "0x15, 0x12",
                    "0x15, 0x13", "0x1C, 0x00", "0x1A, 0x06", "0x27, 0x11",
                    "0x27, 0x10",   # affichage du spectre (essai R10, lu puis remis) ; 27 00 = données reçues, jamais envoyées
                    # fonctions de l'essai R9 (lecture, écriture, remise) ; JAMAIS le VOX (16 46)
                    "0x11", "0x16, 0x02", "0x16, 0x12", "0x16, 0x22", "0x16, 0x40", "0x16, 0x41", "0x16, 0x44",
                    "0x16, 0x65", "0x14, 0x06", "0x14, 0x12", "0x14, 0x0E", "0x0F", "0x21, 0x01", "0x1C, 0x01",
                    "0x07, 0xB0", "0x25"}, cmds     # jamais 0x18 (alimentation) ni 1A 05 (menus)
    assert "[CMD.TUNER.join(\",\")]: [[], [0x00], [0x01]]" in civ                       # jamais 1C 01 02 (accord = émission)
    sources = {f.name: f.read_text(encoding="utf-8") for f in WEB.glob("*.js")}
    keyers = [n for n, t in sources.items() for _ in re.finditer(r"setPtt\(true\)", t)]
    assert keyers == ["runner.js"], keyers
    runner = sources["runner.js"]
    assert runner.count("setPtt(true)") == 1 and runner.index("setPtt(true)") > runner.index("class TxGuard")
    assert runner.index("setPtt(true)") < runner.index("class Runner")
    assert "setTimeout(() => { this.unkey(\"duree_max\"); }, this.o.maxTx)" in runner
    assert "maxTx: 10000" in runner                                                     # 10 s au plus par émission


def test_terms_of_use_are_shown_at_every_visit_and_must_be_accepted() -> None:
    """Conditions d'utilisation (texte validé le 2026-11-19) : fenêtre ouverte au chargement, au-dessus de l'accueil,
    redemandée à chaque visite (rien n'est retenu), bouton inactif tant que la case n'est pas cochée."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    tag = re.search(r'<div class="overlay terms-veil" id="o-terms"[^>]*>', html).group(0)
    assert "hidden" not in tag
    assert re.search(r'<button[^>]*id="terms-go"[^>]*disabled', html)
    assert "J'accepte les conditions d'utilisation de cette application et j'accepte les risques." in html
    assert "Démarrer les tests anonymes de ma station" in html and "Limitation de responsabilité" in html
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '$("terms-go").disabled = !$("terms-ok").checked' in app
    for f in WEB.glob("*.js"):
        text = f.read_text(encoding="utf-8")
        assert "localStorage" not in text and "sessionStorage" not in text and "indexedDB" not in text, f.name


def test_yaesu_closed_list_never_vox_menus_power_mox_or_tuning() -> None:
    """Pilote Yaesu (yaesu.js, manuel CAT FTDX10) : écritures en liste fermée ; jamais VX (VOX), EX (menus), PS
    (alimentation), MX (MOX) ; coupleur seulement 0 / 1 (2 = accord = émission), split jamais « + 5 kHz »."""
    ya = (WEB / "yaesu.js").read_text(encoding="utf-8")
    block = ya[ya.index("const WRITE = {"):ya.index("};", ya.index("const WRITE = {"))]
    keys = set(re.findall(r"(?<![A-Za-z0-9])([A-Z]{2}[0-9]{0,2}):", block))
    assert keys == {"FA", "FB", "MD0", "PC", "TX", "NB0", "NL0", "NR0", "RL0", "RA0", "PA0", "BC0", "PR0", "RT", "ST",
                    "AC00", "SV"}, keys
    assert "AC00: /^[01]$/" in block and "ST: /^[01]$/" in block and "TX: /^[01]$/" in block


def test_kenwood_closed_list_never_tx_tune_vox_menus_power_tuning_or_saved_ai() -> None:
    """Pilote Kenwood (kenwood.js, manuel PC Control Command du TS-890S) : jamais TX2 (TX TUNE), VX, EX, PS ; coupleur
    écrit seulement « 1x0 » (P3 = 1 lancerait l'accord) ; AI seulement 0 ou 2 (jamais 4, sauvegardée dans le poste)."""
    kw = (WEB / "kenwood.js").read_text(encoding="utf-8")
    block = kw[kw.index("const WRITE = {"):kw.index("};", kw.index("const WRITE = {"))]
    keys = set(re.findall(r"(?<![A-Za-z0-9])([A-Z]{2}[0-9]{0,1}):", block))
    assert keys == {"FA", "FB", "OM0", "PC", "TX", "RX", "EC", "AI", "RM", "NB1", "NL1", "NR", "NT", "BC", "RA", "PA",
                    "GC", "PR0", "RT", "XT", "TB", "AC"}, keys
    for rule in ("TX: /^[01]$/", "AC: /^1[01]0$/", "AI: /^[02]$/"):
        assert rule in block, rule


def test_every_text_has_its_english_translation() -> None:
    """Lot PQ6 : chaque texte du code passé par T("…") a sa traduction dans en.js (EN), chaque partie fixe de la page
    marquée data-t="clé" a la sienne (EN_PAGE) ; i18n.js et en.js sont chargés avant le reste ; rien n'est retenu."""
    import json
    en_src = (WEB / "en.js").read_text(encoding="utf-8")
    en = json.loads(en_src[en_src.index("const EN = ") + 11:en_src.index(";\n  const EN_PAGE")])
    page = json.loads(en_src[en_src.index("const EN_PAGE = ") + 16:en_src.index(";\n  if (typeof module")])
    missing = []
    for f in ("runner.js", "app.js"):
        for key in re.findall(r'\bT\("([^"]*)"', (WEB / f).read_text(encoding="utf-8")):
            if key not in en:
                missing.append((f, key))
    assert not missing, missing[:10]
    html = (WEB / "index.html").read_text(encoding="utf-8")
    keys = re.findall(r'data-t="([^"]+)"', html)
    assert len(keys) == len(set(keys)) and set(keys) <= set(page), set(keys) - set(page)
    assert html.index('src="i18n.js"') < html.index('src="en.js"') < html.index('src="civ.js"')
    assert 'href="?lang=en"' in html and 'href="?lang=fr"' in html
