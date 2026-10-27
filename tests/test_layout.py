# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mises en page (designer, étape 19) : format, validation, sécurité, thèmes, cascade, stockage, protocole."""
import asyncio
import copy
import json
from pathlib import Path

import pytest

from trxstation.gateway.api.protocol import MAX_LAYOUT_MESSAGE_BYTES, MAX_MESSAGE_BYTES, ProtocolError, parse_command
from trxstation.gateway.api.session import ControlSession
from trxstation.gateway.cat import Capabilities
from trxstation.layout import (DEVICES, GRID_COLUMNS, WIDGETS, LayoutInvalid, LayoutStorageError, LayoutStore,
                               factory_profile, select_variant, validate_profile)
from trxstation.layout.catalog import LOCKED, MAX_PROFILE_BYTES
from trxstation.layout.theme import PRESETS, check_colors, contrast

CAPS = Capabilities(functions=("NR", "NB", "AIP", "COMP", "TUNER"),
                    levels=("SQL", "PREAMP", "AGC", "RFPOWER", "RFPOWER_METER", "SWR", "ALC"), complete=True)


def phone(profile):
    return profile["variants"]["phone"]["portrait"]["widgets"]


def find(widgets, wid):
    for w in widgets:
        if w["id"] == wid:
            return w
        for section in w.get("sections", []):
            found = find(section["widgets"], wid)
            if found:
                return found
        for group in w.get("groups", []):
            for layer in group:
                found = find(layer["widgets"], wid)
                if found:
                    return found
    return None


def errors_of(profile, caps=None):
    return validate_profile(profile, caps).errors


def minimal(device="phone", orientation="portrait"):
    """Le plus petit écran valide : les quatre widgets de sécurité."""
    widgets = [{"id": "ptt", "type": "ptt", "x": 0, "y": 0, "w": 2, "h": 2},
               {"id": "tx", "type": "tx_indicator", "x": 2, "y": 0, "w": 1, "h": 1},
               {"id": "link", "type": "link_status", "x": 3, "y": 0, "w": 1, "h": 1},
               {"id": "armed", "type": "tx_armed", "x": 2, "y": 1, "w": 2, "h": 1}]
    return {"format": 1, "name": "Essai", "variants": {device: {orientation: {"widgets": widgets}}}}


# --------------------------------------------------------------------------- profil d'usine et catalogue

def test_factory_profile_is_valid_and_warns_only_about_functions_the_rig_lacks():
    assert validate_profile(factory_profile()).to_dict() == {"ok": True, "errors": [], "warnings": []}
    assert validate_profile(factory_profile(), CAPS).warnings == []
    poor = Capabilities(functions=("NR",), levels=("SQL",), complete=True)
    report = validate_profile(factory_profile(), poor)
    assert report.ok and any("« NB »" in w and "masqué" in w for w in report.warnings)       # accepté, widget masqué
    copy_ = factory_profile()
    phone(copy_).clear()
    assert phone(factory_profile())                                                       # chaque appel donne une copie neuve


def test_catalog_is_coherent():
    for name, spec in WIDGETS.items():
        assert spec.appearances and spec.bind in ("func", "level", "none"), name
        assert 1 <= spec.min_size[0] <= GRID_COLUMNS["phone"] and spec.min_size[1] >= 1, name
    assert set(LOCKED) == {"ptt", "tx_indicator", "link_status", "tx_armed"}
    assert WIDGETS["ptt"].appearances == ("toggle",)                                       # PTT en toggle, jamais en maintien


def test_minimal_profile_is_valid_on_every_device():
    for device in DEVICES:
        assert validate_profile(minimal(device)).ok, device


# --------------------------------------------------------------------------- règles de sécurité (§5)

@pytest.mark.parametrize("kind", ["ptt", "tx_indicator", "link_status", "tx_armed"])
def test_every_safety_widget_is_mandatory_in_each_screen(kind):
    profile = minimal()
    phone(profile)[:] = [w for w in phone(profile) if w["type"] != kind]
    assert any(f"« {kind} » est obligatoire" in e for e in errors_of(profile))


