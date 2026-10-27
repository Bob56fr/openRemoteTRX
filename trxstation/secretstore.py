"""secrets.toml : mots de passe et clés d'API des modules, À CÔTÉ de station.toml mais jamais dedans.

station.toml se joint aux rapports, se copie d'une station à l'autre, se montre pour obtenir de l'aide :
elle ne contient que le NOM d'un secret (`secret = "cluster-principal"`). Les valeurs sont ici :

    [secrets]
    "cluster-principal" = "mot de passe"

Règles :
- droits 0600 (Linux), propriétaire = compte des modules (`trx`) : lisible par eux seuls ;
- jamais dans un rapport, un journal ni un message (affichage : ****) ;
- jamais écrasé par une mise à jour (install.sh ne touche qu'à station.toml) ;
- pas de chiffrement sur disque : la clé devrait être sur la même machine pour que la station démarre seule.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path

FILE_NAME = "secrets.toml"
NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
MAX_VALUE = 128
MASK = "****"


class SecretsError(ValueError):
    pass


def path_for(config_path: str | Path) -> Path:
    return Path(config_path).parent / FILE_NAME


def check_value(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_VALUE:
        raise SecretsError(f"valeur vide ou de plus de {MAX_VALUE} caractères")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise SecretsError("caractère de contrôle refusé (il permettrait d'envoyer une commande au serveur)")
    return value


def load(path: str | Path) -> dict[str, str]:
    """Secrets lisibles ; fichier absent = aucun. SecretsError si illisible ou mal formé (jamais la valeur dans le message)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SecretsError(f"{path} illisible ({exc.strerror or type(exc).__name__})") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise SecretsError(f"{path} : TOML illisible") from None
    table = data.get("secrets", {})
    if not isinstance(table, dict):
        raise SecretsError(f"{path} : table [secrets] attendue")
    out: dict[str, str] = {}
    for name, value in table.items():
        if not NAME_RE.fullmatch(name) or not isinstance(value, str):
            raise SecretsError(f"{path} : entrée « {name[:32]} » invalide")
        out[name] = value
    return out


def permission_problem(path: str | Path) -> str | None:
    """Phrase lisible si le fichier est lisible par d'autres que son propriétaire (Linux) ; None sinon."""
    if os.name != "posix":
        return None
    try:
        mode = Path(path).stat().st_mode & 0o777
    except OSError:
        return None
    if mode & 0o077:
        return f"droits {oct(mode)[2:]} : lisible par d'autres comptes (0600 attendu)"
    return None


def _owner(account: str) -> tuple[int, int] | None:
    try:
        import pwd
        entry = pwd.getpwnam(account)
        return entry.pw_uid, entry.pw_gid
    except (ImportError, KeyError):
        return None


def fix_permissions(path: str | Path, account: str = "trx") -> None:
    """0600, et propriétaire `account` si l'on est root (sinon le propriétaire reste celui qui écrit)."""
    if os.name != "posix":
        return
    path = Path(path)
    os.chmod(path, 0o600)
    owner = _owner(account) if os.geteuid() == 0 else None
    if owner is not None:
        os.chown(path, *owner)


def render(secrets: dict[str, str]) -> str:
    lines = ["# secrets.toml : mots de passe des sources du cluster DX. NE JAMAIS JOINDRE À UN RAPPORT.",
             "# Droits 0600. Se modifie avec TRX Console (menu 12).", "[secrets]"]
    for name in sorted(secrets):
        if not NAME_RE.fullmatch(name):
            raise SecretsError(f"nom de secret invalide : {name[:32]}")
        lines.append(f"{json.dumps(name)} = {json.dumps(check_value(secrets[name]), ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def save(path: str | Path, secrets: dict[str, str], account: str = "trx") -> None:
    """Écriture atomique, créée d'emblée en 0600 (jamais un instant lisible par d'autres)."""
    path = Path(path)
    text = render(secrets)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secrets-")      # mkstemp crée en 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        fix_permissions(tmp, account)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
