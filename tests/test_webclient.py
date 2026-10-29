# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Client web de référence : cohérence avec le serveur, hygiène de sécurité de la page, logique JavaScript (Node)."""
import re
import shutil
import subprocess
from pathlib import Path

from trxstation.gateway.api.protocol import COMMANDS

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "trxstation" / "gateway" / "api" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
LOGIC = (STATIC / "client.js").read_text(encoding="utf-8")
UI = (STATIC / "ui.js").read_text(encoding="utf-8")
WATERFALL = (STATIC / "waterfall.js").read_text(encoding="utf-8")
LAYOUT = (STATIC / "layout.js").read_text(encoding="utf-8")
JS = LOGIC + "\n" + UI + "\n" + WATERFALL + "\n" + LAYOUT                               # les quatre scripts de la page
CSS = (STATIC / "client.css").read_text(encoding="utf-8")
PTT = (ROOT / "trxstation" / "gateway" / "safety" / "ptt.py").read_text(encoding="utf-8")
SESSION = (ROOT / "trxstation" / "gateway" / "api" / "session.py").read_text(encoding="utf-8")


def js_table(name):
    block = re.search(rf"const {name} = \{{(.*?)\n  \}};", LOGIC, re.S).group(1)
    return set(re.findall(r"^\s+([a-z_]+):", block, re.M))


def test_page_has_no_inline_code_and_no_external_resource():
    assert not re.search(r"<script(?![^>]*\bsrc=)", HTML) and "<style" not in HTML     # compatible CSP stricte
    assert not re.search(r"\son[a-z]+\s*=", HTML)                                       # aucun gestionnaire en ligne
    site = '<a id="site-link" class="sitelink" href="https://www.rf-diy.com" target="_blank" rel="noopener noreferrer"'
    assert HTML.count(site) == 1                                                        # SEUL lien sortant : le site du projet,
    assert not re.search(r"https?://", HTML.replace(site, "") + JS + CSS)               # nouvel onglet, sans référent ; aucune ressource externe
    for dangerous in ("eval(", "innerHTML", "document.write", "new Function"):
        assert dangerous not in JS, dangerous


def test_every_dom_id_used_by_the_script_exists_in_the_page():
    used = set(re.findall(r'\$\("([a-z-]+)"\)', JS))
    used |= set(re.findall(r'"((?:armed|ptt|stop|freq-set|disconnect|mem-add-current))"', JS))
    used |= {button for _, button in re.findall(r'\["([A-Z]+)", "(ctl-[a-z]+)"\]', UI)}
    used |= {button for button, _ in re.findall(r'\["(wf-[a-z]+)", "([a-z]+)"\]', UI)}              # boutons du waterfall créés en boucle
    defined = set(re.findall(r'\bid="([a-z-]+)"', HTML))
    assert used and used <= defined, used - defined


def test_script_only_sends_commands_the_server_knows():
    sent = (set(re.findall(r'send\("([a-z_]+)"', JS)) | set(re.findall(r'_rigSetting\("([a-z_]+)"', JS))
            | set(re.findall(r'cmd: "([a-z_]+)"', JS)))
    assert sent == set(COMMANDS), (sent ^ set(COMMANDS))                                # ni inconnue, ni oubliée


def test_every_refusal_and_cut_reason_of_the_server_has_a_french_message():
    reasons = js_table("REASONS")
    refused = set(re.findall(r'Refused\("([a-z_]+)"', PTT)) | set(re.findall(r'reason="([a-z_]+)"', SESSION))
    assert refused <= reasons, refused - reasons
    cuts = js_table("CUT_REASONS")
    produced = (set(re.findall(r'force_rx\("([a-z_]+)"', PTT + SESSION)) | set(re.findall(r'return "([a-z_]+)"', PTT))
                | set(re.findall(r'reason = "([a-z_]+)"', PTT)))
    assert produced and produced <= cuts, produced - cuts


