"""Affiche les réponses BRUTES de rigctld (lecture seule) pour diagnostiquer un poste :

    python -m trxstation.devtools.cat_raw --port 4532 f m t "l STRENGTH" "l ALC"

Commandes acceptées : f (fréquence), m (mode), t (état du PTT), l <NIVEAU> (ex. l STRENGTH). Rien d'autre :
cet outil ne peut ni accorder ni émettre. Chaque commande est envoyée en protocole étendu (« + ») puis
sans, pour comparer les deux formats.
"""
from __future__ import annotations

import argparse
import re
import socket
import sys

ALLOWED = re.compile(r"^(f|m|t|l [A-Z][A-Z0-9_]{1,23})$")


def raw_query(host: str, port: int, command: str, extended: bool = True, timeout: float = 3.0) -> list[str]:
    with socket.create_connection((host, port), timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall((("+" if extended else "") + command + "\n").encode())
        buf = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                text = buf.decode(errors="replace")
                if (extended and text.rstrip().splitlines()[-1:] and text.rstrip().splitlines()[-1].startswith("RPRT")) \
                        or (not extended and text.endswith("\n")):
                    break
        except socket.timeout:
            pass
    return buf.decode(errors="replace").splitlines()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4532)
    ap.add_argument("commands", nargs="+", help='ex. f m t "l STRENGTH"')
    args = ap.parse_args(argv)
    bad = [c for c in args.commands if not ALLOWED.fullmatch(c)]
    if bad:
        print(f"Refusé (lecture seule : f, m, t, l NIVEAU) : {bad}", file=sys.stderr)
        return 2
    for command in args.commands:
        for extended in (True, False):
            try:
                lines = raw_query(args.host, args.port, command, extended)
            except OSError as exc:
                print(f"rigctld injoignable : {exc}", file=sys.stderr)
                return 3
            print(f"{'+' if extended else ' '}{command:<12} -> {lines!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
