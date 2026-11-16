# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : installation d'un paquet déposé (menu 7.3) et modification de station.toml (menu 8.1)."""
from __future__ import annotations

from pathlib import Path

from trxstation import config as cfgmod
from trxstation.console import Console, find_packages
from trxstation.setup_wizard import dummy_config


class Runner:
    """Commandes simulées ; l'« éditeur » applique `edits` (une fonction par passage) à la copie ouverte."""

    def __init__(self, *, running=False, code=0, edits=()):
        self.calls: list[tuple[list[str], bool]] = []
        self.running, self.code, self.edits = running, code, list(edits)

    def run(self, cmd, *, admin=False):
        self.calls.append((cmd, admin))
        if cmd[0] == "editeur":
            if self.edits:
                path = Path(cmd[1])
                path.write_text(self.edits.pop(0)(path.read_text(encoding="utf-8")), encoding="utf-8")
            return 0
        if cmd[0] == "install":                                    # sudo install : la copie validée remplace l'originale
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            Path(cmd[-1]).write_bytes(Path(cmd[-2]).read_bytes())
        if cmd[:2] == ["rm", "-f"]:
            Path(cmd[-1]).unlink(missing_ok=True)
        if cmd[:2] in (["systemctl", "restart"], ["systemctl", "start"]):
            self.running = True
        return self.code

    def output(self, cmd):
        return "active" if self.running else "inactive"

    def admin_commands(self):
        return [c for c, admin in self.calls if admin]


def make(tmp_path, answers=(), **runner):
    script = iter(answers)
    out: list[str] = []
    fake = Runner(**runner)

    def ask(_):                                  # réponses épuisées : l'utilisateur ferme le terminal (jamais de boucle sans fin)
        try:
            return next(script)
        except StopIteration:
            raise EOFError from None
    con = Console(tmp_path / "etc" / "station.toml", fake, ask=ask, say=out.append, python="py",
                  installed="0.37.0", home=tmp_path / "home", editor="editeur")
    (tmp_path / "home").mkdir(exist_ok=True)
    return con, fake, out


def drop(tmp_path, version, place="Desktop", signed=False):
    folder = tmp_path / "home" / place if place else tmp_path / "home"
    folder.mkdir(parents=True, exist_ok=True)
    package = folder / f"trx-remote-debian-{version}.zip"
    package.write_bytes(b"zip")
    if signed:
        package.with_name(package.name + ".sig").write_text("sig", encoding="utf-8")
    return package


# --------------------------------------------------------------------------- menu 7.3 : paquet déposé

def test_packages_are_found_on_the_desktop_downloads_and_home_newest_first(tmp_path):
    (tmp_path / "home").mkdir()
    drop(tmp_path, "0.36.0", "Téléchargements")
    drop(tmp_path, "0.37.1", "Bureau")
    drop(tmp_path, "0.38.0", "")
    (tmp_path / "home" / "trx-remote-debian-pas-une-version.zip").write_bytes(b"x")
    assert [v for v, _ in find_packages(tmp_path / "home")] == ["0.38.0", "0.37.1", "0.36.0"]


def test_nothing_found_says_where_to_put_the_package(tmp_path):
    con, fake, out = make(tmp_path)
    con.install_zip()
    assert fake.calls == [] and "Aucun paquet" in out[0]


def test_signed_package_installed_after_typing_its_version(tmp_path):
    package = drop(tmp_path, "0.38.0", signed=True)
    con, fake, out = make(tmp_path, answers=["1", "0.38.0"])
    con.install_zip()
    cmd, admin = fake.calls[-1]
    assert admin and cmd[:3] == ["py", "-m", "trxstation.update.apply"]
    assert cmd[-3:] == ["local", "--zip", str(package)] and "--sans-signature" not in cmd
    assert any("signé" in line for line in out)


def test_unsigned_package_needs_oui_then_the_version(tmp_path):
    drop(tmp_path, "0.38.0")
    con, fake, out = make(tmp_path, answers=["1", "non"])
    con.install_zip()
    assert fake.calls == [] and any("NON signé" in line or "PAS SIGNÉ" in line for line in out)
    con, fake, out = make(tmp_path, answers=["1", "oui", "0.38"])            # mauvaise version tapée
    con.install_zip()
    assert fake.calls == []
    con, fake, out = make(tmp_path, answers=["1", "Oui", "0.38.0"])          # casse indifférente
    con.install_zip()
    assert fake.calls[-1][0][-1] == "--sans-signature"