def test_safety_widgets_cannot_be_hidden_shrunk_doubled_or_put_in_a_container():
    profile = minimal()
    phone(profile)[0]["hidden"] = True
    assert any("ne peut pas être masqué" in e for e in errors_of(profile))
    profile = minimal()
    phone(profile)[0].update(w=1, h=1)
    assert any("trop petit" in e for e in errors_of(profile))
    profile = minimal()
    phone(profile)[0]["appearance"] = "hold"                                             # maintien appuyé : interdit
    assert any("apparence" in e for e in errors_of(profile))
    profile = minimal()
    phone(profile).append({"id": "ptt2", "type": "ptt", "x": 0, "y": 2, "w": 2, "h": 2})
    assert any("un seul bouton PTT" in e for e in errors_of(profile))
    profile = minimal()
    ptt = phone(profile).pop(0)
    phone(profile).append({"id": "zone", "type": "layers", "x": 0, "y": 2, "w": 4, "h": 2,
                           "groups": [[{"widgets": [dict(ptt, x=0, y=0)]}]]})
    errs = errors_of(profile)
    assert any("jamais dans un accordéon ni une zone à calques" in e for e in errs)
    assert any("« ptt » est obligatoire" in e for e in errs)                              # et il manque au premier niveau


def test_each_orientation_and_variant_is_checked_separately():
    profile = minimal()
    profile["variants"]["phone"]["landscape"] = {"widgets": [{"id": "freq", "type": "frequency", "x": 0, "y": 0, "w": 4, "h": 1}]}
    errs = errors_of(profile)
    assert errs and all("smartphone/landscape" in e for e in errs)


# --------------------------------------------------------------------------- géométrie et widgets

def test_geometry_errors():
    for change, expected in (({"x": 3, "w": 2}, "dépasse"), ({"x": -1}, "position ou taille"),
                             ({"w": 1.5}, "position ou taille"), ({"y": True}, "position ou taille")):
        profile = minimal()
        phone(profile)[0].update(change)
        assert any(expected in e for e in errors_of(profile)), change
    profile = minimal()
    phone(profile).append({"id": "freq", "type": "frequency", "x": 1, "y": 1, "w": 2, "h": 1})
    assert any("chevauche" in e for e in errors_of(profile))
    phone(profile)[-1]["hidden"] = True                                                    # masqué : n'occupe pas de place
    assert validate_profile(profile).ok


def test_widget_field_errors():
    cases = [({"type": "rocket"}, "type de widget inconnu"), ({"id": "Bad Id"}, "identifiant invalide"),
             ({"bind": "NR"}, "ne se lie à aucune fonction"), ({"target": "sub"}, "n'a pas de cible"),
             ({"color": "red"}, "champ(s) inconnu(s)"), ({"label": ""}, "« label »"),
             ({"options": {"script": {"a": 1}}}, "options")]
    for change, expected in cases:
        profile = minimal()
        phone(profile)[1].update(change)
        assert any(expected in e for e in errors_of(profile)), change


def test_bindings_targets_and_appearances():
    profile = minimal()
    widgets = phone(profile)
    widgets.append({"id": "nr", "type": "switch", "x": 0, "y": 2, "w": 1, "h": 1})
    assert any("doit nommer une fonction" in e for e in errors_of(profile))
    widgets[-1].update(bind="nr")
    assert any("doit nommer une fonction" in e for e in errors_of(profile))
    widgets[-1].update(bind="NR", target="sub", appearance="toggle")                      # récepteur Sub, apparence interrupteur
    assert validate_profile(profile).ok
    widgets[-1]["target"] = "rx3"
    assert any("cible invalide" in e for e in errors_of(profile))
    widgets[-1]["target"] = "main"
    widgets.append({"id": "sql", "type": "slider", "x": 1, "y": 2, "w": 1, "h": 1, "bind": "SQL", "appearance": "knob"})
    assert validate_profile(profile).ok                                                    # slider devenu potentiomètre
    widgets[-1]["appearance"] = "needle"
    assert any("apparence « needle » impossible" in e for e in errors_of(profile))


