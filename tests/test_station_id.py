# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Identifiant unique de la station (GUID) : UUID 4 créé une fois, jamais écrasé, lisible par TRX Console."""
import os
import uuid

import pytest

from trxstation.station_id import ensure_station_id, id_path, read_station_id


def test_created_once_and_kept(tmp_path):
    assert read_station_id(tmp_path) is None
    first = ensure_station_id(tmp_path)
    assert uuid.UUID(first).version == 4
    assert ensure_station_id(tmp_path) == first == read_station_id(tmp_path)
    if os.name != "nt":
        assert id_path(tmp_path).stat().st_mode & 0o777 == 0o644
    assert [p.name for p in tmp_path.iterdir()] == ["station-id"]       # pas de fichier temporaire oublié


def test_two_stations_get_different_ids(tmp_path):
    assert ensure_station_id(tmp_path / "a") != ensure_station_id(tmp_path / "b")


def test_invalid_file_is_never_overwritten(tmp_path):
    id_path(tmp_path).write_text("pas un identifiant\n")
    assert read_station_id(tmp_path) is None
    with pytest.raises(OSError):
        ensure_station_id(tmp_path)
    assert id_path(tmp_path).read_text() == "pas un identifiant\n"
    id_path(tmp_path).write_text(str(uuid.uuid1()) + "\n")           # UUID 1 : refusé (horloge + adresse MAC)
    assert read_station_id(tmp_path) is None
