# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profils de poste (TRX Console, menu 18) : seules les sections du poste changent, format versionné avec conversions,
profil trop ancien ou trop récent refusé avec la marche à suivre, jamais pendant une émission."""
from __future__ import annotations

import json
import time
import tomllib

import pytest

from trxstation import config as cfgmod
from trxstation import profiles as prof

from test_console_tools import make, write_config


def station_text(tmp_path, **rig):
    path = write_config(tmp_path)
    cfg = cfgmod.load(path)
    for key, value in rig.items():
        setattr(cfg.rig, key, value)
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    return path


def test_profile_format_matches_the_current_configuration_fields():
    """Garde-fou : changer une clé de [rig], [audio] ou [spectrum] oblige à monter PROFILE_FORMAT et à écrire la
    conversion des anciens profils (MIGRATIONS), ou à la déclarer impossible (None)."""
    assert prof.PROFILE_FIELDS[prof.PROFILE_FORMAT] == prof.current_fields(), (
        "Les champs du poste ont changé : monter profiles.PROFILE_FORMAT, ajouter PROFILE_FIELDS[nouveau] et "
        "MIGRATIONS[ancien] (ou None si la conversion est impossible)")
    assert set(prof.MIGRATIONS) <= set(range(1, prof.PROFILE_FORMAT))


def test_names_and_file_names():
    assert prof.file_name("IC-7300 maison") == "ic-7300-maison.toml"
    assert prof.file_name("Poste d'été ") == "poste-d-ete.toml"
    assert prof.valid_name("FT-991A portable") and prof.valid_name("Émetteur 2")
    for bad in ("", "a/b", "../x", " lead", "x" * 41, "a;b"):
        assert not prof.valid_name(bad), bad


def test_saved_profile_holds_only_the_rig_and_loads_back(tmp_path):
    path = station_text(tmp_path, max_power_w=100, tx_modes=["PKTUSB"])
    cfg = cfgmod.load(path)
    text = prof.render("IC-7300 maison", cfg, "0.50.0", "2026-10-28 10:00")
    data = tomllib.loads(text)
    assert set(data) == {"profil", "rig", "audio", "spectrum"}                       # ni comptes, ni réseau, ni bandes
    assert data["profil"] == {"nom": "IC-7300 maison", "format": prof.PROFILE_FORMAT, "version": "0.50.0",
                              "enregistre_le": "2026-10-28 10:00"}
    assert "password_hash" not in text and "[[clients]]" not in text
    file = tmp_path / "p.toml"
    file.write_text(text, encoding="utf-8")
    other = path.read_text(encoding="utf-8").replace("max_power_w = 100", "max_power_w = 10")
    new_cfg, new_text = prof.apply(other, prof.read(file))
    assert new_cfg.rig.max_power_w == 100 and new_cfg.rig.tx_modes == ["PKTUSB"]
    before = cfgmod.from_dict(tomllib.loads(other))
    assert (new_cfg.clients, new_cfg.network, new_cfg.bands, new_cfg.safety, new_cfg.cluster) == \
           (before.clients, before.network, before.bands, before.safety, before.cluster)  # la station ne bouge pas
    assert prof.same_rig(new_cfg, prof.read(file)) and not prof.same_rig(before, prof.read(file))


def write_profile(tmp_path, body, fmt=1, version="0.50.0"):
    file = tmp_path / "old.toml"
    file.write_text(f'[profil]\nnom = "Ancien"\nformat = {fmt}\nversion = "{version}"\n\n{body}', encoding="utf-8")
    return prof.read(file)


def test_missing_keys_take_their_defaults_and_bad_values_are_refused(tmp_path):
    station = station_text(tmp_path).read_text(encoding="utf-8")
    cfg, _ = prof.apply(station, write_profile(tmp_path, "[rig]\nmodel = 1\n"))        # [audio] et [spectrum] absents
    assert cfg.audio == cfgmod.Audio() and cfg.spectrum == cfgmod.Spectrum()
    with pytest.raises(prof.ProfileError, match="refais la configuration"):
        prof.apply(station, write_profile(tmp_path, '[rig]\nmodel = 1\nptt_type = "VOX"\n'))      # valeur invalide
    with pytest.raises(prof.ProfileError, match="clé inconnue"):
        prof.apply(station, write_profile(tmp_path, '[rig]\nmodel = 1\nancienne_cle = 3\n'))      # clé disparue
    with pytest.raises(prof.ProfileError, match="hors du poste"):
        prof.apply(station, write_profile(tmp_path, '[rig]\nmodel = 1\n[network]\ngateway_port = 1\n'))


def test_format_conversions(tmp_path, monkeypatch):
    station = station_text(tmp_path).read_text(encoding="utf-8")
    with pytest.raises(prof.ProfileError, match="plus récente"):
        prof.apply(station, write_profile(tmp_path, "[rig]\nmodel = 1\n", fmt=prof.PROFILE_FORMAT + 1, version="9.0.0"))
    # Format futur simulé : la version 2 renomme une clé ; la conversion 1 -> 2 la reprend.
    monkeypatch.setattr(prof, "PROFILE_FORMAT", 2)
    monkeypatch.setattr(prof, "MIGRATIONS", {1: lambda s: {**s, "rig": {("max_power_w" if k == "puissance" else k): v
                                                                          for k, v in s["rig"].items()}}})
    old = write_profile(tmp_path, "[rig]\nmodel = 1\npuissance = 50\n", fmt=1)
    cfg, _ = prof.apply(station, old)
    assert cfg.rig.max_power_w == 50
    monkeypatch.setattr(prof, "MIGRATIONS", {1: None})                                 # conversion déclarée impossible
    with pytest.raises(prof.ProfileError, match=r"trop ancien.*menu 2.*menu 18"):
        prof.apply(station, old)
    monkeypatch.setattr(prof, "MIGRATIONS", {})                                        # conversion oubliée : même refus
    with pytest.raises(prof.ProfileError, match="trop ancien"):
        prof.apply(station, old)


def test_damaged_or_foreign_files_are_reported(tmp_path):
    (tmp_path / "abime.toml").write_text("[[[", encoding="utf-8")
    (tmp_path / "autre.toml").write_text("[rig]\nmodel = 1\n", encoding="utf-8")
    for name, message in (("abime.toml", "abîmé"), ("autre.toml", "pas un profil")):
        with pytest.raises(prof.ProfileError, match=message):
            prof.read(tmp_path / name)


# ------------------------------------------------------------------ menu 18

def test_menu_saves_then_loads_another_rig(tmp_path):
    path = station_text(tmp_path, max_power_w=100)
    con, fake, out = make(tmp_path, answers=["1", "IC-7300 maison"])
    con.profiles()
    saved = path.parent / "profils" / "ic-7300-maison.toml"
    assert saved.is_file() and fake.admin_commands()[-1][:2] == ["install", "-D"]
    assert any("enregistré" in line for line in out)
    station_text(tmp_path, max_power_w=10)                                             # on passe à un autre poste
    con, fake, out = make(tmp_path, answers=["2", "1", "OUI"])
    con.profiles()
    assert any("<- poste en service" not in line and "IC-7300 maison" in line for line in out)
    assert cfgmod.load(path).rig.max_power_w == 100
    changes = next(line for line in out if line.startswith("Changements"))
    assert "+max_power_w = 100" in changes and "-max_power_w = 10" in changes
    con, fake, out = make(tmp_path, answers=["3", "1", "o"])                           # le profil marque le poste en service
    con.profiles()
    assert any("<- poste en service" in line for line in out) and not saved.exists()


def test_menu_refuses_to_load_during_a_transmission(tmp_path):
    path = station_text(tmp_path)
    con, fake, out = make(tmp_path, answers=["1", "Autre"])
    con.profiles()
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"ptt": {"state": "RX"}, "rig": {"ptt": True}}), encoding="utf-8")   # micro du poste
    cfg = cfgmod.load(path)
    cfg.supervisor.status_path = str(status)
    path.write_text(cfgmod.render_toml(cfg), encoding="utf-8")
    before = path.read_bytes()
    con, fake, out = make(tmp_path, answers=["2", "1"])
    con.profiles()
    assert "le poste émet" in out[-1] and path.read_bytes() == before
    status.write_text(json.dumps({"ptt": {"state": "TX"}, "rig": {"ptt": True}}), encoding="utf-8")
    con, fake, out = make(tmp_path, answers=["2", "1"])
    con.profiles()
    assert "le poste émet" in out[-1]
    old = time.time() - 60
    import os
    os.utime(status, (old, old))                                                       # passerelle arrêtée : permis
    assert con.transmitting() is False


def test_menu_reports_a_profile_from_a_newer_version(tmp_path):
    path = station_text(tmp_path)
    folder = path.parent / "profils"
    folder.mkdir()
    (folder / "futur.toml").write_text('[profil]\nnom = "Futur"\nformat = 99\nversion = "2.0.0"\n[rig]\nmodel = 1\n',
                                       encoding="utf-8")
    con, fake, out = make(tmp_path, answers=["2", "1"])
    con.profiles()
    assert any("version plus récente" in line for line in out) and "mets TRX distant à jour" in out[-1]