def test_same_widget_keeps_its_binding_in_every_variant():
    profile = minimal()
    profile["variants"]["tablet"] = copy.deepcopy(profile["variants"]["phone"])
    for device in ("phone", "tablet"):
        profile["variants"][device]["portrait"]["widgets"].append(
            {"id": "nr", "type": "switch", "x": 0, "y": 2, "w": 1, "h": 1, "bind": "NR"})
    assert validate_profile(profile).ok
    profile["variants"]["tablet"]["portrait"]["widgets"][-1]["bind"] = "NB"
    assert any("même identifiant" in e for e in errors_of(profile))


def test_containers():
    profile = minimal()
    widgets = phone(profile)
    widgets.append({"id": "more", "type": "accordion", "x": 0, "y": 2, "w": 4, "h": 1, "sections": [
        {"title": "Mémoires", "open": True, "widgets": [{"id": "mem", "type": "memories", "x": 0, "y": 0, "w": 4, "h": 2}]}]})
    assert validate_profile(profile).ok
    widgets[-1]["sections"][0]["widgets"][0]["w"] = 5                                     # la grille interne = largeur du conteneur
    assert any("dépasse" in e or "position ou taille" in e for e in errors_of(profile))
    widgets[-1]["sections"][0]["widgets"][0] = {"id": "inner", "type": "accordion", "x": 0, "y": 0, "w": 4, "h": 1,
                                                "sections": [{"title": "x", "widgets": []}]}
    assert any("ne peut pas contenir un autre conteneur" in e for e in errors_of(profile))
    widgets[-1] = {"id": "zone", "type": "layers", "x": 0, "y": 2, "w": 4, "h": 2,
                   "gestures": {"next_layer": "tap", "next_group": "tap"},
                   "groups": [[{"widgets": []}], [{"title": "Mémoires", "widgets": []}]]}
    assert any("doivent être différents" in e for e in errors_of(profile))
    widgets[-1]["gestures"] = {"next_layer": "tap", "next_group": "long_press"}
    assert validate_profile(profile).ok
    widgets[-1]["groups"] = []
    assert any("de 1 à 8 groupes" in e for e in errors_of(profile))


# --------------------------------------------------------------------------- thèmes et polices (§9)

def test_every_preset_is_readable_and_keeps_the_emission_colour_distinct():
    for name, variants in PRESETS.items():
        for kind, colors in variants.items():
            assert check_colors(colors) == [], (name, kind)
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0


def test_theme_and_font_rules():
    for theme, expected in (({"preset": "disco"}, "charte inconnue"),
                            ({"colors": {"text": "#05080d"}}, "contraste insuffisant"),
                            ({"colors": {"accent": "#ff3b30"}}, "ressemble trop à la couleur d'émission"),
                            ({"colors": {"text": "white"}}, "#rrggbb"), ({"dark": "oui"}, "dark")):
        profile = minimal()
        profile["theme"] = theme
        assert any(expected in e for e in errors_of(profile)), theme
    profile = minimal()
    profile["theme"] = {"preset": "nuit", "dark": True}
    assert validate_profile(profile).ok
    profile["fonts"] = {"ui": "Comic Sans"}
    assert any("non autorisée" in e for e in errors_of(profile))
    profile["fonts"] = {"display": "DSEG7 Classic", "base_size": 12}
    assert any("sur smartphone" in e for e in errors_of(profile))
    profile = minimal("desktop")
    profile["fonts"] = {"base_size": 12}
    assert validate_profile(profile).ok


# --------------------------------------------------------------------------- en-tête du profil

