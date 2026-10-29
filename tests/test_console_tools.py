# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""TRX Console : installation d'un paquet déposé (menu 13) et modification de station.toml (menu 14)."""
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


# --------------------------------------------------------------------------- menu 13 : paquet déposé

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


# --------------------------------------------------------------------------- menu 14 : station.toml

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
    assert "zip" in labels["13"] and "station.toml" in labels["14"]


# --------------------------------------------------------------------------- menu 15 : tests automatiques

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


# --------------------------------------------------------------------------- menu 16 : seuils de température

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


# --------------------------------------------------------------------------- menu 20 : visiteurs

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
        "5", "1", "Kriss F4ABC", "o",
        ""])
    con.visitors()
    cfg = cfgmod.load(path)
    club = next(c for c in cfg.clients if c.id == "club1")
    assert club.role == "listener" and club.pseudo == "Radio-club" and club.password_hash and not club.expires
    assert cfg.access.max_listeners == 5 and cfg.access.operator_grace_s == 90 and cfg.access.listeners_need_operator
    assert cfg.access.listener_spectrum_fps == 3
    assert next(c for c in cfg.clients if c.id == "phone").pseudo == "Kriss F4ABC"
    text = "\n".join(out)
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
    con, fake, out = make(tmp_path, answers=["6", "1", "o", ""])
    con.visitors()
    assert any("Radio-club (club1, b, 2 min)" in line for line in out)
    request = json.loads((state / KICK_REQUEST).read_text(encoding="utf-8"))
    assert request["id"] == "club1" and abs(request["at"] - time.time()) < 5
