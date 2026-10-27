# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Socle des modules : jetons, manifestes, clé des modules, registre, configuration."""
import os
from pathlib import Path

import pytest

from trxstation import config as cfgmod
from trxstation.migrate import import_config
from trxstation.modules.keys import (KEY_BYTES, key_path, load_or_create_key, module_secret,
                                     module_secrets, read_key)
from trxstation.modules.manifest import (ManifestError, api_compatible, discover, load_manifest,
                                         parse_manifest)
from trxstation.modules.registry import BUILTIN_DIR, selected_manifests
from trxstation.modules.tokens import TokenAuthority, TokenError


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def write_manifest(folder: Path, name: str, **module):
    folder.mkdir(parents=True, exist_ok=True)
    extra = "".join(f'{k} = "{v}"\n' for k, v in module.items())
    (folder / "manifest.toml").write_text(
        f'[module]\nname = "{name}"\nversion = "1.0"\napi = "1.0"\nentry = "a.b"\n{extra}',
        encoding="utf-8")


# ------------------------------------------------------------------ jetons de session

def test_jeton_valide():
    ta = TokenAuthority(ttl_s=60)
    claims = ta.verify(ta.issue("f4abc", sid="s1"))
    assert claims.user == "f4abc" and claims.sid == "s1"


def test_jeton_expire():
    clock = Clock()
    ta = TokenAuthority(ttl_s=60, clock=clock)
    tok = ta.issue("f4abc")
    clock.t += 61
    with pytest.raises(TokenError) as exc:
        ta.verify(tok)
    assert exc.value.code == "expired"


def test_jeton_revoque_a_la_deconnexion():
    ta = TokenAuthority()
    tok = ta.issue("f4abc", sid="s2")
    ta.revoke("s2")
    with pytest.raises(TokenError) as exc:
        ta.verify(tok)
    assert exc.value.code == "revoked"


def test_jeton_modifie_ou_dune_autre_station_refuse():
    ta = TokenAuthority()
    body, sig = ta.issue("f4abc").split(".")
    with pytest.raises(TokenError) as exc:
        ta.verify(body[:-2] + "AA." + sig)
    assert exc.value.code == "signature"
    with pytest.raises(TokenError):
        TokenAuthority().verify(ta.issue("f4abc"))


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c", None])
def test_jeton_mal_forme(bad):
    with pytest.raises(TokenError):
        TokenAuthority().verify(bad)


def test_revocations_purgees_apres_expiration():
    clock = Clock()
    ta = TokenAuthority(ttl_s=10, clock=clock)
    ta.revoke("vieux", exp=clock.t + 5)
    clock.t += 6
    ta.verify(ta.issue("f4abc"))
    assert "vieux" not in ta._revoked


# ------------------------------------------------------------------ manifestes

BASE = {"module": {"name": "video", "version": "1.2.0", "api": "1.0", "entry": "trx_video.main"}}


def with_(**sections):
    data = {k: dict(v) for k, v in BASE.items()}
    for key, value in sections.items():
        data.setdefault(key, {}).update(value)
    return data


def test_manifeste_minimal():
    m = parse_manifest(with_())
    assert m.name == "video" and m.start == "auto" and m.rights.commands == frozenset()
    assert m.resources.nice == 10


def test_manifeste_du_module_demo_fourni():
    m = load_manifest(BUILTIN_DIR / "demo" / "manifest.toml")
    assert m.name == "demo" and m.entry == "trxstation.modules.demo_module"
    assert "ptt" in m.rights.events and not m.rights.commands


@pytest.mark.parametrize("sections, mot", [
    ({"module": {"name": "Vidéo!"}}, "nom"),
    ({"module": {"version": "un"}}, "version"),
    ({"module": {"api": "1"}}, "API"),
    ({"module": {"entry": "rm -rf /"}}, "entrée"),
    ({"module": {"start": "toujours"}}, "démarrage"),
    ({"rights": {"events": ["inconnu"]}}, "événements"),
    ({"rights": {"commands": ["ptt"]}}, "commandes"),
    ({"resources": {"nice": -5}}, "nice"),
    ({"resources": {"memory_max_mb": 1}}, "memory"),
    ({"degradation": {"levels": [6]}}, "paliers"),
    ({"network": {"ports": [80]}}, "ports"),
])
def test_manifestes_refuses(sections, mot):
    with pytest.raises(ManifestError) as exc:
        parse_manifest(with_(**sections))
    assert mot in str(exc.value)


@pytest.mark.parametrize("req, prov, attendu", [
    ("1.0", "1.0", True), ("1.0", "1.3", True), ("1.4", "1.3", False),
    ("2.0", "1.9", False), ("x", "1.0", False),
])
def test_compatibilite_api(req, prov, attendu):
    assert api_compatible(req, prov) is attendu