def test_older_package_is_flagged_and_cancel_changes_nothing(tmp_path):
    drop(tmp_path, "0.30.0", signed=True)
    con, fake, out = make(tmp_path, answers=["1", ""])
    con.install_zip()
    assert any("plus ANCIENNE" in line for line in out) and fake.calls == []
    con, fake, out = make(tmp_path, answers=["7"])                           # numéro hors liste
    con.install_zip()
    assert fake.calls == [] and "Annulé" in out[-1]


# --------------------------------------------------------------------------- menu 8.1 : station.toml

def write_config(tmp_path):
    path = tmp_path / "etc" / "station.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(cfgmod.render_toml(dummy_config()), encoding="utf-8")
    return path


def share(text):
    return text.replace("allow_local_tx = true", "allow_local_tx = false")


def test_unchanged_copy_writes_nothing(tmp_path):
    write_config(tmp_path)
    con, fake, out = make(tmp_path)
    con.edit_config()
    assert fake.admin_commands() == [] and "Aucune modification" in out[-1]


def test_valid_change_shows_the_difference_keeps_a_backup_and_offers_a_restart(tmp_path):
    path = write_config(tmp_path)
    before = path.read_text(encoding="utf-8")
    con, fake, out = make(tmp_path, answers=["o", "o"], edits=[share], running=True)
    con.edit_config()
    admin = fake.admin_commands()
    assert admin[0][:2] == ["cp", "-p"] and ".avant-modification-" in admin[0][-1]
    assert admin[1][0] == "install" and admin[1][-1] == str(path)          # droits d'origine (-m -o -g) repris
    assert admin[1][1:3][0] == "-m" and "-o" in admin[1] and "-g" in admin[1]
    assert ["systemctl", "restart", "trx-remote.target"] in admin
    assert path.read_text(encoding="utf-8") == share(before)
    changes = next(line for line in out if line.startswith("Changements"))
    assert "-allow_local_tx = true" in changes and "+allow_local_tx = false" in changes


def test_invalid_change_is_never_written(tmp_path):
    path = write_config(tmp_path)
    before = path.read_text(encoding="utf-8")
    broken = lambda text: text.replace("tot_s = 90", "tot_s = 900")       # noqa: E731 - au-delà du plafond
    con, fake, out = make(tmp_path, answers=["n"], edits=[broken])
    con.edit_config()
    assert fake.admin_commands() == [] and path.read_text(encoding="utf-8") == before
    assert any("REFUSÉE" in line for line in out)
    garbage = "\n[[[ pas du toml\n"
    not_toml = lambda text: text + garbage                                   # noqa: E731
    fixed = lambda text: share(text.replace(garbage, ""))                    # noqa: E731
    con, fake, out = make(tmp_path, answers=["o", "o"], edits=[not_toml, fixed])   # reprise, puis correcte
    con.edit_config()
    assert fake.admin_commands()[1][0] == "install"


def test_refusing_to_save_or_a_concurrent_change_writes_nothing(tmp_path):
    path = write_config(tmp_path)
    con, fake, out = make(tmp_path, answers=["n"], edits=[share])
    con.edit_config()
    assert fake.admin_commands() == []

    def meanwhile(text):
        path.write_text(path.read_text(encoding="utf-8") + "\n# modifié ailleurs\n", encoding="utf-8")
        return share(text)
    con, fake, out = make(tmp_path, answers=["o"], edits=[meanwhile])
    con.edit_config()
    assert fake.admin_commands() == [] and "modifié par ailleurs" in out[-1]


def test_menu_lists_the_two_new_entries(tmp_path):
    con, _, _ = make(tmp_path)
    labels = {key: label for key, label, _ in con.items}
    assert "zip" in labels["7.3"] and "station.toml" in labels["8.1"]


# --------------------------------------------------------------------------- menu 8.2 : tests automatiques

class PytestRunner(Runner):
    def __init__(self, *, pytest_ok=True, installable=True, code=0, running=True):
        super().__init__(running=running)
        self.pytest_ok, self.installable, self.tests_code = pytest_ok, installable, code
        self.logged = []

    def output(self, cmd):
        if "import pytest; print('ok')" in cmd:
            return "ok" if self.pytest_ok else ""
        return super().output(cmd)

    def run(self, cmd, *, admin=False):
        if cmd[1:4] == ["-m", "pip", "install"]:
            self.calls.append((cmd, admin))
            self.pytest_ok = self.installable
            return 0
        if cmd[:2] == ["systemctl", "stop"]:
            self.running = False
        return super().run(cmd, admin=admin)

    def run_logged(self, cmd, log, *, cwd=None):
        self.logged.append((cmd, log, cwd))
        log.write_text("1119 passed\n", encoding="utf-8")
        return self.tests_code


