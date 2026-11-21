# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""openRemoteTRX Console : enchaînement des actions (commandes simulées)."""
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
    assert fake.calls == [] and any("menu 2.1" in line for line in out)
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


def test_qualif_menu_runs_trx_qualif_with_the_chosen_mode(tmp_path):
    con, fake, out = console(tmp_path)
    con.qualif()
    assert fake.calls == [] and any("menu 2.1" in line for line in out)
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["1"], running=True)
    con.qualif()                                                       # cahier : ne touche pas au poste
    assert [c for c, _ in fake.calls if c[0] == "systemctl"] == [] and fake.calls[-1][0][-1] == "--plan"
    con, fake, out = console(tmp_path, answers=["2", "o"], running=True)
    con.qualif()                                                       # exploration : station arrêtée, puis relancée
    commands = [c for c, _ in fake.calls]
    assert commands[0] == ["systemctl", "stop", TARGET] and "trxstation.qualif.main" in commands[1]
    assert commands[1][-1] == "--explorer" and "--output" in commands[1] and fake.calls[1][1] is True
    assert ["systemctl", "restart", TARGET] in commands
    for choice, last in (("3", "--lecture-seule"), ("4", "--sans-emission")):
        con, fake, out = console(tmp_path, answers=[choice, "n"])
        con.qualif()
        assert fake.calls[-1][0][-1] == last
    con, fake, out = console(tmp_path, answers=["5", "n"])
    con.qualif()                                                       # complète : aucune option d'émission à part
    assert fake.calls[-1][0][-2] == "--output"
    con, fake, out = console(tmp_path, answers=["6"], running=True)
    con.qualif()                                                       # valise : elle gère la station elle-même
    commands = [c for c, _ in fake.calls]
    assert [c for c in commands if c[0] == "systemctl"] == [] and commands[-1][-1] == "--terrain"
    con, fake, out = console(tmp_path, answers=["9"], running=True)
    con.qualif()
    assert fake.calls == [] and out[-1] == "Annulé."


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
    assert fake.calls == [] and any("menu 2.1" in line for line in out)
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
    con.help_menu("7")
    assert out[-1].startswith("Menu 7 : Mises à jour.")
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
    con, fake, out = console(tmp_path, answers=["h 2.1", "", "q"])
    assert con.loop() == 0
    text = "\n".join(out)
    assert "h) Aide sur un menu" in text and "Menu 2.1 : Assistant de configuration" in text and fake.calls == []


def test_main_menu_shows_themes_then_a_theme_its_menus(tmp_path):
    write_config(tmp_path)
    con, fake, out = console(tmp_path, answers=["1", "r", "7", "q"])
    assert con.loop() == 0
    text = "\n".join(out)
    assert "  1) Station openRemoteTRX  (démarrer" in text and "  7) Mises à jour" in text and "  8) Expert et préférences" in text and "  0) Langue et niveau / Language & level" in text
    assert "--- 1) Station openRemoteTRX ---" in text and "  2) Arrêter la station" in text and "r) Retour au menu principal" in text
    assert "--- 7) Mises à jour ---" in text and "  3) Installer une version depuis un fichier zip" in text
    assert fake.calls == [] or all("systemctl" in c[0] and "is-active" in c[0] for c in fake.calls)


def test_direct_number_and_old_number_run_the_same_menu(tmp_path, monkeypatch):
    import trxstation.console as module
    write_config(tmp_path)
    ran = []
    monkeypatch.setattr(module.Console, "swr_report", lambda self: ran.append("swr"))
    con, _, out = console(tmp_path, answers=["5.4", "", "21", "", "5", "4", "", "q"])
    assert con.loop() == 0
    assert ran == ["swr", "swr", "swr"]                              # 5.4, ancien 21, puis thème 5 > 4
    assert "Le menu 21 est maintenant le menu 5.4" in "\n".join(out)
    con, _, out = console(tmp_path, answers=["9", "4.9", "q"])
    assert con.loop() == 0 and "\n".join(out).count("Choix inconnu.") == 2


def test_every_menu_has_a_number_and_old_numbers_all_lead_somewhere():
    import trxstation.console as module
    methods = [m for _, _, ms in module.MENU_THEMES for m in ms]
    assert len(methods) == len(set(methods))
    assert len(set(module.OLD_NUMBERS.values())) == len(module.OLD_NUMBERS)
    # Menus nés APRÈS la renumérotation par thème (étape 169) : pas d'ancien numéro.
    assert set(methods) - set(module.OLD_NUMBERS.values()) == {"qualif", "operators", "certificate", "sdr", "monitoring",
                                                                 "rig", "sound", "hf_spectrum", "bands", "transmit", "access_network",
                                                                 "local_operator", "alerts", "features_switch",
                                                                 "remote_console", "diffusion", "remote_power", "rx_gain"}
    assert set(module.OLD_NUMBERS.values()) <= set(methods)
    assert module.menu_number("install_zip") == "7.3" and module.UPDATE_MENU == module.menu_number("update")
    for name in methods:
        assert callable(getattr(module.Console, name))


def test_language_menu_switches_the_console_and_remembers_it(tmp_path):
    import json
    write_config(tmp_path)
    prefs = tmp_path / "prefs" / "console.json"
    con, _, out = console(tmp_path, answers=["0", "3", "", "q"])           # Entrée : niveau gardé
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


def test_display_level_hides_menus_without_forbidding_them(tmp_path):
    """Étape 234 : Basic cache les thèmes et menus avancés ; un numéro tapé ouvre quand même son menu, signalé."""
    import json

    from trxstation.console import BASIC_MENUS, EXPERT_MENUS, MENU_THEMES, menu_level
    from trxstation.i18n import load_level
    write_config(tmp_path)
    prefs = tmp_path / "prefs" / "console.json"
    con, _, out = console(tmp_path, answers=["0", "", "1", "2", "r", "3.1", "", "q"])
    con.lang_file = prefs

    def temperature():                                                   # menu Expert, sans ses questions
        out.append("menu 3.1 ouvert")
    con.temperature = temperature
    assert con.loop() == 0
    text = "\n".join(out)
    assert con.level == "basic" and json.loads(prefs.read_text())["level"] == "basic"
    after = text.split("Niveau d'affichage : Basic.", 1)[1]
    main = after.split("--- 2)")[0]
    assert "  1) Station" in main and "  8) Expert" not in main and "  3) Sécurité" not in main
    theme2 = after.split("--- 2)", 1)[1].split("r)", 1)[0]
    assert "2) Essai du poste" in theme2 and "3) Profils" not in theme2   # thème 2 sans ses menus Normal
    assert "Menu 3.1 (niveau Expert) : caché au niveau choisi, ouvert quand même." in text
    assert "Niveau d'affichage : Basic (menu 0 pour changer)" in text
    methods = {m for _, _, ms in MENU_THEMES for m in ms}
    assert BASIC_MENUS <= methods and EXPERT_MENUS <= methods and menu_level("alerts") == "normal"
    fresh = tmp_path / "neuf.json"
    assert load_level(fresh, configured=False) == "basic" and json.loads(fresh.read_text())["level"] == "basic"
    assert load_level(fresh, configured=True) == "basic"                  # le défaut enregistré ne bouge plus
    assert load_level(tmp_path / "ancien.json", configured=True) == "basic"               # Basic partout (étape 235)


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
    """Menu 6.4 : synthèses, export anonyme sur le Bureau, « Tout effacer » (station arrêtée : find -delete par sudo)."""
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


def test_language_menu_comes_first_in_yellow_and_the_station_state_is_coloured(tmp_path):
    write_config(tmp_path)
    con, _, out = console(tmp_path, running=True)
    con.color = True
    con.show_main()
    text = "\n".join(out)
    assert "\x1b[1;32mStation en marche\x1b[0m" in text
    menu = [line for line in text.splitlines() if line.strip()[:2] in ("0)", "1)", "6)") or "\x1b[1;33m0)" in line]
    assert "\x1b[1;33m0) Langue et niveau / Language & level" in menu[0] and menu[1].strip().startswith("1) Station")
    con, _, out = console(tmp_path, running=False)
    con.color = True
    assert "\x1b[1;31mStation arrêtée\x1b[0m" in con.header()
    con.color = False                                                 # hors d'un terminal : aucune couleur
    assert "\x1b" not in con.header() and "Station arrêtée" in con.header()
    con, _, _ = console(tmp_path / "vide", running=False)
    con.color = True
    assert "\x1b[1;33mStation PAS ENCORE CONFIGURÉE" in con.header()


def test_certificate_menu_remakes_the_certificate_with_the_station_authority(tmp_path):
    from trxstation.setup_wizard import _make_certificate
    cfg = dummy_config()
    cfg.network.gateway_bind = "0.0.0.0"
    _make_certificate(["192.168.1.10", "station"], tmp_path / "tls", cfg)
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con, fake, out = console(tmp_path, answers=["2", "10.8.0.1", "o", "o"])
    con.certificate()
    text = "\n".join(out)
    assert "AUTORITÉ DE LA STATION" in text and "192.168.1.10" in text and "/station-ca.crt" in text
    setup = next(c for c, admin in fake.calls if "trxstation.setup_wizard" in c and admin)
    assert setup[-2:] == ["--autorite-station", "10.8.0.1"]
    assert ["systemctl", "restart", TARGET] in [c for c, _ in fake.calls]
    con, fake, out = console(tmp_path, answers=["1", "n"])                    # refus : rien n'est lancé
    con.certificate()
    assert not any("trxstation.setup_wizard" in c for c, _ in fake.calls)


def test_setup_wizard_switches_an_existing_station_to_its_authority(tmp_path):
    from trxstation.gateway.api.tls import CA_CERT, certificate_hosts, generate_self_signed
    from trxstation.setup_wizard import main as setup_main
    cfg = dummy_config()
    tls = tmp_path / "tls"
    generate_self_signed(["192.168.1.10", "station"], tls / "station-cert.pem", tls / "station-key.pem")
    cfg.network.tls_cert, cfg.network.tls_key = str(tls / "station-cert.pem"), str(tls / "station-key.pem")
    cfg.network.gateway_bind = "0.0.0.0"
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    assert setup_main(["--output", str(tmp_path / "station.toml"), "--autorite-station", "10.8.0.1"]) == 0
    assert (tls / CA_CERT).is_file()
    assert certificate_hosts(tls / "station-cert.pem") == ["192.168.1.10", "10.8.0.1", "station"]


def test_sdr_menu_chooses_a_free_sdrplay_by_serial_and_refuses_held_or_duplicated_ones(tmp_path):
    import json as _json
    write_config(tmp_path)
    listing = {"devices": [
        {"kind": "sdrplay", "model": "RSP2 / RSP2pro", "serial": "170502EC10", "state": "pris", "location": "bus 3, port 3", "duplicate": False},
        {"kind": "sdrplay", "model": "RSP2 / RSP2pro", "serial": "170502E910", "state": "libre", "location": "bus 3, port 5", "duplicate": False},
        {"kind": "rtlsdr", "model": "RTL-SDR (RTLSDRBlog Blog V4)", "serial": "00000001", "state": "libre", "location": "bus 3, port 6", "duplicate": True}],
        "warnings": []}

    class Lister(FakeRunner):
        def output(self, cmd):
            return _json.dumps(listing) if "trxstation.sdr.devices" in cmd else super().output(cmd)

        def run(self, cmd, *, admin=False):
            if cmd[0] == "install":                                   # enregistrement : le brouillon validé est copié
                import shutil
                shutil.copyfile(cmd[-2], cmd[-1])
            return super().run(cmd, admin=admin)

    # choisir n° 1 (pris), n° 3 (RTL), n° 2 (libre, enregistré), puis mise en service (enregistrée), retour
    script = iter(["2", "1", "2", "3", "2", "2", "o", "6", "o", ""])
    out: list[str] = []
    fake = Lister()
    con = Console(tmp_path / "station.toml", fake, ask=lambda _: next(script, ""), say=out.append, python="py")
    con.sdr()
    text = "\n".join(out)
    assert "pris par une autre application" in text                  # 1 = celui de l'AIS : refusé
    assert "numéro de série unique" in text                            # 3 = clé RTL au numéro en double
    cfg = cfgmod.load(tmp_path / "station.toml")
    assert cfg.sdr.serial == "170502E910" and cfg.sdr.enabled is True and "sdr" in cfg.modules.run


def test_sdr_menu_rewrites_the_serial_of_the_only_rtl_sdr_key_and_follows_it(tmp_path):
    import json as _json
    cfg = dummy_config()
    cfg.sdr.serial, cfg.sdr.driver, cfg.sdr.sample_rate_hz = "00000001", "rtlsdr", 2_048_000
    cfg.supervisor.state_dir = str(tmp_path / "state")
    (tmp_path / "station.toml").write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    keys = [{"kind": "rtlsdr", "model": "RTL-SDR (RTLSDRBlog Blog V4)", "serial": "00000001", "state": "station"}]

    class Keys(FakeRunner):
        def output(self, cmd):
            if any("rtl_eeprom" in part for part in cmd):                    # relecture de la mémoire de la clé
                return "Serial number:\t\tRTLV4A\nSerial number enabled:\tyes"
            return _json.dumps({"devices": keys}) if "trxstation.sdr.devices" in cmd else super().output(cmd)

        def run(self, cmd, *, admin=False):
            if cmd[0] == "rtl_eeprom":                                       # rend 1 même quand il réussit (réel)
                self.calls.append((cmd, admin))
                return 1
            return super().run(cmd, admin=admin) if cmd[0] != "install" else self._install(cmd, admin)

        def _install(self, cmd, admin):
            import shutil
            shutil.copyfile(cmd[-2], cmd[-1])
            return super().run(cmd, admin=admin)

    out: list[str] = []
    fake = Keys(running=True)
    script = iter(["7", "RTLV4A", "o", "o", "n", ""])
    con = Console(tmp_path / "station.toml", fake, ask=lambda _: next(script, ""), say=out.append, python="py")
    con.sdr()
    calls = [c for c, _ in fake.calls]
    assert ["systemctl", "stop", TARGET] in calls                          # sa clé : station arrêtée avant
    eeprom = [c for c in calls if c[0] == "rtl_eeprom"]
    assert eeprom[0][:4] == ["rtl_eeprom", "-d", "0", "-r"] and eeprom[1] == ["rtl_eeprom", "-d", "0", "-s", "RTLV4A"]
    assert all(admin for c, admin in fake.calls if c[0] == "rtl_eeprom")
    assert cfgmod.load(tmp_path / "station.toml").sdr.serial == "RTLV4A"
    assert any("REBRANCHEZ" in line for line in out)
    keys.append(dict(keys[0], serial="00000002", state="libre"))         # deux clés : refus, rien n'est écrit
    fake2 = Keys()
    con = Console(tmp_path / "station.toml", fake2, ask=lambda _: next(iter(["7", ""])), say=out.append, python="py")
    script2 = iter(["7", ""])
    con.ask = lambda _: next(script2, "")
    con.sdr()
    assert not any(c[0] == "rtl_eeprom" for c, _ in fake2.calls) and "UNE SEULE clé" in out[-3] + out[-2] + out[-1]


def test_every_menu_number_quoted_to_the_operator_exists():
    """Renumérotation de l'étape 219 : un texte montré à l'opérateur (console, mode d'emploi, guide, codes d'erreur,
    page, notices) ne cite jamais un menu qui n'existe pas, ni un ancien numéro à un niveau (10 à 24)."""
    import re
    from pathlib import Path
    import trxstation.console as module
    root = Path(module.__file__).resolve().parents[1]
    valid = {module.menu_number(m) for _, _, ms in module.MENU_THEMES for m in ms}
    files = [*root.glob("trxstation/i18n/console.*.json"), *root.glob("docs/console/contenu*.toml"),
             *root.glob("User-Guide/**/*.md"), root / "trxstation/errors/catalog.yaml", root / "README.md",
             root / "README.fr.md", root / "debian/LISEZMOI.txt", root / "windows/notice-windows.html",
             *root.glob("trxstation/gateway/api/static/*.js"), root / "trxstation/gateway/api/static/index.html"]
    word = r"(?:[Mm]enus?|Menüs?|men[úu]s?)\s+\**"
    for path in files:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(word + r"(\d+(?:\.\d+)?)(?![\d.])", text):
            number = m.group(1)
            if "." in number:
                assert number in valid, f"{path.name} : menu {number} inexistant"
            else:
                assert not 10 <= int(number) <= 24, f"{path.name} : ancien numéro de menu {number}"
