# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Profils de poste : plusieurs TRX pilotés tour à tour par la même station (TRX Console, menu 18).

Un profil garde ce qui dépend DU POSTE : sections [rig] (modèle, port, PTT, modes d'émission, puissance), [audio]
(cartes son, gains) et [spectrum] (second port CI-V). Le reste de station.toml appartient à la station et n'est
jamais touché par un profil : comptes et mots de passe, réseau, bandes autorisées, sécurités, superviseur, cluster.

Fichiers : `<dossier de station.toml>/profils/<nom>.toml`, mêmes droits que station.toml (écrits par sudo).

ÉVOLUTION DU FORMAT. Chaque profil porte `[profil] format = N`. PROFILE_FIELDS[N] décrit les clés de ce format ; un
test vérifie que PROFILE_FIELDS[PROFILE_FORMAT] correspond EXACTEMENT aux champs actuels de Rig, Audio et Spectrum :
toute livraison qui ajoute, renomme ou retire une de ces clés doit monter PROFILE_FORMAT et écrire la conversion
MIGRATIONS[ancien] (profil du format N -> profil du format N+1), ou y mettre None si la conversion est impossible.
Au chargement : profil d'une version PLUS RÉCENTE = refusé ; conversion manquante ou impossible = refusé, avec le
conseil de refaire la configuration (assistant) puis d'enregistrer un nouveau profil ; profil converti = validé comme
station.toml (une clé manquante prend sa valeur par défaut, une valeur invalide est refusée), puis montré avant
d'être enregistré. Le fichier du profil n'est jamais réécrit au chargement : il suffit de le réenregistrer.
"""
from __future__ import annotations

import re
import tomllib
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path

from . import config as cfgmod

SECTIONS = ("rig", "audio", "spectrum")
PROFILE_FORMAT = 1
PROFILE_FIELDS: dict[int, dict[str, tuple[str, ...]]] = {
    1: {"rig": ("model", "port", "speed", "ptt_type", "ptt_port", "extra_conf", "tx_modes", "max_power_w"),
        "audio": ("capture_device", "playback_device", "sample_rate", "rx_gain_db", "tx_gain_db"),
        "spectrum": ("enabled", "source", "data_port", "max_fps", "port", "civ_address", "baud")},
}
# MIGRATIONS[n] : profil (dict des sections) au format n -> format n+1. None = impossible : profil à refaire.
MIGRATIONS: dict[int, Callable[[dict], dict] | None] = {}
NAME_RE = re.compile(r"^[\w .+-]{1,40}$")
FOLDER = "profils"


class ProfileError(ValueError):
    """Profil inutilisable : le message dit quoi faire."""


@dataclass
class Profile:
    name: str
    path: Path
    format: int
    version: str
    saved_at: str
    sections: dict


def current_fields() -> dict[str, tuple[str, ...]]:
    return {"rig": tuple(f.name for f in fields(cfgmod.Rig)), "audio": tuple(f.name for f in fields(cfgmod.Audio)),
            "spectrum": tuple(f.name for f in fields(cfgmod.Spectrum))}


def folder_for(config_path: Path) -> Path:
    return Path(config_path).parent / FOLDER


def file_name(name: str) -> str:
    """« IC-7300 maison » -> « ic-7300-maison.toml » (sans accent ni espace)."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return (slug or "profil") + ".toml"


def valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name)) and name.strip() == name


def _section_text(rendered: str, names: tuple[str, ...]) -> str:
    """Sections `names` d'un station.toml rendu par cfgmod.render_toml (commentaires compris)."""
    out, keep = [], False
    for line in rendered.splitlines():
        if line.startswith("["):
            keep = line.strip() in {f"[{n}]" for n in names}
        if keep:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def render(name: str, cfg: cfgmod.Config, version: str, saved_at: str) -> str:
    """Texte du profil : en-tête [profil] puis les sections du poste, telles que station.toml les écrit."""
    return ("# Profil de poste TRX distant (TRX Console, menu 18). Modifier de préférence par la console :\n"
            "# charger le profil, changer la configuration, puis le réenregistrer.\n"
            "[profil]\n"
            f"nom = {cfgmod._s(name)}\n"
            f"format = {PROFILE_FORMAT}\n"
            f"version = {cfgmod._s(version)}\n"
            f"enregistre_le = {cfgmod._s(saved_at)}\n\n"
            + _section_text(cfgmod.render_toml(cfg), SECTIONS))