def console_for_tests(tmp_path, answers, **runner):
    write_config(tmp_path)
    (tmp_path / "opt" / "current" / "app" / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Bureau").mkdir(exist_ok=True)
    script = iter(answers)
    out: list[str] = []
    fake = PytestRunner(**runner)
    con = Console(tmp_path / "etc" / "station.toml", fake, ask=lambda _: next(script, ""), say=out.append, python="py",
                  app_dir=tmp_path / "opt", desktop=lambda: tmp_path / "Bureau")
    return con, fake, out


def test_tests_run_on_a_stopped_station_and_the_result_lands_on_the_desktop(tmp_path):
    con, fake, out = console_for_tests(tmp_path, answers=["1", "o", "o"])
    con.expert()
    cmd, log, _ = fake.logged[0]
    assert cmd[:3] == ["py", "-m", "pytest"] and cmd[-1].endswith("tests") and "--basetemp" in cmd
    assert log.parent == tmp_path / "Bureau" and log.read_text(encoding="utf-8") == "1119 passed\n"
    commands = [c for c, _ in fake.calls]
    assert ["systemctl", "stop", "trx-remote.target"] in commands            # station arrêtée pendant les tests
    assert ["systemctl", "restart", "trx-remote.target"] in commands         # puis relancée à la demande
    assert any("Tous les tests passent" in line for line in out)


def test_missing_pytest_is_installed_only_on_request(tmp_path):
    con, fake, out = console_for_tests(tmp_path, answers=["1", "n"], pytest_ok=False)
    con.expert()
    assert fake.logged == [] and not any(c[1:4] == ["-m", "pip", "install"] for c, _ in fake.calls)
    con, fake, out = console_for_tests(tmp_path, answers=["1", "o", "o", "n"], pytest_ok=False)
    con.expert()
    pip = next((c, admin) for c, admin in fake.calls if c[1:4] == ["-m", "pip", "install"])
    assert pip[1] is True and pip[0][-1] == "pytest" and len(fake.logged) == 1
    con, fake, out = console_for_tests(tmp_path, answers=["1", "o"], pytest_ok=False, installable=False)
    con.expert()
    assert fake.logged == [] and "impossible" in out[-1]


def test_failures_point_to_the_saved_result_and_old_versions_say_so(tmp_path):
    con, fake, out = console_for_tests(tmp_path, answers=["1", "o", "n"], code=1)
    con.expert()
    assert any("Des tests échouent" in line and "Bureau" in line for line in out)
    con = Console(tmp_path / "etc" / "station.toml", PytestRunner(), ask=lambda _: "1", say=out.append, python="py",
                  app_dir=tmp_path / "nulle-part")
    con.expert()
    assert "absents de la version installée" in out[-1]


# --------------------------------------------------------------------------- menu 3.1 : seuils de température

def test_temperature_thresholds_are_written_through_the_validated_path(tmp_path):
    path = write_config(tmp_path)
    old = path.read_text(encoding="utf-8").replace("rig_temp_warn_c = 40", "rig_temp_warn_c = 40   # mon commentaire")
    path.write_text(old, encoding="utf-8")
    con, fake, out = make(tmp_path, answers=["45", "", "OUI"])          # 2e seuil inchangé ; « OUI » en majuscules
    con.temperature()
    assert any("1er seuil" in line and "40 °C" in line for line in out)
    text = path.read_text(encoding="utf-8")
    assert "rig_temp_warn_c = 45   # mon commentaire" in text and "rig_temp_cut_c = 50" in text
    assert fake.admin_commands()[1][0] == "install"
    assert cfgmod.load(path).safety.rig_temp_warn_c == 45


def test_temperature_thresholds_added_to_an_old_file_and_bad_values_refused(tmp_path):
    path = write_config(tmp_path)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("rig_temp_")]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")           # station.toml d'avant l'étape 41
    con, fake, out = make(tmp_path, answers=["abc", "42", "48", "Oui"])
    con.temperature()
    assert any("nombre entier" in line for line in out)
    assert (cfgmod.load(path).safety.rig_temp_warn_c, cfgmod.load(path).safety.rig_temp_cut_c) == (42, 48)
    before = path.read_text(encoding="utf-8")
    con, fake, out = make(tmp_path, answers=["60", "55"])                 # 1er seuil au-dessus du 2e : refusé
    con.temperature()
    assert fake.admin_commands() == [] and path.read_text(encoding="utf-8") == before
    assert any("REFUSÉS" in line for line in out)


