# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Mémoires de fréquence et de mode : stockage partagé, ordre d'affichage, validation, robustesse du fichier."""
import json

import pytest

from trxstation.gateway.memories import MAX_ITEMS, MemoryStore, MemoryStoreError


def make(store, **kw):
    kw.setdefault("name", "Test")
    kw.setdefault("hz", 14_200_000)
    kw.setdefault("mode", "USB")
    return store.save(**kw)


def test_favorites_first_then_by_frequency_with_the_mode_kept():
    store = MemoryStore()
    make(store, name="Quarante", hz=7_100_000, mode="LSB")
    make(store, name="Vingt", hz=14_200_000, mode="PKTUSB")
    make(store, name="Dix", hz=28_400_000, mode="USB", favorite=True)
    make(store, name="Quatre-vingts", hz=3_650_000, mode="LSB", favorite=True)
    items = store.list()
    assert [m["name"] for m in items] == ["Quatre-vingts", "Dix", "Quarante", "Vingt"]
    assert [m["favorite"] for m in items] == [True, True, False, False]
    assert [m["mode"] for m in items] == ["LSB", "USB", "LSB", "PKTUSB"]


def test_updating_and_deleting():
    store = MemoryStore()
    first = make(store, name="Ancien")
    updated = store.save(memory_id=first.id, name="Nouveau", hz=7_074_000, mode="PKTUSB", favorite=True)
    assert updated.id == first.id and len(store.list()) == 1 and store.get(first.id).name == "Nouveau"
    assert store.delete(first.id) is True and store.delete(first.id) is False and store.list() == []
    with pytest.raises(ValueError):
        store.save(memory_id="inconnu", name="x", hz=1, mode="USB")


@pytest.mark.parametrize("fields", [
    dict(name="", hz=14_200_000, mode="USB"), dict(name="   ", hz=14_200_000, mode="USB"),
    dict(name="x" * 41, hz=14_200_000, mode="USB"), dict(name="a\nb", hz=14_200_000, mode="USB"),
    dict(name="ok", hz=0, mode="USB"), dict(name="ok", hz=14.2e6, mode="USB"), dict(name="ok", hz=True, mode="USB"),
    dict(name="ok", hz=10**11, mode="USB"), dict(name="ok", hz=14_200_000, mode="USB\nT 1"),
    dict(name="ok", hz=14_200_000, mode=""), dict(name="ok", hz=14_200_000, mode="USB", favorite="oui"),
    dict(name=None, hz=14_200_000, mode="USB"),
])
def test_invalid_memories_are_refused(fields):
    store = MemoryStore()
    with pytest.raises(ValueError):
        store.save(**fields)
    assert store.list() == []


def test_name_is_trimmed_and_the_limit_is_enforced():
    store = MemoryStore()
    assert make(store, name="  Réseau 40 m  ").name == "Réseau 40 m"
    for i in range(MAX_ITEMS - 1):
        make(store, name=f"m{i}", hz=1000 + i)
    with pytest.raises(ValueError):
        make(store, name="de trop")


def test_persistence_across_restarts_and_atomic_file(tmp_path):
    path = tmp_path / "state" / "memories.json"
    store = MemoryStore(path)
    kept = make(store, name="Mémoire é à ü", hz=7_074_000, mode="PKTUSB", favorite=True)
    make(store, name="Autre", hz=3_700_000, mode="LSB")
    again = MemoryStore(path)
    assert again.list() == store.list() and again.get(kept.id).favorite is True
    assert [p.name for p in path.parent.iterdir()] == ["memories.json"]           # aucun fichier temporaire
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_corrupt_file_never_prevents_starting_and_is_kept_aside(tmp_path):
    path = tmp_path / "memories.json"
    path.write_text("{ceci n'est pas du json", encoding="utf-8")
    store = MemoryStore(path)
    assert store.list() == [] and (tmp_path / "memories.json.corrupt").exists()
    make(store, name="Reparti")
    assert len(MemoryStore(path).list()) == 1


def test_bad_entries_in_the_file_are_skipped_not_trusted(tmp_path):
    path = tmp_path / "memories.json"
    good = {"id": "abc123", "name": "Bonne", "hz": 14_200_000, "mode": "USB", "favorite": False}
    evil = {"id": "../../x", "name": "Mauvaise", "hz": 14_200_000, "mode": "USB"}
    path.write_text(json.dumps({"version": 1, "items": [good, evil]}), encoding="utf-8")
    store = MemoryStore(path)
    assert [m["name"] for m in store.list()] == ["Bonne"]
    store2 = MemoryStore(tmp_path / "other.json")
    (tmp_path / "other.json").write_text(json.dumps({"version": 1, "items": [{"id": "ab", "name": "x", "hz": 0, "mode": "USB"}]}))
    assert MemoryStore(tmp_path / "other.json").list() == [] and store2.list() == []


def test_listeners_are_notified_with_the_sorted_list_and_can_be_removed():
    store = MemoryStore()
    seen = []
    store.add_listener(seen.append)
    first = make(store, name="A", hz=2000)
    make(store, name="B", hz=1000, favorite=True)
    assert [m["name"] for m in seen[-1]] == ["B", "A"] and len(seen) == 2
    store.remove_listener(seen.append)
    store.delete(first.id)
    assert len(seen) == 2
    store.add_listener(lambda items: 1 / 0)                                          # un écouteur défaillant ne bloque rien
    make(store, name="C")


def test_failed_write_leaves_the_list_unchanged_and_announces_nothing(tmp_path):
    blocker = tmp_path / "pas_un_dossier"
    blocker.write_text("fichier")
    store = MemoryStore(blocker / "memories.json")
    seen = []
    store.add_listener(seen.append)
    with pytest.raises(MemoryStoreError):
        make(store, name="Perdue")
    assert store.list() == [] and seen == []
