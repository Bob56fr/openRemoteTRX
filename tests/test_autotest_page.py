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
                          encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def test_every_file_has_its_licence_header_and_every_script_exists() -> None:
    for f in CODE:
        assert "SPDX-License-Identifier: AGPL-3.0-or-later" in f.read_text(encoding="utf-8")[:300], f.name
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^":]+)"', html):
        assert (WEB / ref).is_file(), ref


def test_the_page_contacts_no_server_during_the_test() -> None:
    """« Le test est anonyme, rien ne part » (§ 4) : ni requête, ni police ou script venus d'ailleurs ; la CSP l'impose."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in html and "default-src 'self'" in html
    for f in CODE:
        text = f.read_text(encoding="utf-8")
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
                    "0x15, 0x13", "0x1C, 0x00", "0x1A, 0x06", "0x27, 0x11"}, cmds     # jamais 0x18 (alimentation) ni 1A 05 (menus)
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