def test_header_shows_version_and_station_id(tmp_path, monkeypatch):
    from trxstation import console
    from trxstation.station_id import ensure_station_id
    monkeypatch.setattr(console, "config_state_dir", lambda _: tmp_path / "state")
    write_config(tmp_path)
    con, _, _ = make(tmp_path)
    assert f"version {con.installed}" in con.header() and "premier démarrage" in con.header()
    ident = ensure_station_id(tmp_path / "state")
    assert ident in con.header()


def test_header_lines_for_the_address_and_the_rig_vitals():
    from trxstation.console import address_line, rig_vitals_line
    assert address_line("127.0.0.1", 8443, True, ["192.168.1.19"]) == "  Adresse : https://127.0.0.1:8443 (cette machine seulement)"
    assert address_line("0.0.0.0", 8443, True, ["192.168.1.19", "100.64.0.7"]) ==         "  Adresse : https://192.168.1.19:8443, https://100.64.0.7:8443"
    assert address_line("100.64.0.7", 8080, False, ["192.168.1.19"]) == "  Adresse : http://100.64.0.7:8080"
    assert "introuvable" in address_line("0.0.0.0", 8443, True, [])
    assert rig_vitals_line(None) == "  Poste : mesures indisponibles (station arrêtée)"
    assert "liaison CAT" in rig_vitals_line({"connected": False, "levels": {"VD_METER": 13.8}})
    assert rig_vitals_line({"connected": True, "levels": {"VD_METER": 13.84, "TEMP_METER": 41.6}}) ==         "  Poste : alimentation 13,8 V, température 42 °C"
    # IC-7300MK2 : pas de température sous Hamlib ; valeur absente ou illisible = « — »
    assert rig_vitals_line({"connected": True, "levels": {"VD_METER": 14.5}}) == "  Poste : alimentation 14,5 V, température —"
    assert rig_vitals_line({"connected": True, "levels": {"VD_METER": True, "TEMP_METER": "chaud"}}) ==         "  Poste : alimentation —, température —"


def test_header_shows_the_rig_vitals_published_by_the_gateway(tmp_path):
    import time
    from trxstation.status import GatewayStatus, write_status
    path = write_config(tmp_path)
    cfg, _ = cfgmod.load_unchecked(path)
    con, _, _ = make(tmp_path)
    con.addresses = lambda: ["192.168.1.19"]
    assert "mesures indisponibles (station arrêtée)" in con.header()                # aucun fichier d'état
    write_status(cfg.supervisor.status_path, GatewayStatus(pid=1, seq=1, written_at=time.time(), ptt={"state": "RX"},
                                                           rig={"connected": True, "levels": {"VD_METER": 13.8}}))
    header = con.header()
    assert "alimentation 13,8 V, température —" in header
    assert "Adresse : " in header and header.index("Adresse") < header.index("Identifiant de la station")
    con.addresses = lambda: 1 / 0                                                     # jamais d'exception dans l'en-tête
    assert "Poste : alimentation 13,8 V" in con.header()


def test_test_output_is_shown_as_it_comes_with_a_reminder_when_quiet(tmp_path, capsys):
    """Petit PC : les points de pytest s'affichent sans attendre la fin de la ligne, le fichier suit, et un rappel
    « toujours en cours » apparaît quand rien ne bouge (il ne va pas dans le fichier transmis)."""
    import sys as _sys
    from trxstation.console import Runner
    child = "import sys, time; sys.stdout.write('..'); sys.stdout.flush(); time.sleep(1.6); print('é fin')"
    log = tmp_path / "tests.txt"
    assert Runner().run_logged([_sys.executable, "-c", child], log, quiet_after_s=0.5) == 0
    shown = capsys.readouterr().out
    assert shown.index("..") < shown.index("toujours en cours") < shown.index("é fin")
    assert log.read_bytes().decode("utf-8").replace("\r\n", "\n") == "..é fin\n"


# --------------------------------------------------------------------------- menu 4.2 : visiteurs

def _with_operator(tmp_path):
    from trxstation.config import ClientAuth
    from trxstation.passwords import hash_password
    path = write_config(tmp_path)
    cfg = dummy_config()
    cfg.clients = [ClientAuth("phone", password_hash=hash_password("Un mot de passe correct 42"))]
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path


