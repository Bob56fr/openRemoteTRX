# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Lancement et surveillance des modules, côté superviseur.

- Mode géré (Windows, ou Linux sans systemd) : le superviseur lance chaque
  module comme processus enfant à priorité basse et le relance s'il s'arrête,
  avec un délai croissant. Trop de redémarrages en peu de temps : le module
  est désactivé jusqu'à une intervention de l'utilisateur.
- Linux avec systemd : generate_systemd_unit() produit l'unité du module,
  avec ses plafonds CPUQuota, MemoryMax et Nice appliqués par le système.

Sécurité : un module ne tourne JAMAIS en root. Si le superviseur est root
(Debian), chaque module est lancé sous le compte de la station (`run_as`) ;
si ce compte n'existe pas, le module n'est pas lancé.

Les plafonds CPU et mémoire en mode géré (Job Objects sous Windows, cgroups
sous Linux) arrivent au lot 2 ; le lanceur applique déjà la priorité basse.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Callable

from . import API_VERSION, DEFAULT_BUS_HOST
from .manifest import Manifest, api_compatible

log = logging.getLogger("trx.launcher")

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000    # Windows

# États possibles d'un module
STOPPED, RUNNING, WAITING, DISABLED, INCOMPATIBLE = (
    "arrêté", "en marche", "redémarrage en attente", "désactivé", "incompatible")


@dataclass
class RestartPolicy:
    first_delay_s: float = 1.0
    max_delay_s: float = 30.0
    max_restarts: int = 5          # au-delà, dans la fenêtre : désactivé
    window_s: float = 300.0
    stable_after_s: float = 60.0   # une marche plus longue remet le délai à zéro


@dataclass
class ModuleProcess:
    manifest: Manifest
    state: str = STOPPED
    proc: subprocess.Popen | None = None
    started_at: float = 0.0
    restarts: list[float] = field(default_factory=list)
    delay_s: float = 0.0
    next_start: float = 0.0
    last_exit: int | None = None

    @property
    def name(self) -> str:
        return self.manifest.name


Notify = Callable[[str, str, str], None]      # (module, état, message)
SecretsSource = Callable[[], dict[str, str] | None]


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _user_exists(user: str) -> bool:
    try:
        import pwd
        pwd.getpwnam(user)
        return True
    except (ImportError, KeyError):
        return False


class ModuleLauncher:
    def __init__(self, manifests: list[Manifest],
                 secrets: dict[str, str] | SecretsSource, *,
                 bus_port: int, bus_host: str = DEFAULT_BUS_HOST,
                 python: str = sys.executable, cwd: Path | None = None,
                 policy: RestartPolicy | None = None,
                 notify: Notify | None = None, poll_s: float = 0.5,
                 run_as: str = "", is_root: Callable[[], bool] = _is_root,
                 user_exists: Callable[[str], bool] = _user_exists,
                 command_override: Callable[[Manifest], list[str]] | None = None,
                 extra_env: dict[str, str] | None = None) -> None:
        # secrets : dictionnaire, ou fonction qui le renvoie (None tant que la
        # clé des modules n'existe pas : les lancements attendent).
        self._secrets_source: SecretsSource = secrets if callable(secrets) else (lambda: secrets)
        self.secrets: dict[str, str] = {}
        self.run_as = run_as
        self._is_root = is_root
        self._user_exists = user_exists
        self._pending: set[str] = set()
        self.bus_host, self.bus_port = bus_host, bus_port
        self.python = python
        self.cwd = Path(cwd) if cwd else Path.cwd()
        self.policy = policy or RestartPolicy()
        self.notify = notify
        self.poll_s = poll_s
        self.command_override = command_override
        self.extra_env = dict(extra_env or {})          # ex. TRX_CONFIG_PATH (jamais de secret ici)
        self.modules: dict[str, ModuleProcess] = {}
        for m in manifests:
            mp = ModuleProcess(manifest=m)
            if not api_compatible(m.api, API_VERSION):
                mp.state = INCOMPATIBLE
                self._notify(mp, f"API {m.api} attendue, {API_VERSION} fournie : "
                                 "module non lancé")
            self.modules[m.name] = mp
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------- commandes
    def command_for(self, m: Manifest) -> list[str]:
        if self.command_override:
            return self.command_override(m)
        return [self.python, "-m", m.entry]

    def env_for(self, m: Manifest) -> dict[str, str]:
        env = dict(os.environ)
        env.update({"TRX_MODULE_NAME": m.name,
                    "TRX_MODULE_SECRET": self.secrets.get(m.name, ""),
                    "TRX_BUS_HOST": self.bus_host,
                    "TRX_BUS_PORT": str(self.bus_port),
                    "PYTHONUNBUFFERED": "1"})
        env.update(self.extra_env)
        return env

    def _refresh_secrets(self) -> bool:
        try:
            found = self._secrets_source()
        except Exception:
            log.exception("secrets des modules illisibles")
            found = None
        if found:
            self.secrets = dict(found)
        return bool(self.secrets)

    def _account_kwargs(self, mp: ModuleProcess) -> dict | None:
        """Compte d'exécution ; None = lancement interdit (jamais de module en root)."""
        if os.name == "nt" or not self._is_root():
            return {}
        if not self.run_as or self.run_as == "root" or not self._user_exists(self.run_as):
            mp.state = DISABLED
            self._notify(mp, f"le superviseur est root et le compte « {self.run_as or '?'} » "
                             "est introuvable : module non lancé (jamais en root)")
            return None
        try:
            import pwd
            info = pwd.getpwnam(self.run_as)
            groups = os.getgrouplist(self.run_as, info.pw_gid)   # ex. video pour une caméra USB
        except (ImportError, KeyError, OSError) as exc:
            mp.state = DISABLED
            self._notify(mp, f"compte « {self.run_as} » inutilisable ({exc}) : module non lancé")
            return None
        return {"user": info.pw_uid, "group": info.pw_gid, "extra_groups": groups,
                "_home": info.pw_dir}

    def _spawn(self, mp: ModuleProcess) -> bool:
        m = mp.manifest
        if mp.name not in self.secrets and not (self._refresh_secrets() and mp.name in self.secrets):
            return False                  # clé des modules pas encore créée : on réessaiera
        account = self._account_kwargs(mp)
        if account is None:
            return False
        env = self.env_for(m)
        home = account.pop("_home", None)
        if home:
            env.update({"HOME": home, "USER": self.run_as, "LOGNAME": self.run_as})
        kwargs: dict = {"cwd": str(self.cwd), "env": env, **account}
        if os.name == "nt":
            kwargs["creationflags"] = BELOW_NORMAL_PRIORITY_CLASS
        else:
            nice = m.resources.nice
            kwargs["preexec_fn"] = lambda: os.nice(nice)
            kwargs["start_new_session"] = True
        try:
            mp.proc = subprocess.Popen(self.command_for(m), **kwargs)
        except (OSError, KeyError, ValueError) as exc:
            mp.state = DISABLED
            self._notify(mp, f"lancement impossible : {exc}")
            return False
        mp.started_at = time.monotonic()
        mp.state = RUNNING
        self._pending.discard(mp.name)
        log.info("module %s lancé (pid %s)", m.name, mp.proc.pid)
        return True

    def start(self, name: str) -> bool:
        mp = self.modules[name]
        if mp.state in (INCOMPATIBLE, RUNNING, DISABLED):
            return False
        mp.restarts.clear()
        mp.delay_s = 0.0
        if self._spawn(mp):
            return True
        if mp.state != DISABLED:
            self._pending.add(name)       # réessayé à chaque passage de surveillance
        return False

    def enable(self, name: str) -> bool:
        """Réactive un module désactivé (action de l'utilisateur)."""
        mp = self.modules[name]
        if mp.state != DISABLED:
            return False
        mp.state = STOPPED
        return self.start(name)

    @property
    def pending(self) -> frozenset[str]:
        """Modules dont le lancement attend la clé des modules."""
        return frozenset(self._pending)

    def stop(self, name: str, timeout_s: float = 5.0) -> None:
        mp = self.modules[name]
        if mp.proc and mp.proc.poll() is None:
            mp.proc.terminate()
            try:
                mp.proc.wait(timeout_s)
            except subprocess.TimeoutExpired:
                mp.proc.kill()
                mp.proc.wait(timeout_s)
        mp.proc = None
        self._pending.discard(name)
        if mp.state in (RUNNING, WAITING):
            mp.state = STOPPED

    def stop_all(self) -> None:
        for name in self.modules:
            self.stop(name)

    def status(self) -> dict[str, dict]:
        return {n: {"state": mp.state, "version": mp.manifest.version,
                    "pid": mp.proc.pid if mp.proc and mp.proc.poll() is None else None,
                    "restarts": len(mp.restarts), "last_exit": mp.last_exit}
                for n, mp in self.modules.items()}

    # ------------------------------------------------------------- surveillance
    def start_auto(self) -> None:
        for name, mp in self.modules.items():
            if mp.manifest.start == "auto" and mp.state == STOPPED:
                self.start(name)

    def check(self, now: float | None = None) -> None:
        """Un passage de surveillance (appelé périodiquement)."""
        now = time.monotonic() if now is None else now
        p = self.policy
        for name in sorted(self._pending):
            mp = self.modules[name]
            if mp.state == STOPPED:
                self._spawn(mp)
            else:
                self._pending.discard(name)
        for mp in self.modules.values():
            if mp.state == RUNNING and mp.proc is not None:
                code = mp.proc.poll()
                if code is None:
                    if now - mp.started_at >= p.stable_after_s:
                        mp.delay_s = 0.0
                    continue
                mp.last_exit = code
                mp.proc = None
                mp.restarts = [t for t in mp.restarts if now - t < p.window_s]
                mp.restarts.append(now)
                if len(mp.restarts) > p.max_restarts:
                    mp.state = DISABLED
                    self._notify(mp, f"arrêté {len(mp.restarts)} fois en moins de "
                                     f"{p.window_s:.0f} s : désactivé")
                    continue
                mp.delay_s = p.first_delay_s if mp.delay_s == 0 else \
                    min(p.max_delay_s, mp.delay_s * 2)
                mp.next_start = now + mp.delay_s
                mp.state = WAITING
                self._notify(mp, f"arrêt inattendu (code {code}), "
                                 f"relance dans {mp.delay_s:.0f} s")
            elif mp.state == WAITING and now >= mp.next_start:
                if not self._spawn(mp) and mp.state == WAITING:
                    mp.next_start = now + p.first_delay_s

    async def run(self) -> None:
        self.start_auto()
        try:
            while True:
                self.check()
                await asyncio.sleep(self.poll_s)
        finally:
            self.stop_all()

    def _notify(self, mp: ModuleProcess, message: str) -> None:
        log.warning("module %s : %s", mp.name, message)
        if self.notify:
            try:
                self.notify(mp.name, mp.state, message)
            except Exception:
                log.exception("notification impossible")


