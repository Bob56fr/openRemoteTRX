# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Sert la page d'openRemoteTRX-Autotest sur http://127.0.0.1:8765/ depuis n'importe quel dossier courant.

`python -m http.server --directory autotest/web` dépend du dossier où l'on se trouve (sinon : erreur 404) ;
ce lanceur trouve la page à côté de lui. Web Serial exige 127.0.0.1 (ou HTTPS)."""
from __future__ import annotations

import functools
import http.server
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as srv:
        print(f"Page de l'Autotest : http://127.0.0.1:{port}/  (Ctrl+C pour arrêter)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