def test_visitors_menu_creates_an_account_and_opens_listening_through_the_validated_path(tmp_path):
    path = _with_operator(tmp_path)
    con, fake, out = make(tmp_path, answers=[
        "2", "club1", "phone", "Radio-club", "", "", "o",            # pseudo = identifiant d'un compte : redemandé
        "1", "5", "", "90", "", "3", "o",
        ""])
    con.visitors()
    text = "\n".join(out)
    con, _, _ = make(tmp_path, answers=["4", "1", "Kriss F4ABC", "o", ""])   # pseudo d'un opérateur : menu 4.3
    con.operators()
    cfg = cfgmod.load(path)
    club = next(c for c in cfg.clients if c.id == "club1")
    assert club.role == "listener" and club.pseudo == "Radio-club" and club.password_hash and not club.expires
    assert cfg.access.max_listeners == 5 and cfg.access.operator_grace_s == 90 and cfg.access.listeners_need_operator
    assert cfg.access.listener_spectrum_fps == 3
    assert next(c for c in cfg.clients if c.id == "phone").pseudo == "Kriss F4ABC"
    assert "identifiant d'un compte" in text and "Mot de passe : " in text and "FERMÉE (0)" in text
    assert "sans redémarrer" in text and not any(c[:2] == ["systemctl", "restart"] for c in fake.admin_commands())


def test_visitors_menu_disables_deletes_and_refuses_bad_dates(tmp_path):
    path = _with_operator(tmp_path)
    con, _, _ = make(tmp_path, answers=["2", "club1", "", "31/12/2026", "2026-12-31", "", "o", ""])
    con.visitors()
    assert next(c for c in cfgmod.load(path).clients if c.id == "club1").expires == "2026-12-31"
    con, _, _ = make(tmp_path, answers=["3", "1", "", "n", "", "", "o", ""])      # désactivé, pas de nouveau mot de passe
    con.visitors()
    assert next(c for c in cfgmod.load(path).clients if c.id == "club1").enabled is False
    con, _, _ = make(tmp_path, answers=["4", "1", "o", "o", ""])
    con.visitors()
    assert [c.id for c in cfgmod.load(path).clients] == ["phone"]


def test_visitors_menu_kick_writes_a_request_for_a_connected_listener_only(tmp_path):
    import json
    import time
    from trxstation.gateway.access_watch import KICK_REQUEST
    from trxstation.status import GatewayStatus, write_status
    path = _with_operator(tmp_path)
    state = tmp_path / "state"
    cfg = cfgmod.load(path)
    cfg.supervisor.state_dir, cfg.supervisor.status_path = str(state), str(state / "status.json")
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    con, fake, out = make(tmp_path, answers=[""])
    con.visitors()
    assert any("aucun visiteur" in line for line in out)
    write_status(state / "status.json", GatewayStatus(pid=1, seq=1, written_at=time.time(), ptt={"state": "RX"}, rig={},
                 presence={"connections": [{"id": "phone", "pseudo": "Opérateur", "role": "operator", "source": "a", "since_s": 5},
                                           {"id": "club1", "pseudo": "Radio-club", "role": "listener", "source": "b", "since_s": 125}]}))
    con, fake, out = make(tmp_path, answers=["5", "1", "o", ""])
    con.visitors()
    assert any("Radio-club (club1, b, 2 min)" in line for line in out)
    request = json.loads((state / KICK_REQUEST).read_text(encoding="utf-8"))
    assert request["id"] == "club1" and abs(request["at"] - time.time()) < 5


# --------------------------------------------------------------------------- menu 4.3 : comptes opérateurs

def test_operators_menu_adds_one_account_per_device_and_offers_its_pairing(tmp_path, monkeypatch):
    import trxstation.setup_wizard as wizard
    path = _with_operator(tmp_path)
    shown = []
    monkeypatch.setattr(wizard, "show_pairing", lambda cfg, ask, say, user=None: shown.append(user))
    con, fake, out = make(tmp_path, answers=[
        "1", "phone", "1", "S25", "", "", "o", "o",                 # « phone » existe déjà : refusé
        ""])
    con.operators()
    cfg = cfgmod.load(path)
    s25 = next(c for c in cfg.clients if c.id == "S25")
    assert s25.role == "operator" and s25.enabled and s25.password_hash and not s25.pseudo
    assert shown == ["S25"]
    text = "\n".join(out)
    assert "UN PAR APPAREIL" in text and "déjà utilisé" in text and "Mot de passe : " in text
    assert "sans redémarrer" in text and not any(c[:2] == ["systemctl", "restart"] for c in fake.admin_commands())


def test_operators_menu_never_disables_nor_deletes_the_last_active_operator(tmp_path):
    path = _with_operator(tmp_path)
    con, _, out = make(tmp_path, answers=["3", "1", "5", "1", ""])
    con.operators()
    assert [(c.id, c.enabled) for c in cfgmod.load(path).clients] == [("phone", True)]
    assert sum("dernier compte opérateur actif" in line for line in out) == 2