def test_javascript_client_logic_with_a_fake_browser():
    node = shutil.which("node")
    if not node:
        return                                                                          # Node absent : test ignoré
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "client_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_voice_equalizer_and_effects_with_a_fake_audio_context():
    """Égaliseur et effets de voix (voice.js) : biquads = vecteurs partagés, limiteur toujours là, rien vers la station hors TX."""
    node = shutil.which("node")
    if not node:
        return
    html = (ROOT / "trxstation" / "gateway" / "api" / "static" / "index.html").read_text(encoding="utf-8")
    assert html.index('src="voice.js"') < html.index('src="ui.js"')
    server = (ROOT / "trxstation" / "gateway" / "api" / "server.py").read_text(encoding="utf-8")
    assert '"/voice.js": ("voice.js", "text/javascript")' in server
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "voice_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_page_reads_the_shared_protocol_examples():
    node = shutil.which("node")
    if not node:
        return
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "protocol_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_page_display_with_a_fake_browser_loading_the_real_page():
    node = shutil.which("node")
    if not node:
        return
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "ui_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_classes_set_by_the_scripts_exist_in_the_stylesheet():
    classes = set()
    for found in re.findall(r'el\("[a-z]+", "([a-z0-9 -]+)"', UI) + re.findall(r'className = "([a-z0-9 -]+)"', UI):
        classes |= set(found.split())
    classes |= set(re.findall(r'" (fav|active|on|tx)"', UI)) | {"ptt", "ptt-state", "chip", "badge", "ok", "busy", "bad", "warn",
                                                              "dig", "sep", "active", "pending", "locked", "txzone", "wf", "keypad", "bands", "lost", "reconnect"}
    classes |= set(re.findall(r'status\("[^"]*", "([a-z]+)"\)', LOGIC))
    missing = {c for c in classes if not re.search(rf"\.{re.escape(c)}\b", CSS)}
    assert classes and not missing, missing
    for token in ("portrait", "landscape"):                                              # les deux dispositions existent
        assert f"#app.{token}" in CSS or token == "portrait", token
    for size in ("s", "m", "l"):
        assert f'html[data-text="{size}"]' in CSS, size


def test_the_top_part_stays_visible_and_only_the_bottom_scrolls():
    assert re.search(r"#top\s*\{[^}]*flex:\s*0 0 auto", CSS) and re.search(r"#bottom\s*\{[^}]*overflow-y:\s*auto", CSS)
    assert HTML.index('id="ptt"') < HTML.index('id="bottom"')                           # le bouton d'émission est dans la partie haute
    top = HTML[HTML.index('<header id="top">'):HTML.index("</header>")]
    for needed in ("freq", "mode-pill", "smeter-text", "sql-marker", "po-text", "swr-text", "alc-text", "ctl-nr", "ctl-nb", "ctl-preamp", "ctl-aip",
                   "ctl-agc", "ctl-comp", "ctl-fil", "ctl-tuner", "ptt", "stop", "armed", "squelch"):
        assert f'id="{needed}"' in top, needed
    assert re.search(r"\.ptt\s*\{[^}]*min-height:\s*3\.\d+rem", CSS)               # bouton d'émission assez grand


def test_hidden_attribute_always_wins_over_class_display_rules():
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", CSS)           # sinon .memform { display: grid } reste visible


def test_control_buttons_sit_above_the_ptt_button_and_the_ptt_button_is_named_ptt():
    top = HTML[HTML.index('<header id="top">'):HTML.index("</header>")]
    assert top.index('id="ctl-nr"') < top.index('id="ptt"') and top.index('id="ctl-tuner"') < top.index('id="ptt"')   # juste au-dessus du bouton
    assert re.search(r'<button id="ptt"[^>]*>PTT</button>', top)
    assert top.index('id="po-mask"') < top.index('id="swr-mask"') and top.index('id="po-mask"') < top.index('id="alc-mask"')   # SWR et ALC sous la puissance
    assert top.index('id="sql-marker"') < top.index('id="smeter-mask"')                                                          # le repère est dans le S-mètre
    assert "ÉMETTRE" not in HTML + UI


def test_every_control_button_is_a_real_button_with_a_touch_friendly_size():
    for key in ("nr", "nb", "preamp", "aip", "agc", "comp", "fil", "tuner"):
        assert re.search(rf'<button id="ctl-{key}" class="chip"', HTML), key
    assert re.search(r"\.chip\s*\{[^}]*min-height:\s*1\.9\d*rem", CSS)


