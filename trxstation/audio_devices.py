"""Périphériques audio : `sounddevice` (PortAudio) si disponible, identique sous Windows, Linux et
Raspberry Pi ; sinon, sous Linux, repli sur ALSA (`arecord -l` / `aplay -l`).

La valeur retournée est ce qui s'écrit dans station.toml : le NOM du périphérique (sous-chaîne
acceptée à l'utilisation), ou l'identifiant ALSA stable en repli.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys

_UNSET = object()
_CARD_RE = re.compile(r"^card (\d+): (\S+) \[(.+?)\], device (\d+): (.+?) \[")
HOSTAPI_PREFERENCE = ("WASAPI", "ALSA", "Core Audio", "MME", "DirectSound", "WDM-KS")


def parse_audio_list(text: str) -> list[tuple[str, str]]:
    """Analyse `arecord -l` / `aplay -l` -> [(périphérique ALSA stable, libellé)]."""
    devices = []
    for line in text.splitlines():
        m = _CARD_RE.match(line)
        if m:
            devices.append((f"plughw:CARD={m.group(2)},DEV={m.group(4)}", f"{m.group(3)} (carte {m.group(1)})"))
    return devices


def _alsa_devices(kind: str) -> list[tuple[str, str]]:
    tool = "arecord" if kind == "capture" else "aplay"
    if not shutil.which(tool):
        return []
    out = subprocess.run([tool, "-l"], capture_output=True, text=True, timeout=10).stdout
    return parse_audio_list(out)


def _import_sounddevice():
    try:
        import sounddevice  # type: ignore[import-not-found]
        return sounddevice
    except Exception:          # absent, ou PortAudio manquant (OSError)
        return None


def _hostapi_rank(name: str) -> int:
    for rank, key in enumerate(HOSTAPI_PREFERENCE):
        if key.lower() in name.lower():
            return rank
    return len(HOSTAPI_PREFERENCE)


def list_audio_devices(kind: str, *, sd=_UNSET, platform: str | None = None) -> list[tuple[str, str]]:
    """kind = « capture » (son reçu du poste) ou « playback » (son envoyé au poste)."""
    module = _import_sounddevice() if sd is _UNSET else sd
    if module is not None:
        try:
            hostapis = [h["name"] for h in module.query_hostapis()]
            channels = "max_input_channels" if kind == "capture" else "max_output_channels"
            candidates = []
            for index, dev in enumerate(module.query_devices()):
                if dev.get(channels, 0) > 0:
                    api = hostapis[dev["hostapi"]] if dev.get("hostapi") is not None else "?"
                    candidates.append((_hostapi_rank(api), index, dev["name"], api))
            seen, result = set(), []
            for _, _, name, api in sorted(candidates):          # une entrée par nom, meilleure API d'abord
                if name not in seen:
                    seen.add(name)
                    result.append((name, f"{name}  [{api}]"))
            return result
        except Exception:
            pass                                                # on tente le repli ALSA
    if (platform or sys.platform).startswith("linux"):
        return _alsa_devices(kind)
    return []


def resolve_device(name: str, kind: str, sd) -> int:
    """Index PortAudio d'un périphérique d'après son nom (exact, sinon sous-chaîne sans casse).

    Plusieurs interfaces audio (WASAPI, MME...) portent le même nom sous Windows : la
    meilleure d'après HOSTAPI_PREFERENCE est retenue. LookupError si rien ne correspond.
    """
    channels = "max_input_channels" if kind == "capture" else "max_output_channels"
    hostapis = [h["name"] for h in sd.query_hostapis()]
    wanted = name.strip().lower()
    exact, partial = [], []
    for index, dev in enumerate(sd.query_devices()):
        if dev.get(channels, 0) <= 0:
            continue
        api = hostapis[dev["hostapi"]] if dev.get("hostapi") is not None else ""
        entry = (_hostapi_rank(api), index)
        if dev["name"].lower() == wanted:
            exact.append(entry)
        elif wanted in dev["name"].lower():
            partial.append(entry)
    found = sorted(exact) or sorted(partial)
    if not found:
        raise LookupError(f"aucun périphérique audio « {name} » ({kind}) : lance trx-setup pour la liste")
    return found[0][1]


def real_device_names(*specs: str) -> list[str]:
    """Noms des VRAIS périphériques audio parmi des réglages (exclut vide, null, file:, tone:, click:)."""
    names = []
    for spec in specs:
        spec = (spec or "").strip()
        if spec and spec != "null" and not spec.startswith(("file:", "tone:", "click:")):
            names.append(spec)
    return names