def test_profile_level_errors():
    assert validate_profile([]).errors == ["le profil doit être un objet JSON"]
    for change, expected in (({"format": 2}, "trop récent"), ({"format": "1"}, "format"), ({"name": ""}, "name"),
                             ({"script": "x"}, "champ(s) inconnu(s)"), ({"variants": {}}, "variants"),
                             ({"variants": {"watch": {}}}, "variants"), ({"rig_model": "IC-7300"}, "rig_model")):
        profile = minimal()
        profile.update(change)
        assert any(expected in e for e in errors_of(profile)), change
    profile = minimal()
    phone(profile)[1]["label"] = "x" * 40
    profile["name"] = "y" * 60
    big = [dict(phone(profile)[1], id=f"t{i}", y=10 + i) for i in range(MAX_PROFILE_BYTES // 60)]
    phone(profile).extend(big)
    assert any("trop volumineux" in e for e in errors_of(profile))


# --------------------------------------------------------------------------- cascade (§3)

def test_cascade_goes_up_never_down():
    only_phone = {"phone": {"portrait": {}}}
    only_phone["phone"]["portrait"] = {"widgets": []}
    assert select_variant(only_phone, "phone", "portrait").to_dict() == {"device": "phone", "orientation": "portrait", "display": "native"}
    assert select_variant(only_phone, "tablet", "portrait").to_dict() == {"device": "phone", "orientation": "portrait", "display": "centered"}
    assert select_variant(only_phone, "desktop", "landscape").device == "phone"
    both = {"phone": {"portrait": {"widgets": []}}, "tablet": {"landscape": {"widgets": []}}}
    assert select_variant(both, "desktop", "landscape").to_dict() == {"device": "tablet", "orientation": "landscape", "display": "centered"}
    no_phone = {"tablet": {"portrait": {"widgets": []}}, "desktop": {"landscape": {"widgets": []}}}
    assert select_variant(no_phone, "phone", "portrait") is None                          # => écran de sécurité
    assert select_variant({"desktop": {"landscape": {"widgets": []}}}, "tablet", "landscape") is None


def test_cascade_orientation_and_forced_category():
    profile = {"phone": {"portrait": {"widgets": []}}, "tablet": {"landscape": {"widgets": []}}}
    assert select_variant(profile, "phone", "landscape").to_dict() == {"device": "phone", "orientation": "portrait", "display": "centered"}
    assert select_variant(profile, "tablet", "portrait").to_dict() == {"device": "tablet", "orientation": "landscape", "display": "rotate"}
    assert select_variant(profile, "tablet", "landscape", forced="phone").device == "phone"   # catégorie inférieure : permis
    assert select_variant(profile, "phone", "portrait", forced="tablet").device == "phone"    # supérieure : ignorée
    with pytest.raises(ValueError):
        select_variant(profile, "watch", "portrait")


# --------------------------------------------------------------------------- stockage

def test_store_serves_factory_then_saves_validates_and_keeps_the_previous_version(tmp_path):
    store = LayoutStore(tmp_path / "layouts")
    profile, source = store.get("phone")
    assert source == "factory" and profile == factory_profile()
    mine = minimal()
    store.save("phone", mine)
    assert store.get("phone") == (mine, "user") and store.get("car")[1] == "factory"      # un profil par compte
    second = copy.deepcopy(mine)
    second["name"] = "Deuxième"
    store.save("phone", second)
    assert store.get("phone")[0]["name"] == "Deuxième"
    assert json.loads((tmp_path / "layouts" / "phone.prev.json").read_text(encoding="utf-8"))["name"] == "Essai"
    assert store.restore_previous("phone") and store.get("phone")[0]["name"] == "Essai"
    bad = minimal()
    phone(bad).pop(0)
    with pytest.raises(LayoutInvalid) as exc:
        store.save("phone", bad)
    assert any("ptt" in e for e in exc.value.report.errors) and store.get("phone")[0]["name"] == "Essai"
    store.reset("phone")
    assert store.get("phone")[1] == "factory"
    with pytest.raises(ValueError):
        store.get("../etc/passwd")


def test_store_never_blocks_on_a_corrupt_or_obsolete_file(tmp_path):
    store = LayoutStore(tmp_path)
    (tmp_path / "phone.json").write_text("{pas du json", encoding="utf-8")
    assert store.get("phone")[1] == "factory" and (tmp_path / "phone.corrupt").exists()
    invalid = minimal()
    phone(invalid).pop(0)
    (tmp_path / "car.json").write_text(json.dumps(invalid), encoding="utf-8")
    assert store.get("car")[1] == "factory"


def test_store_reports_disk_errors(tmp_path):
    blocker = tmp_path / "layouts"
    blocker.write_text("un fichier à la place du dossier", encoding="utf-8")
    with pytest.raises(LayoutStorageError):
        LayoutStore(blocker).save("phone", minimal())


# --------------------------------------------------------------------------- protocole et session

def test_protocol_accepts_a_large_layout_save_only():
    profile = factory_profile()
    raw = json.dumps({"cmd": "layout_save", "id": 3, "profile": profile}, separators=(",", ":"))
    assert len(raw) > MAX_MESSAGE_BYTES
    command = parse_command(raw)
    assert command.name == "layout_save" and command.params["profile"] == profile
    assert parse_command(raw.encode("utf-8")).name == "layout_save"
    with pytest.raises(ProtocolError) as exc:                                            # autre commande trop grosse : refusée sans analyse
        parse_command(json.dumps({"cmd": "set_frequency", "hz": 7_000_000, "pad": "x" * MAX_MESSAGE_BYTES}))
    assert exc.value.code == "too_large"
    with pytest.raises(ProtocolError) as exc:
        parse_command('{"cmd":"layout_save","profile":"' + "x" * MAX_LAYOUT_MESSAGE_BYTES + '"}')
    assert exc.value.code == "too_large"
    with pytest.raises(ProtocolError) as exc:
        parse_command(json.dumps({"cmd": "layout_save", "profile": [1, 2]}))
    assert exc.value.code == "invalid_params"
    assert parse_command('{"cmd":"layout_get","id":1}').name == "layout_get"


def session_with(store, client_id="phone", caps=CAPS):
    messages = []
    session = ControlSession(client_id, None, None, None, caps, messages.append, layouts=store)

    def say(**fields):
        asyncio.run(session.on_message(json.dumps(fields, separators=(",", ":"))))
        return next(m for m in reversed(messages) if m.get("id") == fields.get("id"))
    return say


def test_session_layout_commands(tmp_path):
    say = session_with(LayoutStore(tmp_path))
    got = say(cmd="layout_get", id=1)
    assert got["ok"] and got["source"] == "factory" and got["profile"] == factory_profile() and got["warnings"] == []
    mine = minimal()
    mine["variants"]["phone"]["portrait"]["widgets"].append(
        {"id": "dw", "type": "switch", "x": 0, "y": 2, "w": 1, "h": 1, "bind": "DUAL_WATCH"})
    saved = say(cmd="layout_save", id=2, profile=mine)
    assert saved["ok"] and "DUAL_WATCH" in saved["warnings"][0]                       # fonction absente : acceptée, masquée
    assert say(cmd="layout_get", id=3)["source"] == "user"
    bad = minimal()
    phone(bad).pop(0)
    refused = say(cmd="layout_save", id=4, profile=bad)
    assert not refused["ok"] and refused["reason"] == "layout_invalid" and refused["errors"]
    reset = say(cmd="layout_reset", id=5)
    assert reset["ok"] and reset["source"] == "factory"
    assert session_with(None)(cmd="layout_get", id=6)["reason"] == "layouts_unavailable"


# --------------------------------------------------------------------------- cohérence avec le navigateur (layout.js)

JS_DIR = Path(__file__).resolve().parent / "js"


def test_browser_copy_of_the_factory_profile_is_up_to_date():
    # tests/js/factory_profile.json est lu par les tests du navigateur : il doit rester identique au profil d'usine
    assert json.loads((JS_DIR / "factory_profile.json").read_text(encoding="utf-8")) == factory_profile()


def test_shared_cascade_cases_give_the_same_answer_as_the_browser():
    cases = json.loads((JS_DIR / "layout_cases.json").read_text(encoding="utf-8"))
    assert len(cases) >= 10
    for case in cases:
        variants = {}
        for item in case["variants"]:
            device, orientation = item.split("/")
            variants.setdefault(device, {})[orientation] = {"widgets": []}
        got = select_variant(variants, case["device"], case["orientation"], case["forced"])
        assert (got and [got.device, got.orientation, got.display]) == case["expect"], case