def test_waterfall_logic_with_node():
    node = shutil.which("node")
    if not node:
        return
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "waterfall_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr



def test_hf_scope_view_is_loaded_served_and_its_logic_passes_with_node():
    assert HTML.index('src="client.js"') < HTML.index('src="hfscope.js"') < HTML.index('src="ui.js"')
    server = (ROOT / "trxstation" / "gateway" / "api" / "server.py").read_text(encoding="utf-8")
    assert '"/hfscope.js": ("hfscope.js", "text/javascript")' in server
    for element in ("hfscope", "hf-plot", "hf-spec", "hf-fall", "hf-grid", "hf-axis", "hf-marker", "hf-stop", "hf-close", "hf-gain", "hf-range", "hf-tx", "hf-set-mode", "hf-set-span", "hf-ref-down", "hf-ref", "hf-ref-up", "hf-set-speed", "hf-vfo"):
        assert f'id="{element}"' in HTML, element
    node = shutil.which("node")
    if not node:
        return
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "hfscope_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr

def test_power_zone_toggles_with_the_waterfall_and_contains_po_swr_alc():
    def inside(container_id, element_id):                    # l'élément est-il dans le conteneur ? (analyse de la structure, pas une simple recherche de texte)
        from html.parser import HTMLParser

        class Finder(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.found = [], False

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if a.get("id") == element_id and any(entry == container_id for entry in self.stack):
                    self.found = True
                if tag not in ("meta", "link", "input", "br", "img", "hr"):
                    self.stack.append(a.get("id"))

            def handle_endtag(self, tag):
                if tag not in ("meta", "link", "input", "br", "img", "hr") and self.stack:
                    self.stack.pop()
        finder = Finder()
        finder.feed(HTML)
        return finder.found
    for needed in ("po-mask", "swr-mask", "alc-mask"):
        assert inside("txzone", needed), needed
    assert not inside("txzone", "smeter-mask") and not inside("waterfall", "po-mask")             # le S-mètre reste visible quand le waterfall s'ouvre
    for needed in ("wf-spec", "wf-fall", "wf-grid", "wf-axis", "wf-speed", "wf-width", "wf-gain", "wf-peak"):
        assert inside("waterfall", needed), needed
    assert re.search(r'<div id="waterfall"[^>]*\bhidden\b', HTML) and not re.search(r'<div id="txzone"[^>]*\bhidden\b', HTML)   # fermé au départ
    assert HTML.index('id="waterfall"') < HTML.index('class="chips"')                                                              # toujours dans la partie haute, avant les boutons et le PTT


def test_loading_order_of_the_scripts_and_no_forbidden_constructs():
    assert HTML.index('src="client.js"') < HTML.index('src="waterfall.js"') < HTML.index('src="ui.js"')
    for dangerous in ("eval(", "innerHTML", "document.write", "new Function", "insertAdjacentHTML", "outerHTML"):
        assert dangerous not in JS, dangerous


def test_tune_section_comes_before_memories_and_is_open():
    assert HTML.index('id="sec-tune"') < HTML.index('id="sec-memories"')
    assert re.search(r'<details id="sec-tune" open>', HTML)
    for needed in ("bands", "step-down", "step-select", "step-up", "freq-input", "mode-buttons"):
        assert f'id="{needed}"' in HTML[HTML.index('id="sec-tune"'):HTML.index('id="sec-memories"')], needed


def test_connection_loss_history_lives_in_the_journal_and_the_last_reason_next_to_the_connect_button():
    diag = HTML[HTML.index('id="sec-diag"'):]
    for needed in ("loss-select", "loss-detail", "loss-copy", "loss-clear", 'id="log"'):
        assert needed in diag, needed
    connect = HTML[HTML.index('id="sec-connect"'):HTML.index('id="sec-tune"')]
    assert 'id="loss-last"' in connect and 'id="loss-open"' in connect


def test_splash_image_is_small_served_and_fades_out_by_itself_after_two_seconds():
    assets = [p for p in STATIC.iterdir() if p.name.startswith("splash.")]
    assert len(assets) == 1 and assets[0].stat().st_size < 150_000, assets            # trois cents ko d'image rendraient l'accueil lent en 4G
    name = assets[0].name
    body = HTML[HTML.index("<body>"):]
    assert re.match(rf'<body>\s*<div id="splash" class="splash"[^>]*><img src="{re.escape(name)}" alt="[^"]+"></div>', body)   # premier élément de la page
    server = (ROOT / "trxstation" / "gateway" / "api" / "server.py").read_text(encoding="utf-8")
    assert f'"/{name}": ("{name}", "image/' in server                                  # la passerelle sert l'image avec son type
    assert re.search(r"\.splash\s*\{[^}]*animation:\s*splash-out\s+\.35s\s+ease\s+2s\s+forwards", CSS)   # 2 s puis un fondu, sans JavaScript
    assert re.search(r"@keyframes splash-out\s*\{[^}]*visibility:\s*hidden", CSS)                        # une fois effacée, elle ne bloque plus aucun appui
    assert "prefers-reduced-motion" in CSS and 'getElementById("splash")' in UI.replace("$(\"splash\")", 'getElementById("splash")')
    assert re.search(r"z-index:\s*100", CSS[CSS.index(".splash"):])


def test_reconnect_banner_replaces_the_frequency_area_and_the_duration_is_adjustable():
    header = HTML[HTML.index('<header id="top">'):HTML.index("</header>")]
    assert header.index('id="freq"') < header.index('id="reconnect"') < header.index('class="meters"')     # même emplacement que la fréquence
    assert re.search(r'<div id="reconnect" class="reconnect" hidden>', header) and 'id="reconnect-cancel"' in header
    options = re.findall(r'<option value="(\d+)">', HTML[HTML.index('id="reconnect-select"'):HTML.index("</select>", HTML.index('id="reconnect-select"'))])
    assert options == ["0", "15", "30", "60"]
    assert re.search(r"\.reconnect-text\s*\{[^}]*animation:\s*blink", CSS) and "@keyframes blink" in CSS     # le texte clignote
    assert re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.reconnect-text\s*\{\s*animation:\s*none", CSS)   # sauf si l'utilisateur a demandé moins d'animation
    assert re.search(r"\.reconnect-text\s*\{[^}]*font-size:\s*min\(2\.[0-9]+rem", CSS)                  # gros texte
    assert "frequencyPending" in LOGIC and "reconnectWindowS: Number($(\"reconnect-select\").value)" in UI


def test_the_password_is_never_written_to_any_storage():
    stored = re.findall(r'(?:storage|store)\.set\(\s*"([^"]+)"', LOGIC + UI)
    assert stored and not any("pass" in key.lower() or "secret" in key.lower() for key in stored), stored
    assert re.findall(r'storage\.set\("([^"]+)"', LOGIC) and set(re.findall(r'storage\.set\("([^"]+)"', LOGIC)) <= {"trx.bands", "trx.losses"}
    assert "localStorage.setItem" in UI and "password" not in UI[UI.index("const store = {"):UI.index("const el = ")]    # le magasin du navigateur ne manipule jamais le mot de passe
    assert 'client.disconnect()' in UI and "this._credentials = null" in LOGIC                                         # oublié à la déconnexion voulue


def test_layout_logic_with_node_and_the_page_loads_it():
    assert HTML.index('src="layout.js"') < HTML.index('src="ui.js"')                       # chargé avant l'affichage
    server = (ROOT / "trxstation" / "gateway" / "api" / "server.py").read_text(encoding="utf-8")   # sans importer aiohttp
    assert '"/layout.js": ("layout.js", "text/javascript")' in server
    classes = set()
    for found in re.findall(r'_el\("[a-z]+", "([a-z0-9 -]+)"', LAYOUT):
        classes |= set(found.split())
    classes |= {"laygrid", "safe", "safe-title", "safe-body", "modegrp"}
    missing = {c for c in classes if not re.search(rf"\.{re.escape(c)}\b", CSS)}
    assert not missing, missing
    assert re.search(r'\[data-lay="off"\]\s*\{[^}]*display:\s*none\s*!important', CSS)   # masquage plus fort que ui.js (hidden, className)
    node = shutil.which("node")
    if not node:
        return
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "layout_test.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr

