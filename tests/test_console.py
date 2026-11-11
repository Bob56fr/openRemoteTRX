# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : enchaînement des actions (commandes simulées)."""
from __future__ import annotations

from trxstation import config as cfgmod
from trxstation.console import TARGET, Console, main
from trxstation.setup_wizard import dummy_config


class FakeRunner:
    def __init__(self, running: bool = False, code: int = 0, creates=None):
        self.calls: list[tuple[list[str], bool]] = []
        self.running, self.code, self.creates = running, code, creates

    def run(self, cmd, *, admin=False):
        self.calls.append((cmd, admin))
        if cmd[:2] == ["systemctl", "stop"]:
            self.running = False
        if cmd[:2] in (["systemctl", "restart"], ["systemctl", "start"]):
            self.running = True
        if "trxstation.setup_wizard" in cmd:
            if self.code == 0 and self.creates is not None:          # l'assistant a écrit la configuration
                self.creates.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
            return self.code
        return 0

    def output(self, cmd):
        return "active" if self.running else "inactive"


def console(tmp_path, answers=(), **runner):
    script = iter(answers)
    out: list[str] = []
    fake = FakeRunner(**runner)
    con = Console(tmp_path / "station.toml", fake, ask=lambda _: next(script, ""), say=out.append, python="py")
    return con, fake, out


def write_config(tmp_path):
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")


def test_assistant_stops_the_station_uses_the_import_and_restarts(tmp_path):
    (tmp_path / "station.import.toml").write_text("", encoding="utf-8")
    con, fake, out = console(tmp_path, answers=["o"], running=True, creates=tmp_path / "station.toml")
    con.assistant()
    commands = [c for c, _ in fake.calls]
    assert commands[0] == ["systemctl", "stop", TARGET]
    setup = next(c for c in commands if "trxstation.setup_wizard" in c)
    assert setup[:3] == ["py", "-m", "trxstation.setup_wizard"] and "--base" in setup
    assert all(admin for c, admin in fake.calls if c[0] == "systemctl" or "setup_wizard" in c)
    assert ["systemctl", "restart", TARGET] in commands               # station relancée à la demande
    assert any("Reprise de la configuration importée" in line for line in out)


def test_failed_assistant_changes_nothing_and_restores_the_running_station(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, running=True, code=1)
    con.assistant()
    commands = [c for c, _ in fake.calls]
    assert ["systemctl", "start", TARGET] in commands and "--base" not in commands[1]
    assert any("rien n'a été modifié" in line for line in out)


def test_hwtest_needs_a_configuration_and_frees_the_port_first(tmp_path):
    con, fake, out = console(tmp_path)
    con.hwtest()
    assert fake.calls == [] and any("menu 3.1" in line for line in out)
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["2", "n"], running=True)
    con.hwtest()
    commands = [c for c, _ in fake.calls]
    assert commands[0] == ["systemctl", "stop", TARGET] and "trxstation.devtools.hwtest" in commands[1]
    assert "--reception-seule" not in commands[1]                      # essai complet
    assert ["systemctl", "restart", TARGET] not in commands            # « n » : station laissée arrêtée


def test_hwtest_offers_a_reception_only_run_and_can_be_cancelled(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["1", "n"])
    con.hwtest()
    assert fake.calls[-1][0][-1] == "--reception-seule"
    con, fake, out = console(tmp_path, answers=[""], running=True)
    con.hwtest()
    assert fake.calls == [] and out[-1] == "Annulé."                    # rien arrêté, rien lancé


def test_leaving_safe_mode_requires_an_explicit_yes(tmp_path):
    write_config(tmp_path)
    con, fake, _ = console(tmp_path, answers=[""])
    con.clear_safe_mode()
    assert fake.calls == []                                            # défaut : non
    con, fake, _ = console(tmp_path, answers=["o"])
    con.clear_safe_mode()
    assert "--clear-safe-mode" in fake.calls[0][0] and fake.calls[0][1] is True
    assert fake.calls[1][0] == ["systemctl", "restart", TARGET]


def test_first_launch_offers_the_assistant_then_menu_quits(tmp_path):
    con, fake, out = console(tmp_path, answers=["n", "z", "", "q"])
    assert con.loop() == 0
    assert any("PAS ENCORE CONFIGURÉE" in line for line in out) and any("Choix inconnu" in line for line in out)
    assert fake.calls == []


def test_diagnostic_command_line_returns_an_exit_code(tmp_path, capsys):
    assert main(["--diagnostic", "--config", str(tmp_path / "absent.toml")]) in (0, 1)
    assert "Bilan" in capsys.readouterr().out


def test_pairing_menu_shows_what_the_android_app_needs_and_falls_back_to_admin_rights(tmp_path, monkeypatch):
    con, fake, out = console(tmp_path)
    con.pairing()
    assert fake.calls == [] and any("menu 3.1" in line for line in out)
    write_config(tmp_path)
    con, fake, out = console(tmp_path)
    con.pairing()
    assert fake.calls == [] and "Appairage" in out[-1] and "cette machine" in out[-1]
    import trxstation.setup_wizard as wizard

    def refused(cfg, addresses=None):
        raise PermissionError("certificat réservé au groupe de la station")
    monkeypatch.setattr(wizard, "pairing_lines", refused)
    con, fake, out = console(tmp_path)
    con.pairing()
    command, admin = fake.calls[0]
    assert admin and command[-1] == "--empreinte" and "trxstation.setup_wizard" in command


def test_help_key_explains_a_menu_without_running_it(tmp_path):
    con, fake, out = console(tmp_path)
    con.help_menu("4.1")
    text = "\n".join(out)
    assert "Menu 4.1 : Appairer un téléphone" in text and "À QUOI IL SERT" in text and "QR code" in text
    assert "<" not in text and fake.calls == []                        # texte simple, rien n'est lancé
    con, fake, out = console(tmp_path, answers=["1.2"])                # numéro demandé
    con.help_menu("")
    assert "Menu 1.2 : Arrêter la station" in "\n".join(out) and "oui" in "\n".join(out) and fake.calls == []
    con, _, out = console(tmp_path)
    con.help_menu("2", theme="1")                                      # dans le thème 1 : son 2e menu
    assert "Menu 1.2 : Arrêter la station" in "\n".join(out)
    con, _, out = console(tmp_path)
    con.help_menu("19")                                                # ancien numéro : accepté
    assert "Menu 4.1 : Appairer un téléphone" in "\n".join(out)
    con, _, out = console(tmp_path)
    con.help_menu("6")
    assert out[-1].startswith("Menu 6 : Mises à jour.")
    con, _, out = console(tmp_path)
    con.help_menu("99")
    assert "Pas de menu 99" in out[-1]


def test_every_menu_has_help_text_shipped_with_the_station(tmp_path):
    import trxstation.console as module
    con, _, _ = console(tmp_path)
    for lang in module.LANGS:
        texts = module.load_help(lang)
        for key, label, fn in con.items:
            assert texts.get(fn.__name__, {}).get("role"), f"menu {key} « {label} » sans aide en {lang} (lancer scripts/build_console_doc.py)"
    assert module.load_help("de")["start"]["role"] != module.load_help("fr")["start"]["role"]


def test_loop_offers_h_and_returns_to_the_menu(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["h 3.1", "", "q"])
    assert con.loop() == 0
    text = "\n".join(out)
    assert "h) Aide sur un menu" in text and "Menu 3.1 : Assistant de configuration" in text and fake.calls == []


def test_main_menu_shows_themes_then_a_theme_its_menus(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["1", "r", "6", "q"])
    assert con.loop() == 0
    text = "\n".join(out)
    assert "  1) Station  (démarrer" in text and "  6) Mises à jour" in text and "  0) Langue / Language" in text
    assert "--- 1) Station ---" in text and "  2) Arrêter la station" in text and "r) Retour au menu principal" in text
    assert "--- 6) Mises à jour ---" in text and "  3) Installer une version depuis un fichier zip" in text
    assert fake.calls == [] or all("systemctl" in c[0] and "is-active" in c[0] for c in fake.calls)


def test_direct_number_and_old_number_run_the_same_menu(tmp_path, monkeypatch):
    import trxstation.console as module
    write_config(tmp_path)
    ran = []
    monkeypatch.setattr(module.Console, "swr_report", lambda self: ran.append("swr"))
    con, _, out = console(tmp_path, answers=["2.5", "", "21", "", "2", "5", "", "q"])
    assert con.loop() == 0
    assert ran == ["swr", "swr", "swr"]                              # 2.5, ancien 21, puis thème 2 > 5
    assert "Le menu 21 est maintenant le menu 2.5" in "\n".join(out)
    con, _, out = console(tmp_path, answers=["7", "4.9", "q"])
    assert con.loop() == 0 and "\n".join(out).count("Choix inconnu.") == 2


def test_every_menu_has_a_number_and_old_numbers_all_lead_somewhere():
    import trxstation.console as module
    methods = [m for _, _, ms in module.MENU_THEMES for m in ms]
    assert len(methods) == len(set(methods)) == len(module.OLD_NUMBERS)
    assert set(module.OLD_NUMBERS.values()) == set(methods)
    assert module.menu_number("install_zip") == "6.3" and module.UPDATE_MENU == module.menu_number("update")
    for name in methods:
        assert callable(getattr(module.Console, name))


def test_language_menu_switches_the_console_and_remembers_it(tmp_path):
    import json
    write_config(tmp_path)
    prefs = tmp_path / "prefs" / "console.json"
    con, _, out = console(tmp_path, answers=["0", "3", "q"])
    con.lang_file = prefs
    assert con.loop() == 0
    text = "\n".join(out)
    assert "  3) Deutsch (de)" in text and json.loads(prefs.read_text())["lang"] == "de"
    assert con.t.lang == "de" and con.t("menu.start") != "Démarrer ou redémarrer la station"
    from trxstation.i18n import load_lang
    assert load_lang(prefs, env={}) == "de"
    con, _, out = console(tmp_path, answers=["0", "9", "q"])
    con.lang_file = prefs
    assert con.loop() == 0 and "Choix inconnu." in "\n".join(out) and con.t.lang == "fr"


def test_diagnostic_shows_breizh_and_visitors_without_secrets(tmp_path, monkeypatch):
    """Menu 1 : Breizh (activé + état de la liaison), écoute des visiteurs, comptes visiteurs ; jamais clé ni mot de passe."""
    import trxstation.console as consolemod
    monkeypatch.setattr(consolemod, "run_all", lambda path: [])
    monkeypatch.setattr(consolemod, "format_checks", lambda checks, color: "Bilan")
    cfg = dummy_config()
    cfg.breizh.enabled, cfg.breizh.host = True, "192.168.1.50"
    cfg.access.max_listeners = 3
    cfg.clients.append(cfgmod.ClientAuth(id="bob", password_hash="scrypt$secret", role="listener", pseudo="Bob",
                                         enabled=False))
    cfg.clients.append(cfgmod.ClientAuth(id="ann", password_hash="scrypt$secret", role="listener", pseudo="Ann",
                                         expires="2020-01-01"))
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con, fake, out = console(tmp_path)
    monkeypatch.setattr(con, "_gateway_status", lambda: None)
    con.diagnostic()
    text = out[-1]
    assert "Breizh Audio Box : activé (192.168.1.50 port" in text and "passerelle arrêtée" in text
    assert "écoute OUVERTE, 3 au plus" in text
    assert "bob « Bob » (désactivé)" in text and "ann « Ann » (jusqu'au 2020-01-01) EXPIRÉ" in text
    assert "secret" not in text

    cfg.breizh.enabled, cfg.access.max_listeners = False, 0
    cfg.clients = [c for c in cfg.clients if c.role != "listener"]
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con.diagnostic()
    assert "Breizh Audio Box : désactivé" in out[-1] and "écoute FERMÉE" in out[-1] and "visiteurs: aucun" in out[-1]


def test_network_menu_reports_exports_and_clears(tmp_path):
    """Menu 23 : synthèses, export anonyme sur le Bureau, « Tout effacer » (station arrêtée : find -delete par sudo)."""
    import zipfile

    from trxstation.netprobe.store import NetStore
    cfg = dummy_config()
    cfg.supervisor.state_dir = str(tmp_path / "etat")
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con, fake, out = console(tmp_path, ["1", "2", "3", "4", "non", "4", "EFFACER", ""])
    con.network()
    assert any("Aucune mesure encore" in line for line in out)
    store = NetStore(tmp_path / "etat" / "netprobe")
    store.add_outage({"start_ms": store.wall_ms() - 9000, "end_ms": store.wall_ms() - 3000, "duration_ms": 6000,
                      "device": "a" * 32, "agent": "android", "diagnosis": "lan", "basis": [], "kind": "in_session"})
    desktop = tmp_path / "Bureau"
    desktop.mkdir()
    con, fake, out = console(tmp_path, ["2", "3", "4", "non", "4", "EFFACER", ""])
    con.desktop = lambda: desktop
    con.network()
    text = "\n".join(out)
    assert "Station arrêtée" in text and "30 derniers jours" in text and "réseau local ou machine de la station" in text
    exports = list(desktop.glob("openremotetrx-reseau-*.zip"))
    assert len(exports) == 1 and zipfile.is_zipfile(exports[0])
    assert "Rien n'a été effacé." in text
    clear = [c for c in fake.calls if c[0][0] == "find"]
    assert len(clear) == 1 and clear[0][1] is True and "seuils.json" in clear[0][0]