def test_decouverte_tolere_un_manifeste_invalide(tmp_path):
    write_manifest(tmp_path / "bon", "bon")
    (tmp_path / "casse").mkdir()
    (tmp_path / "casse" / "manifest.toml").write_text("[module\n", encoding="utf-8")
    write_manifest(tmp_path / "double", "bon")
    found, errors = discover(tmp_path)
    assert [m.name for m in found] == ["bon"] and len(errors) == 2
    assert discover(tmp_path / "absent") == ([], [])


# ------------------------------------------------------------------ clé des modules

def test_cle_creee_une_fois_puis_relue(tmp_path):
    path = key_path(tmp_path / "etat")
    assert read_key(path) is None                   # le superviseur attend
    key = load_or_create_key(path)
    assert len(key) == KEY_BYTES and load_or_create_key(path) == key == read_key(path)
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600
    assert not list(path.parent.glob(".*.tmp"))


def test_cle_invalide_jamais_ecrasee(tmp_path):
    path = key_path(tmp_path)
    path.write_bytes(b"court")
    with pytest.raises(OSError):
        load_or_create_key(path)
    assert path.read_bytes() == b"court"


def test_secrets_derives_distincts_et_stables():
    key = bytes(range(32))
    s = module_secrets(key, ["demo", "video"])
    assert s["demo"] != s["video"] and s["demo"] == module_secret(key, "demo")
    assert module_secret(bytes(32), "demo") != s["demo"]


# ------------------------------------------------------------------ registre et configuration

def test_registre_ne_garde_que_les_modules_demandes(tmp_path):
    write_manifest(tmp_path / "builtin" / "demo", "demo")
    write_manifest(tmp_path / "builtin" / "endormi", "endormi", start="disabled")
    write_manifest(tmp_path / "extra" / "cluster", "cluster")
    write_manifest(tmp_path / "extra" / "demo2", "demo")          # ne remplace pas le module fourni
    mods = cfgmod.Modules(run=["cluster", "demo", "endormi", "absent"], extra_dir=str(tmp_path / "extra"))
    selected, problems = selected_manifests(mods, builtin_dir=tmp_path / "builtin")
    assert [m.name for m in selected] == ["cluster", "demo"]
    assert any("introuvable" in p for p in problems)
    assert any("désactivé" in p for p in problems)
    assert any("déjà ce nom" in p for p in problems)


def test_registre_vide_par_defaut():
    assert selected_manifests(cfgmod.Modules()) == ([], [])


def dummy_config(**modules):
    cfg = cfgmod.Config()
    cfg.rig.model = cfgmod.DUMMY_MODEL
    for k, v in modules.items():
        setattr(cfg.modules, k, v)
    return cfg


def test_section_modules_desactivee_par_defaut_et_relue():
    import tomllib
    cfg = dummy_config()
    assert not cfg.modules.enabled and cfgmod.validate(cfg) == []
    cfg.modules.run = ["demo"]
    again = cfgmod.from_dict(tomllib.loads(cfgmod.render_toml(cfg)))
    assert again.modules.run == ["demo"] and again.modules.enabled
    assert again.modules.bus_port == 47810 and again.modules.run_as == "trx"


def test_ancienne_configuration_sans_section_modules_reste_valide():
    data = {"rig": {"model": 1}}
    assert cfgmod.from_dict(data).modules.run == []


@pytest.mark.parametrize("modules, mot", [
    ({"run": ["Demo"]}, "nom de module"),
    ({"run": ["demo", "demo"]}, "deux fois"),
    ({"bus_port": 80}, "hors plage"),
    ({"bus_port": 8443}, "différer"),
    ({"run_as": "root"}, "jamais tourner en root"),
    ({"run_as": "Mauvais Nom"}, "nom de compte"),
])
def test_section_modules_validee(modules, mot):
    problems = cfgmod.validate(dummy_config(**modules))
    assert any(mot in p for p in problems), problems


def test_import_depuis_windows_oublie_le_dossier_de_modules():
    cfg = dummy_config(run=["demo"], extra_dir=r"C:\trx\modules")
    out, notes = import_config(cfg, desktop=False)
    assert out.modules.extra_dir == "" and out.modules.run == ["demo"]
    assert any("modules" in n for n in notes)


def test_pyproject_embarque_les_manifestes_des_modules():
    """Sans cette ligne, pip ne copie pas les manifestes sur la station : aucun module ne démarre.

    Le zip Debian copie tout le dossier, donc test_debian_package ne verrait pas l'oubli.
    """
    import tomllib
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    data = project["tool"]["setuptools"]["package-data"]
    assert "builtin/*/manifest.toml" in data.get("trxstation.modules", [])
    assert "trxstation.gateway.api" in data                        # les lignes des autres livraisons restent
    assert project["project"]["scripts"]["trx-qualif"] == "trxstation.qualif.main:main"