def test_operators_menu_changes_password_disables_reenables_and_deletes(tmp_path):
    from trxstation.passwords import verify_password
    path = _with_operator(tmp_path)
    con, _, _ = make(tmp_path, answers=["1", "PC", "", "Un autre mot de passe correct 77", "o", "n", ""])
    con.operators()
    con, _, _ = make(tmp_path, answers=["2", "2", "Encore un mot de passe correct 55", "o", ""])
    con.operators()
    pc = next(c for c in cfgmod.load(path).clients if c.id == "PC")
    assert verify_password("Encore un mot de passe correct 55", pc.password_hash)
    con, _, out = make(tmp_path, answers=["3", "1", "o", "o", ""])     # phone désactivé : PC reste actif
    con.operators()
    assert next(c for c in cfgmod.load(path).clients if c.id == "phone").enabled is False
    con, _, out = make(tmp_path, answers=["5", "2", ""])              # PC = dernier actif : refusé
    con.operators()
    assert any("dernier compte opérateur actif" in line for line in out)
    con, _, _ = make(tmp_path, answers=["3", "1", "o", "5", "1", "o", "o", ""])   # phone réactivé puis supprimé
    con.operators()
    assert [(c.id, c.enabled) for c in cfgmod.load(path).clients] == [("PC", True)]


def test_operators_menu_is_in_the_access_theme():
    from trxstation.console import menu_number
    assert menu_number("operators") == "4.3"


# --------------------------------------------------------------------------- menu 5.2 : Breizh Audio Box

def test_breizh_menu_creates_the_key_shows_it_once_and_never_again(tmp_path):
    from trxstation.breizh.keyfile import read_key
    from trxstation.breizh.protocol import key_to_text
    write_config(tmp_path)
    con, fake, out = make(tmp_path, answers=["1", ""])
    con.addresses = lambda: ["192.0.2.10"]
    con.breizh()
    key_file = tmp_path / "etc" / "breizh.key"
    text = key_to_text(read_key(key_file))
    shown = "\n".join(out)
    assert text in shown and "192.0.2.10" in shown and "port UDP = 47100" in shown and "pare-feu" in shown
    assert shown.count(text) == 1                                              # montrée une seule fois
    con, fake, out = make(tmp_path, answers=["1", "n", ""])                   # remplacement refusé : clé inchangée
    con.breizh()
    assert key_to_text(read_key(key_file)) == text and text not in "\n".join(out)
    assert any("présente" in line for line in out)


def test_breizh_menu_settings_refuse_a_public_address_and_go_through_the_validated_path(tmp_path):
    path = write_config(tmp_path)
    con, fake, out = make(tmp_path, answers=["2", "8.8.8.8", "breizh.local", "192.168.1.50", "47200", "o", "o", ""])
    con.breizh()
    b = cfgmod.load(path).breizh
    assert b.enabled is True and b.host == "192.168.1.50" and b.port == 47200
    text = "\n".join(out)
    assert text.count("Adresse IP PRIVÉE attendue") == 2 and "pas encore de clé" in text
    assert "prochain démarrage" in text and any(c[0] == "install" for c in fake.admin_commands())


def test_breizh_menu_probe_runs_the_fake_station_without_sound(tmp_path):
    path = write_config(tmp_path)
    con, fake, out = make(tmp_path, answers=["3", ""])
    con.breizh()
    assert any("adresse de Breizh" in line for line in out) and not fake.calls
    cfg = cfgmod.load(path)
    cfg.breizh.host = "192.168.1.50"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    (tmp_path / "etc" / "breizh.key").write_text("x" * 43 + "\n", encoding="utf-8")
    con, fake, out = make(tmp_path, answers=["3", ""])
    con.breizh()
    cmd = fake.calls[-1][0]
    assert cmd[:3] == ["py", "-m", "trxstation.devtools.breizh_probe"] and "--sans-son" in cmd
    assert cmd[cmd.index("--host") + 1] == "192.168.1.50" and cmd[cmd.index("--key-file") + 1].endswith("breizh.key")


def test_breizh_menu_probe_is_not_run_while_the_station_link_is_in_service(tmp_path):
    import time
    from trxstation.status import GatewayStatus, write_status
    path = write_config(tmp_path)
    state = tmp_path / "state"
    cfg = cfgmod.load(path)
    cfg.supervisor.state_dir, cfg.supervisor.status_path = str(state), str(state / "status.json")
    cfg.breizh.enabled, cfg.breizh.host = True, "192.168.1.50"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    (tmp_path / "etc" / "breizh.key").write_text("x" * 43 + "\n", encoding="utf-8")
    write_status(state / "status.json", GatewayStatus(pid=1, seq=1, written_at=time.time(), ptt={"state": "RX"}, rig={},
                 breizh={"state": "ready", "route": "breizh", "rtt_ms": 20, "peer": "Breizh 0.10.0"}))
    con, fake, out = make(tmp_path, answers=["3", ""])
    con.breizh()
    assert not fake.calls and any("EN SERVICE (Breizh 0.10.0, aller-retour 20 ms) : essai inutile" in line for line in out)


def test_breizh_menu_shows_the_live_link_and_the_journal(tmp_path):
    import time
    from trxstation.breizh.store import BreizhStore
    from trxstation.status import GatewayStatus, write_status
    path = write_config(tmp_path)
    state = tmp_path / "state"
    cfg = cfgmod.load(path)
    cfg.supervisor.state_dir, cfg.supervisor.status_path = str(state), str(state / "status.json")
    cfg.breizh.enabled, cfg.breizh.host = True, "192.168.1.50"
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    BreizhStore(state).event("connected", "Breizh 0.10.0 joint (traitement annoncé : 12 ms)")
    write_status(state / "status.json", GatewayStatus(pid=1, seq=1, written_at=time.time(), ptt={"state": "RX"}, rig={},
                 breizh={"state": "ready", "route": "breizh", "bypass": False, "rtt_ms": 2, "peer": "Breizh 0.10.0"}))
    con, fake, out = make(tmp_path, answers=["4", ""])
    con.breizh()
    text = "\n".join(out)
    assert "prêt : prochaines émissions par Breizh · route breizh · Breizh 0.10.0 · aller-retour 2 ms" in text
    assert text.count("Breizh 0.10.0 joint") >= 2                              # résumé (3 dernières) et journal


# --------------------------------------------------------------------------- parties de l'assistant (étape 220)

def test_a_wizard_part_stops_the_station_when_the_port_must_be_free_and_offers_a_restart(tmp_path):
    path = write_config(tmp_path)

    class PartRunner(Runner):
        def run(self, cmd, *, admin=False):
            if "--partie" in cmd:                              # la partie écrit une configuration changée
                self.calls.append((cmd, admin))
                path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                return 0
            return super().run(cmd, admin=admin)

    fake = PartRunner(running=True)
    out: list[str] = []
    answers = iter(["o"])
    con = Console(path, fake, ask=lambda _: next(answers), say=out.append, python="py", installed="0.37.0",
                  home=tmp_path / "home", editor="editeur")
    con.rig()
    part = next(c for c, admin in fake.calls if "--partie" in c)
    assert part[-1] == "poste" and ("--partie" in part) and any(admin for c, admin in fake.calls if "--partie" in c)
    commands = [" ".join(c) for c, _ in fake.calls]
    assert any("stop" in c for c in commands[:commands.index(" ".join(part))])      # arrêtée AVANT les questions
    assert any("restart" in c or "start" in c for c in commands[commands.index(" ".join(part)) + 1:])


def test_a_wizard_part_that_changes_nothing_says_so_and_needs_a_configuration(tmp_path):
    con, fake, out = make(tmp_path)
    con.bands()
    assert "menu 2.1" in out[-1] and fake.calls == []
    write_config(tmp_path)
    con, fake, out = make(tmp_path)
    con.transmit()
    assert out[-1] == "Rien n'a été modifié." and fake.calls[-1][0][-2:] == ["--partie", "emission"]


# --------------------------------------------------------------------------- écrans dédiés (étape 221)

def test_local_operator_screen_changes_only_the_supervisor_rules_through_the_validated_path(tmp_path):
    path = write_config(tmp_path)
    con, fake, out = make(tmp_path, answers=["n", "150", "o"])           # plus partagée, TOT absolu 150 s, enregistrer
    con.local_operator()
    cfg = cfgmod.load(path)
    assert cfg.supervisor.allow_local_tx is False and cfg.supervisor.tot_abs_s == 150
    assert "ne peut que couper" in "\n".join(out)
    con, _, out = make(tmp_path, answers=["o", "100", "", "250", "o"])  # TOT absolu sous le plafond : redemandé
    con.local_operator()
    cfg = cfgmod.load(path)
    assert cfg.supervisor.allow_local_tx is True and cfg.supervisor.tot_abs_s == 150 and cfg.supervisor.local_tx_max_s == 250