def generate_systemd_unit(m: Manifest, *, python: str, workdir: Path,
                          env_file: Path, user: str | None = None,
                          core_unit: str | None = None) -> str:
    """Unité systemd d'un module, plafonds du manifeste appliqués par le système.

    Le secret n'est jamais écrit dans l'unité : il est lu depuis env_file
    (droits 600), qui contient TRX_MODULE_NAME, TRX_MODULE_SECRET, TRX_BUS_PORT.
    """
    def posix(p) -> str:
        # Une unité systemd vise toujours Linux : barres obliques, même si
        # elle est générée depuis Windows.
        return p.as_posix() if isinstance(p, PurePath) else str(p).replace("\\", "/")

    workdir, env_file, python = posix(workdir), posix(env_file), posix(python)
    after = f"network.target {core_unit}" if core_unit else "network.target"
    lines = [
        "[Unit]",
        f"Description=TRX distant - module {m.name}",
        f"After={after}",
        "StartLimitIntervalSec=300",
        "StartLimitBurst=5",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={workdir}",
        f"EnvironmentFile={env_file}",
        f"ExecStart={python} -m {m.entry}",
        "Restart=on-failure",
        "RestartSec=2",
        f"CPUQuota={m.resources.cpu_quota}%",
        f"MemoryMax={m.resources.memory_max_mb}M",
        f"Nice={m.resources.nice}",
        "NoNewPrivileges=yes",
    ]
    if user:
        lines.append(f"User={user}")
    lines += ["", "[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lines)
