# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Validation du catalogue d'erreurs (trxstation/errors/catalog.yaml) et du registre des préfixes.

Codes uniques et bien formés, dans la bonne plage, champs obligatoires, traduction anglaise
complète, mêmes variables {…} en français et en anglais (cahier du monitoring, § 7).
"""
from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML absent (extra « dev ») : catalogue non vérifié")

ERRORS_DIR = Path(__file__).resolve().parents[1] / "trxstation" / "errors"
MODULES = ERRORS_DIR / "modules.yaml"

GRAVITES = {"info", "avertissement", "erreur", "critique"}
REQUIRED = ("gravite", "titre", "message", "causes", "preconisation", "action_auto",
            "ntfy_defaut", "priorite_ntfy", "depuis_version", "en")
REQUIRED_EN = ("titre", "message", "causes", "preconisation")
CODE_RE = re.compile(r"^(?P<prefix>[A-Z]{3})-(?P<num>\d{4})$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ACTION_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Plages du cahier (§ 7) : premier chiffre du code -> domaine. 0 n'est pas attribué au cœur.
PLAGES_ORT = set("123456789")
# Entrées imposées par le cahier : liaison avec les modules extérieurs.
CODES_CDC_6500 = {f"ORT-{n}" for n in range(6501, 6509)}


class _UniqueKeyLoader(yaml.SafeLoader):
    """Chargeur qui refuse une clé répétée (PyYAML garderait la dernière sans rien dire)."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(None, None, f"clé répétée : {key}", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_UniqueKeyLoader)


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.fixture(scope="module")
def registry() -> dict:
    data = _load(MODULES)
    assert isinstance(data, dict) and isinstance(data.get("prefixes"), dict)
    return data["prefixes"]


@pytest.fixture(scope="module")
def catalogs(registry: dict) -> dict[str, dict]:
    """Catalogue du cœur (ORT) et catalogues des modules livrés dans ce dossier (AND…), par préfixe."""
    out = {}
    for prefix, entry in registry.items():
        name = entry.get("catalogue")
        if name and (ERRORS_DIR / name).is_file():
            data = _load(ERRORS_DIR / name)
            assert isinstance(data, dict) and data, f"{name} vide ou mal formé"
            out[prefix] = data
    assert "ORT" in out and out["ORT"] is not None
    return out


@pytest.fixture(scope="module")
def catalog(catalogs: dict) -> dict:
    """Tous les codes, tous préfixes confondus (codes uniques entre catalogues : préfixes différents)."""
    merged: dict = {}
    for data in catalogs.values():
        assert not set(merged) & set(data)
        merged.update(data)
    return merged


def test_codes_are_unique_well_formed_and_in_a_known_range(catalogs: dict) -> None:
    # L'unicité est garantie par le chargeur (clé répétée = erreur) ; reste la forme, le préfixe et la plage.
    for prefix, data in catalogs.items():
        for code in data:
            m = CODE_RE.match(str(code))
            assert m, f"{code} : format attendu {prefix}-NNNN"
            assert m["prefix"] == prefix, f"{code} : le catalogue {prefix} ne contient que des codes {prefix}"
            if prefix == "ORT":
                assert m["num"][0] in PLAGES_ORT, f"{code} : hors des plages 1000-9999"


def test_deprecated_entries_say_what_replaces_them(catalog: dict) -> None:
    for code, entry in catalog.items():
        if entry.get("deprecated"):
            assert isinstance(entry.get("remplace_par"), str) and entry["remplace_par"].strip(),                 f"{code} : abandonné sans `remplace_par`"


def test_every_entry_has_the_required_fields(catalog: dict) -> None:
    for code, entry in catalog.items():
        missing = [f for f in REQUIRED if f not in entry]
        assert not missing, f"{code} : champs manquants {missing}"
        assert entry["gravite"] in GRAVITES, f"{code} : gravité {entry['gravite']!r}"
        for f in ("titre", "message", "preconisation"):
            assert isinstance(entry[f], str) and entry[f].strip(), f"{code} : {f} vide"
        assert isinstance(entry["causes"], list) and entry["causes"], f"{code} : causes vides"
        assert all(isinstance(c, str) and c.strip() for c in entry["causes"]), f"{code} : cause vide"
        assert isinstance(entry["action_auto"], str) and ACTION_RE.match(entry["action_auto"]), \
            f"{code} : action_auto {entry['action_auto']!r}"
        assert isinstance(entry["ntfy_defaut"], bool), f"{code} : ntfy_defaut doit être true/false"
        prio = entry["priorite_ntfy"]
        assert isinstance(prio, int) and not isinstance(prio, bool) and 1 <= prio <= 5, \
            f"{code} : priorite_ntfy {prio!r} (1 à 5)"
        assert isinstance(entry["depuis_version"], str) and VERSION_RE.match(entry["depuis_version"]), \
            f"{code} : depuis_version {entry['depuis_version']!r} (X.Y.Z entre guillemets)"
        if "deprecated" in entry:
            assert isinstance(entry["deprecated"], bool), f"{code} : deprecated doit être true/false"


def test_every_entry_has_a_complete_english_translation(catalog: dict) -> None:
    for code, entry in catalog.items():
        en = entry["en"]
        assert isinstance(en, dict), f"{code} : bloc en absent"
        for f in REQUIRED_EN:
            assert f in en, f"{code} : en.{f} manquant"
        for f in ("titre", "message", "preconisation"):
            assert isinstance(en[f], str) and en[f].strip(), f"{code} : en.{f} vide"
        assert isinstance(en["causes"], list) and len(en["causes"]) == len(entry["causes"]), \
            f"{code} : en.causes doit traduire chacune des {len(entry['causes'])} causes"
        assert all(isinstance(c, str) and c.strip() for c in en["causes"]), f"{code} : en.causes vide"


def test_message_variables_are_the_same_in_both_languages(catalog: dict) -> None:
    for code, entry in catalog.items():
        fr, en = _fields(entry["message"]), _fields(entry["en"]["message"])
        assert fr == en, f"{code} : variables {sorted(fr)} (fr) != {sorted(en)} (en)"
        for name in fr:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{code} : variable {{{name}}} mal nommée"


def test_external_module_link_codes_of_the_specification_are_present(catalog: dict) -> None:
    missing = sorted(CODES_CDC_6500 - set(catalog))
    assert not missing, f"codes de liaison avec les modules extérieurs absents : {missing}"


def test_module_registry(registry: dict) -> None:
    assert {"ORT", "BZA", "FDV", "AND"} <= set(registry)
    assert registry["ORT"]["catalogue"] == "catalog.yaml"
    for prefix, entry in registry.items():
        assert re.fullmatch(r"[A-Z]{3}", prefix), f"préfixe {prefix!r} : 3 lettres majuscules"
        for f in ("nom", "role", "interaction", "contact", "version_min", "catalogue", "en"):
            assert f in entry, f"{prefix} : champ {f} manquant"
        assert VERSION_RE.match(str(entry["version_min"])), f"{prefix} : version_min"
        assert entry["en"].get("nom") and entry["en"].get("role"), f"{prefix} : traduction anglaise"