def test_alerts_screen_hides_the_secret_topic_and_sends_a_test(tmp_path, monkeypatch):
    from trxstation.supervisor import notify
    path = write_config(tmp_path)
    sent = []
    monkeypatch.setattr(notify, "_default_post", lambda url, title, message, priority="": sent.append((url, title)))
    con, _, out = make(tmp_path, answers=["4", "1", "ftp://x", "1", "https://ntfy.sh/sujet-tres-secret-42", "o",
                                          "3", "0,5", "o", "4", ""])
    con.alerts()
    cfg = cfgmod.load(path)
    assert cfg.supervisor.notify_url == "https://ntfy.sh/sujet-tres-secret-42" and cfg.supervisor.alive_every_h == 0.5
    text = "\n".join(out)
    assert "Aucune adresse" in text and "Refusé" in text and "https://ntfy.sh/suj…" in text
    assert "sujet-tres-secret" not in text                               # jamais l'adresse entière à l'écran
    assert sent and sent[-1][0] == cfg.supervisor.notify_url and sent[-1][1].startswith("ORT-8025")
    assert "Alerte d'essai envoyée" in text

    def broken(*_a, **_k):
        raise OSError("réseau injoignable")
    monkeypatch.setattr(notify, "_default_post", broken)
    con, _, out = make(tmp_path, answers=["4", ""])
    con.alerts()
    assert any("Échec de l'envoi : réseau injoignable" in line for line in out)


def test_features_switch_sets_enabled_and_the_module_together(tmp_path):
    from trxstation.console import FEATURES, feature_on
    path = write_config(tmp_path)
    number = str([f[0] for f in FEATURES].index("features.freedv_activity") + 1)
    con, _, out = make(tmp_path, answers=[number, "o", ""])
    con.features_switch()
    cfg = cfgmod.load(path)
    assert "freedv_activity" in cfg.modules.run
    con, _, out = make(tmp_path, answers=[""])
    con.features_switch()
    shown = "\n".join(out)
    assert "[EN SERVICE] Activité FreeDV" in shown and "[arrêt] SELCALL" in shown
    number = str([f[0] for f in FEATURES].index("features.swr") + 1)
    con, _, _ = make(tmp_path, answers=[number, "o", ""])
    con.features_switch()
    assert cfgmod.load(path).swr.enabled is False
    cluster = str([f[0] for f in FEATURES].index("features.cluster") + 1)       # réglages manquants : refus, rien d'écrit
    before = path.read_bytes()
    con, _, out = make(tmp_path, answers=[cluster, ""])
    con.features_switch()
    assert path.read_bytes() == before and any("REFUSÉ" in line for line in out) and "menu 5.1" in "\n".join(out)
    assert not feature_on(cfgmod.load(path), "cluster", "cluster")


# --------------------------------------------------------------------------- TRX Console sous Windows (étape 222)

def test_windows_saves_station_toml_without_sudo_cp_or_install(tmp_path, monkeypatch):
    import trxstation.console as module
    monkeypatch.setattr(module, "IS_WINDOWS", True)
    path = write_config(tmp_path)
    con, fake, _ = make(tmp_path, answers=["n", "150", "o"])
    con.local_operator()
    assert cfgmod.load(path).supervisor.tot_abs_s == 150
    assert not any(c[0] in ("cp", "install", "sudo") for c, _ in fake.calls)                # aucune commande Unix
    assert list(path.parent.glob("station.toml.avant-modification-*"))                    # sauvegarde gardée
    target = tmp_path / "etat" / "demande.json"
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    assert con._install_file(source, target, parents=True) == 0 and target.read_text(encoding="utf-8") == "{}"
    assert con._remove_file(target) == 0 and not target.exists() and fake.calls == []


def test_windows_indicator_and_updates_are_told_honestly(tmp_path, monkeypatch):
    import trxstation.console as module
    monkeypatch.setattr(module, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    con, fake, out = make(tmp_path, answers=["1"])
    spawned = []
    fake.spawn = lambda cmd: spawned.append(cmd) or True
    con.indicator()
    assert spawned and spawned[0][-2:] == ["-m", "trxstation.tray"] and "Indicateur lancé" in out[-1]
    con, fake, out = make(tmp_path, answers=["2"])
    con.indicator()
    assert fake.calls[-1][0][0] == "powershell.exe" and "TRX distant - indicateur.lnk" in fake.calls[-1][0][-1]
    startup = module.windows_tray_startup()
    startup.parent.mkdir(parents=True)
    startup.write_bytes(b"lnk")
    con, fake, out = make(tmp_path, answers=["2"])
    con.indicator()
    assert not startup.exists() and "ne se lancera plus" in out[-1]
    for menu in ("update", "rollback", "install_zip"):
        con, fake, out = make(tmp_path)
        getattr(con, menu)()
        assert "installer.cmd" in out[-1] and fake.calls == []
