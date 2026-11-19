# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Essai d'extinction et de rallumage du poste par la CAT (TRX Console, menu 2.8), station ARRÊTÉE.

`python -m trxstation.power_trial --config station.toml` : poste lu allumé et en réception, éteint, ports relus
(présents, même identité USB), rallumé, puis fréquence, mode et PTT relus. Code de sortie 0 = réussi ; la mise en
service de l'allumage à distance n'est proposée qu'après un essai réussi (docs/alimentation-poste-cahier-des-charges.md
§ 8.3). N'émet JAMAIS : la seule commande de PTT est « T 0 », si le poste se rallume en émission. Même déroulé que
l'essai réel du FTDX10 du 2026-11-19 (rigctl d'une commande à la fois).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import config as cfgmod
from . import ports as portsmod
from . import usbports
from .crashguard import guarded
from .hamlib import find_tool
from .i18n import tool_translator
from .paths import default_config_path

OFF_WAIT_S = 15.0
PORTS_WAIT_S = 5.0
ORDER_TIMEOUT_S = 30.0
READ_TIMEOUT_S = 15.0


def khz_text(hz: int) -> str:
    """27555000 -> « 27 555,00 kHz » (comme la page)."""
    whole, frac = f"{hz / 1000:.2f}".split(".")
    groups = f"{int(whole):,}".replace(",", " ")
    return f"{groups},{frac} kHz"


def t(key: str, **fields) -> str:
    return tool_translator("power")(key, **fields)


def rigctl_base(cfg: cfgmod.Config, rigctl: str) -> list[str]:
    r = cfg.rig
    args = [rigctl, "-m", str(r.model)]
    if r.port:
        args += ["-r", r.port]
    if r.speed:
        args += ["-s", str(r.speed)]
    if r.ptt_type != "RIG":
        args += ["-P", r.ptt_type]
    if r.ptt_port:
        args += ["-p", r.ptt_port]
    for conf in r.extra_conf:
        args += ["-C", conf]
    return args


class Trial:
    def __init__(self, cfg: cfgmod.Config, rigctl: str, *, run=subprocess.run, say: Callable[[str], None] = print,
                 port_present: Callable[[str], bool] = portsmod.port_present,
                 identity: Callable[[str], usbports.UsbIdentity | None] = usbports.identity,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.cfg, self.base, self.run_, self.say = cfg, rigctl_base(cfg, rigctl), run, say
        self.port_present, self.identity, self.sleep, self.clock = port_present, identity, sleep, clock

    def rigctl(self, *command: str, timeout: float = READ_TIMEOUT_S) -> tuple[int, str]:
        try:
            done = self.run_([*self.base, *command], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return -1, ""
        out = (done.stdout or b"")
        if isinstance(out, bytes):
            out = out.replace(b"\0", b"").decode("utf-8", "replace")
        return done.returncode, out.strip()

    def value(self, command: str) -> str | None:
        code, out = self.rigctl(command)
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        return lines[-1] if code == 0 and lines else None

    def powered(self) -> bool | None:
        raw = self.value("get_powerstat")       # SANS antislash : rigctl 4.7.2 refuse « \get_powerstat » en argument
        return None if raw is None else raw == "1"

    def wait_power(self, on: bool, seconds: float) -> bool:
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            if self.powered() is on:
                return True
            self.sleep(1.0)
        return False

    def ptt_off_if_needed(self) -> bool:
        """True si le poste est en émission (« T 0 » envoyé aussitôt) : l'essai échoue."""
        if self.value("t") in ("1", "2", "3"):
            self.rigctl("T", "0")
            return True
        return False

    def run(self) -> bool:
        cfg, say = self.cfg, self.say
        port = cfg.rig.port
        say(t("start", model=cfg.rig.model, port=port or "-"))
        if self.powered() is not True:
            say(t("not_on"))
            return False
        if self.ptt_off_if_needed():
            say(t("tx_before"))
            return False
        before = self.identity(port) if port else None
        say(t("step_off"))
        code, _ = self.rigctl("set_powerstat", "0", timeout=ORDER_TIMEOUT_S)
        if code != 0 or not self.wait_power(False, OFF_WAIT_S):
            say(t("off_failed"))
            return False
        say(t("off_ok"))
        self.sleep(PORTS_WAIT_S)
        if port:
            if not self.port_present(port):
                say(t("port_gone", port=port))
                return False
            after = self.identity(port)
            if before is not None and not usbports.same_device(before, after):
                say(t("port_changed", port=port))
                return False
            say(t("ports_ok", port=port, ident=str(after) if after else t("no_ident")))
        say(t("step_on", seconds=cfg.power.on_timeout_s))
        started = self.clock()
        self.rigctl("set_powerstat", "1", timeout=ORDER_TIMEOUT_S)
        if not self.wait_power(True, float(cfg.power.on_timeout_s)):
            say(t("on_failed", seconds=cfg.power.on_timeout_s))
            return False
        seconds = self.clock() - started
        freq = None
        deadline = self.clock() + 10.0
        while self.clock() < deadline and freq is None:
            raw = self.value("f")
            freq = int(float(raw)) if raw and raw.replace(".", "", 1).isdigit() else None
            if freq is None:
                self.sleep(1.0)
        code, out = self.rigctl("m")                    # « USB » puis la largeur « 3000 » : le mode est la PREMIÈRE ligne
        mode = next((line.strip() for line in out.splitlines() if line.strip()), "") if code == 0 else ""
        if self.ptt_off_if_needed():
            say(t("tx_after"))
            return False
        shown = khz_text(freq) if freq else t("no_freq")
        say(t("on_ok", seconds=f"{seconds:.0f}", freq=shown, mode=mode or "-"))
        return True


@guarded("trx-power-trial")
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trx-power-trial", description=t("description"))
    ap.add_argument("--config", type=Path, default=default_config_path())
    args = ap.parse_args(argv)
    try:
        cfg = cfgmod.load(args.config)
    except (OSError, cfgmod.ConfigError) as exc:
        print(t("config_bad", detail=exc), file=sys.stderr)
        return 2
    rigctl = find_tool("rigctl", cfg.tools.hamlib_dir)
    if not rigctl:
        print(t("no_rigctl"), file=sys.stderr)
        return 2
    ok = Trial(cfg, rigctl).run()
    print(t("result_ok") if ok else t("result_failed"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
