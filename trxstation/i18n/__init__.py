# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Langues des outils de la station (aujourd'hui : openRemoteTRX Console). Français, anglais, allemand, espagnol ; d'autres
langues viendront : ajouter son code à LANGS, son nom à NAMES et ses catalogues.

Catalogues : `trxstation/i18n/<domaine>.<langue>.json` (livrés avec la station), un objet {clé: texte} ; les
textes acceptent des champs `{nom}` (str.format). Le FRANÇAIS est la référence : une clé absente d'une autre langue
retombe sur le français (les tests exigent pourtant les MÊMES clés dans toutes les langues). Une clé absente partout
s'affiche telle quelle (jamais d'exception : une console doit toujours s'afficher).

Choix de la langue, PAR COMPTE de l'ordinateur : `~/.config/trx-remote/console.json` (Windows :
`%APPDATA%\\trx-remote\\console.json`), {"lang": "en"} ; à défaut, la langue du système (LANGUAGE, LC_ALL,
LC_MESSAGES, LANG, puis la locale de Windows) si elle est connue, sinon le français.
"""
from __future__ import annotations

import json
import locale
import os
import sys
from functools import lru_cache
from pathlib import Path

LANGS = ("fr", "en", "de", "es")
NAMES = {"fr": "Français", "en": "English", "de": "Deutsch", "es": "Español"}
DEFAULT = "fr"
FOLDER = Path(__file__).resolve().parent
_WINDOWS_NAMES = {"french": "fr", "english": "en", "german": "de", "spanish": "es"}


@lru_cache(maxsize=None)
def catalog(lang: str, domain: str = "console") -> dict[str, str]:
    """Textes d'une langue ({} si le fichier manque ou est illisible)."""
    try:
        data = json.loads((FOLDER / f"{domain}.{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}


class Translator:
    def __init__(self, lang: str = DEFAULT, domain: str = "console") -> None:
        self.lang = lang if lang in LANGS else DEFAULT
        self.domain = domain
        # Clés lues depuis le dernier message affiché : la console web en déduit un refus (rouge) ou un abandon,
        # quelle que soit la langue (étape 235). Vidée par celui qui la lit ; bornée.
        self.used: list[str] = []

    def __call__(self, _key: str, **fields) -> str:
        self.used.append(_key)
        del self.used[:-20]
        text = catalog(self.lang, self.domain).get(_key)
        if text is None:
            text = catalog(DEFAULT, self.domain).get(_key, _key)
        if fields:
            try:
                return text.format(**fields)
            except (KeyError, IndexError, ValueError):
                return text
        return text


def _code(value: str | None) -> str | None:
    """« de_DE.UTF-8 », « en », « German_Germany » -> code connu, sinon None."""
    if not value:
        return None
    value = value.strip()
    head = value.split(":")[0].split(".")[0].split("_")[0].split("-")[0].lower()
    if head in LANGS:
        return head
    return _WINDOWS_NAMES.get(head)


def system_lang(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        code = _code(env.get(var))
        if code:
            return code
    if sys.platform == "win32" and env is os.environ:
        try:
            code = _code(locale.getlocale()[0])
        except (ValueError, TypeError):
            code = None
        if code:
            return code
    return DEFAULT


def prefs_path(home: Path | None = None, env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if sys.platform == "win32" and env.get("APPDATA") and home is None:
        return Path(env["APPDATA"]) / "trx-remote" / "console.json"
    return (home or Path.home()) / ".config" / "trx-remote" / "console.json"


def load_lang(path: Path, env: dict[str, str] | None = None) -> str:
    """Langue choisie (menu 0), sinon celle du système, sinon le français."""
    try:
        lang = json.loads(path.read_text(encoding="utf-8")).get("lang")
        if lang in LANGS:
            return lang
    except (OSError, ValueError, AttributeError):
        pass
    return system_lang(env)


ENV_LANG = "TRX_LANG"             # langue passée par openRemoteTRX Console aux outils qu'elle lance (sudo compris, étape 240)


def tool_lang(env: dict[str, str] | None = None) -> str:
    """Langue d'un OUTIL (trx-setup, trx-monitor…, lot L3) : celle que lui passe openRemoteTRX Console (`TRX_LANG`), sinon le
    choix du menu 0 du compte qui le lance, sinon celle du système, sinon le français."""
    env = os.environ if env is None else env
    lang = env.get(ENV_LANG, "")
    if lang in LANGS:
        return lang
    return load_lang(prefs_path(env=env), env)


def tool_translator(domain: str, env: dict[str, str] | None = None) -> "Translator":
    """Traducteur d'un outil : textes de `trxstation/i18n/<domain>.<langue>.json`, français si une clé manque."""
    return Translator(tool_lang(env), domain)


def _prefs(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_pref(path: Path, key: str, value: str) -> bool:
    data = _prefs(path)
    data[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def save_lang(path: Path, lang: str) -> bool:
    """Enregistre le choix ; False si le fichier ne peut pas être écrit (la langue vaut alors pour cette session)."""
    if lang not in LANGS:
        return False
    return _save_pref(path, "lang", lang)


# Niveaux d'affichage d'openRemoteTRX Console (étape 234, décisions de l'utilisateur du 2026-11-17) : ils CACHENT des menus pour
# ne pas noyer un débutant, ils ne protègent rien (un numéro tapé ouvre toujours son menu).
LEVELS = ("basic", "normal", "expert")


def load_level(path: Path, configured: bool) -> str:
    """Niveau choisi (menu 0 ou boutons de la page) ; sinon Basic, station configurée ou non (décision de
    l'utilisateur, étape 235 : moins de menus, moins de clics). Le défaut est enregistré tout de suite.
    `configured` n'est plus utilisé (gardé pour les appelants)."""
    level = _prefs(path).get("level")
    if level in LEVELS:
        return level
    level = "basic"
    _save_pref(path, "level", level)
    return level


def save_level(path: Path, level: str) -> bool:
    if level not in LEVELS:
        return False
    return _save_pref(path, "level", level)
