"""Lancement des modules par le superviseur (Windows, Linux, Raspberry Pi).

Les modules sont des processus enfants du superviseur, sur toutes les
plateformes : priorité basse, relance avec délai croissant, désactivation
après trop de plantages, alerte ntfy à chaque incident. Sous Debian, le
superviseur est root : les modules sont lancés sous le compte `run_as`
(par défaut « trx »), jamais en root.

Le superviseur ne crée jamais la clé des modules : il attend que la
passerelle l'ait créée, puis lance les modules.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from .keys import key_path, module_secrets, read_key
from .launcher import ModuleLauncher, RestartPolicy
from .registry import selected_manifests

log = logging.getLogger(__name__)


def build_launcher(cfg, *, alert: Callable[[str, str], object] | None = None,
                   policy: RestartPolicy | None = None, **kwargs) -> ModuleLauncher | None:
    """Lanceur des modules de [modules] run, ou None s'il n'y en a aucun."""
    if not cfg.modules.enabled:
        return None
    manifests, problems = selected_manifests(cfg.modules)
    for problem in problems:
        log.warning("modules : %s", problem)
    if not manifests:
        return None
    names = [m.name for m in manifests]
    kpath = key_path(cfg.supervisor.state_dir)

    def secrets() -> dict[str, str] | None:
        key = read_key(kpath)
        return module_secrets(key, names) if key is not None else None

    def notify(module: str, state: str, message: str) -> None:
        if alert is not None:
            alert(f"Module {module}", f"{module} ({state}) : {message}")

    cwd = Path(cfg.supervisor.state_dir)
    return ModuleLauncher(manifests, secrets, bus_port=cfg.modules.bus_port,
                          cwd=cwd if cwd.is_dir() else None, policy=policy,
                          notify=notify, run_as=cfg.modules.run_as, **kwargs)


def start_modules(launcher: ModuleLauncher | None) -> None:
    """Lance tous les modules choisis (ceux qui attendent la clé partiront ensuite)."""
    if launcher is None:
        return
    for name in launcher.modules:
        try:
            launcher.start(name)
        except Exception:
            log.exception("module %s : lancement en erreur", name)


def make_tick(maintain: Callable[[], None], launcher: ModuleLauncher | None) -> Callable[[], None]:
    """Passage de supervision : processus de la station, puis modules.

    Une erreur côté modules est journalisée et n'interrompt JAMAIS la
    surveillance de l'émission.
    """
    if launcher is None:
        return maintain

    def tick() -> None:
        maintain()
        try:
            launcher.check()
        except Exception:
            log.exception("surveillance des modules en erreur")
    return tick