def read(path: Path) -> Profile:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ProfileError(f"profil illisible ({exc})") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"profil abîmé (TOML invalide : {exc}) : supprime-le et réenregistre ce poste") from exc
    head = data.get("profil")
    fmt = head.get("format") if isinstance(head, dict) else None
    if not isinstance(fmt, int) or isinstance(fmt, bool) or fmt < 1:
        raise ProfileError("ce fichier n'est pas un profil de poste (en-tête [profil] absent ou abîmé)")
    sections = {k: v for k, v in data.items() if k != "profil"}
    return Profile(str(head.get("nom", Path(path).stem))[:40], Path(path), fmt, str(head.get("version", "?"))[:20],
                   str(head.get("enregistre_le", "?"))[:20], sections)


def upgrade(profile: Profile) -> dict:
    """Sections au format actuel (conversions successives) ; ProfileError si impossible."""
    if profile.format > PROFILE_FORMAT:
        raise ProfileError(f"profil enregistré par une version plus récente (format {profile.format}, version "
                           f"{profile.version}) : mets TRX distant à jour pour le charger")
    sections = {k: dict(v) if isinstance(v, dict) else v for k, v in profile.sections.items()}
    for fmt in range(profile.format, PROFILE_FORMAT):
        step = MIGRATIONS.get(fmt)
        if step is None:
            raise ProfileError(f"profil trop ancien (format {profile.format}, version {profile.version}) : sa conversion "
                               "n'est pas possible. Refais la configuration de ce poste (menu 2), puis enregistre-le "
                               "de nouveau (menu 18)")
        sections = step(sections)
    unknown = sorted(set(sections) - set(SECTIONS))
    if unknown:
        raise ProfileError("profil inattendu : section(s) " + ", ".join(f"[{s}]" for s in unknown)
                           + " hors du poste : refais la configuration de ce poste puis réenregistre-le")
    return sections


def apply(station_text: str, profile: Profile) -> tuple[cfgmod.Config, str]:
    """(config, texte de station.toml) avec les sections du poste remplacées par celles du profil, VALIDÉS.
    ProfileError si le résultat n'est pas une configuration valable (avec la liste des problèmes)."""
    sections = upgrade(profile)
    try:
        current = tomllib.loads(station_text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"station.toml illisible ({exc}) : corrige-le d'abord (menu 14)") from exc
    merged = dict(current)
    for name in SECTIONS:
        merged[name] = sections.get(name, {})          # section absente du profil : valeurs par défaut
    try:
        cfg = cfgmod.from_dict(merged)
    except cfgmod.ConfigError as exc:
        raise ProfileError("profil refusé, la station ne démarrerait pas avec :\n  - " + "\n  - ".join(exc.problems)
                           + "\nSi ce profil vient d'une ancienne version, refais la configuration de ce poste (menu 2) "
                           "puis réenregistre-le (menu 18)") from exc
    return cfg, cfgmod.render_toml(cfg)


def same_rig(cfg: cfgmod.Config, profile: Profile) -> bool:
    """Le profil décrit-il le poste en service ? (comparaison des sections une fois converties et complétées)"""
    try:
        sections = upgrade(profile)
        other, _ = cfgmod.build({name: sections.get(name, {}) for name in SECTIONS})
    except (ProfileError, cfgmod.ConfigError, TypeError):
        return False
    return (other.rig, other.audio, other.spectrum) == (cfg.rig, cfg.audio, cfg.spectrum)


def list_profiles(config_path: Path) -> list[tuple[Path, Profile | None, str]]:
    """[(fichier, profil ou None, problème)] triés par nom."""
    folder = folder_for(config_path)
    out = []
    for path in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
        try:
            out.append((path, read(path), ""))
        except ProfileError as exc:
            out.append((path, None, str(exc)))
    return out
