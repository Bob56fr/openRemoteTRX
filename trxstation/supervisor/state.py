# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""État persistant du superviseur : mode sûr et historique des redémarrages.

Les dates utilisent l'horloge murale. Sur un Pi sans RTC l'heure peut être fausse après un
reboot : une date « dans le futur » est comptée comme récente (choix prudent : on préfère
entrer en mode sûr que rebooter en boucle).
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

KEEP_REBOOTS = 20


class StateStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _atomic_write(self, name: str, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".st-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o644)             # lisible par TRX Console (diagnostic) : le superviseur tourne en root
            os.replace(tmp, self.dir / name)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def safe_mode(self) -> str | None:
        path = self.dir / "safe_mode"
        try:
            return path.read_text(encoding="utf-8").strip() or "raison inconnue"
        except FileNotFoundError:
            return None
        except OSError:
            return "mode sûr (fichier illisible)"   # dans le doute, on reste en mode sûr

    def set_safe_mode(self, reason: str) -> None:
        self._atomic_write("safe_mode", reason or "raison inconnue")

    def clear_safe_mode(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            (self.dir / "safe_mode").unlink()

    def reboot_times(self) -> list[float]:
        try:
            data = json.loads((self.dir / "reboots.json").read_text(encoding="utf-8"))
            return [float(t) for t in data if isinstance(t, (int, float)) and not isinstance(t, bool)]
        except (OSError, ValueError, TypeError):
            return []

    def add_reboot(self, when: float) -> None:
        self._atomic_write("reboots.json", json.dumps((self.reboot_times() + [when])[-KEEP_REBOOTS:]))
