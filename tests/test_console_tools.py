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
            Path(cmd[-1]).write_bytes(Path(cmd[-2]).read_bytes())
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
    con, fake, out = make(tmp_path, answers=["1", "oui"])                    # « oui » en minuscules : refusé
    con.install_zip()
    assert fake.calls == [] and any("NON signé" in line or "PAS SIGNÉ" in line for line in out)
    con, fake, out = make(tmp_path, answers=["1", "OUI", "0.38"])            # mauvaise version tapée
    con.install_zip()
    assert fake.calls == []
    con, fake, out = make(tmp_path, answers=["1", "OUI", "0.38.0"])
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
