"""Essai autonome du cluster DX (lot 1) : affiche les spots filtrés dans la console.

    python -m trxstation.cluster --indicatif F4XXX
    python -m trxstation.cluster --indicatif F4XXX --rbn --bandes 20m 40m --continent EU --duree 7200
    python -m trxstation.cluster --indicatif F4XXX --cb     # + Cluster DX des cibistes (11 m)
    python -m trxstation.cluster --connu clusterdx          # cibistes seulement (aucun indicatif envoyé)
    python -m trxstation.cluster --serveurs                 # serveurs proposés
    python -m trxstation.cluster --verifier-serveurs        # bannière seulement, rien n'est envoyé

Aucun lien avec le poste ni avec la station : on peut le lancer station
arrêtée ou en marche. À la fin (durée écoulée ou Ctrl+C), un bilan donne le
nombre de coupures et si chacune a été rattrapée (critère du lot 1 : 2 h sans
coupure non rattrapée).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import socket
import sys
import time
from pathlib import Path

from .. import paths
from . import clusterdx, cty as ctymod
from .bandplan import BAND_NAMES, MODES
from .cache import Spot, SpotCache, SpotFilter
from .cty import CONTINENTS
from .engine import Engine
from .feed import CONNECTED, Feed, Source, SourceState
from .servers import KNOWN, VERIFIED_ON, by_name
from .text import check_own_call

DEFAULT_CLUSTERS = ("on0dxk", "db0sue")


def default_cty_path() -> Path:
    return paths.default_state_dir() / "cluster" / "cty.dat"


def _hostport(text: str) -> tuple[str, int]:
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError(f"forme attendue HÔTE:PORT, reçu {text!r}")
    return host, int(port)


def build_sources(args: argparse.Namespace) -> list[Source]:
    sources: list[Source] = []
    for i, (host, port) in enumerate(args.source or [], start=1):
        sources.append(Source(f"cluster-{i}", "telnet", host, port, priority=i))
    names = list(args.connu or ([] if args.source else list(DEFAULT_CLUSTERS)))
    names += [name for flag, name in ((args.rbn, "rbn-cw"), (args.cb, "clusterdx")) if flag]
    for name in dict.fromkeys(names):                      # sans doublon, ordre gardé
        k = by_name(name)
        if k is None:
            raise SystemExit(f"serveur inconnu : {name} (voir --serveurs)")
        sources.append(Source(k.name, k.kind, k.host, k.port, priority=len(sources) + 1, url=k.url))
    if args.mot_de_passe and sources:
        first = sources[0]
        pw = getpass.getpass(f"Mot de passe pour {first.name} (rien ne s'affiche) : ")
        sources[0] = Source(first.name, first.kind, first.host, first.port, first.priority,
                            password=pw or None)
    return sources


def format_spot(s: Spot, new: bool) -> str:
    mode = (s.mode or "?") + ("*" if s.mode_guessed else "")
    where = f"{s.country or '?'}/{s.continent or '?'}"
    more = f" ({s.count} spotteurs)" if s.count > 1 else ""
    tag = {"rbn": "RBN", "cb": "CB "}.get(s.kind, "DX ")
    mark = "+" if new else "~"
    return (f"{time.strftime('%H:%M:%S')} {mark} {tag} {s.freq_khz:>10.1f}  {s.dx:<12} {mode:<6} "
            f"de {s.spotter:<10} {where:<28}{more}  {s.comment}")


def status_line(engine: Engine, feed: Feed) -> str:
    c = engine.counters()
    states = " ".join(f"{name}={st.state}" for name, st in feed.states.items() if st.state != "disabled")
    age = "jamais" if c["last_spot_age_s"] is None else f"{c['last_spot_age_s']:.0f} s"
    return (f"-- {time.strftime('%H:%M:%S')}  {states} | {c['per_minute']}/min, reçus {c['received']}, "
            f"mal formés {c['malformed']}, filtrés {c['filtered']}, doublons {c['duplicates']}, "
            f"cache {c['cache']}, dernier spot il y a {age}")


def summary(engine: Engine, feed: Feed, elapsed: float) -> list[str]:
    out = [f"Bilan après {elapsed / 60:.1f} min :"]
    c = engine.counters()
    out.append(f"  spots lus {c['received']}, mal formés {c['malformed']}, filtrés {c['filtered']}, "
               f"doublons {c['duplicates']}, en cache {c['cache']}")
    worst = 0
    for name, st in feed.streams.items():
        rec = ", ".join(f"{d:.0f} s" for d in st.recover_s) or "-"
        out.append(f"  flux {name} : coupures {st.losses}, rattrapées {st.recovered} (reprise : {rec})")
        worst = max(worst, st.unrecovered)
    for name, st in feed.states.items():
        if st.last_code and st.state != CONNECTED:
            out.append(f"  {name} : {st.state}, dernier motif : {st.last_message}")
    out.append("  RÉSULTAT : aucune coupure non rattrapée." if worst == 0 else
               f"  RÉSULTAT : {worst} coupure(s) NON rattrapée(s) à la fin de l'essai.")
    return out


def verify_servers(timeout: float = 8.0) -> int:
    print(f"Serveurs proposés (vérifiés le {VERIFIED_ON}) : connexion et lecture de la bannière, rien n'est envoyé.")
    bad = 0
    for k in KNOWN:
        if k.kind == "web":
            try:
                page, now = clusterdx.fetch(k.url, timeout=timeout * 2)
                spots, wrong = clusterdx.parse_page(page, now)
                print(f"  OK  {k.name:<12} {k.url}  {len(spots)} spots lisibles, {wrong} illisibles")
            except Exception as exc:
                bad += 1
                print(f"  --  {k.name:<12} {k.url}  {exc}")
            continue
        try:
            with socket.create_connection((k.host, k.port), timeout=timeout) as s:
                s.settimeout(4)
                try:
                    data = s.recv(400)
                except socket.timeout:
                    data = b""
            text = " ".join(data.decode("latin-1", "replace").split())[:70]
            print(f"  OK  {k.name:<12} {k.host}:{k.port:<5} {text}")
        except OSError as exc:
            bad += 1
            print(f"  --  {k.name:<12} {k.host}:{k.port:<5} {exc}")
    return 0 if bad == 0 else 1


async def run(args: argparse.Namespace, call: str, sources: list[Source]) -> int:
    cty_path = Path(args.cty) if args.cty else default_cty_path()
    if args.maj_cty or (not args.cty and ctymod.is_stale(cty_path)):
        try:
            await asyncio.to_thread(ctymod.download, cty_path)
            print(f"cty.dat mis à jour : {cty_path}")
        except Exception as exc:                         # sans cty.dat, on continue sans pays
            print(f"Mise à jour de cty.dat impossible : {exc}")
    table, problem = ctymod.load_or_empty(cty_path)
    if problem:
        print(f"ATTENTION : {problem}" + ("; filtre de continent INOPÉRANT" if args.continent else ""))
    flt = SpotFilter(bands=frozenset(args.bandes or ()), modes=frozenset(m.upper() for m in args.modes or ()),
                     continents=frozenset(c.upper() for c in args.continent or ()),
                     blacklist=frozenset(c.upper() for c in args.liste_noire or ()))
    cache = SpotCache(table, flt, ttl_s={"cluster": args.duree_vie * 60.0, "cb": args.duree_vie * 60.0,
                                                     "rbn": args.duree_vie_rbn * 60.0})

    def on_spot(s: Spot, new: bool) -> None:
        if new or args.tout:
            print(format_spot(s, new), flush=True)

    def on_state(src: Source, st: SourceState) -> None:
        extra = f" (nouvel essai dans {st.retry_in_s:.0f} s)" if st.retry_in_s else ""
        why = f" — {st.last_message}" if st.state != CONNECTED and st.last_message else ""
        kind = f" [{st.cluster_type}]" if st.state == CONNECTED and st.cluster_type else ""
        print(f"-- {time.strftime('%H:%M:%S')}  {src.name} ({src.address}) : {st.state}{kind}{why}{extra}",
              flush=True)

    engine = Engine(cache, on_spot=on_spot)
    feed = Feed(sources, call, engine.handle_line, on_web=engine.handle_web, on_state=on_state)
    start = time.monotonic()
    task = asyncio.ensure_future(feed.run())
    try:
        while not task.done():
            left = args.duree - (time.monotonic() - start) if args.duree else 60.0
            await asyncio.wait({task}, timeout=max(0.0, min(60.0, left)))
            cache.expire(time.monotonic())
            print(status_line(engine, feed), flush=True)
            if args.duree and time.monotonic() - start >= args.duree:
                break
    finally:
        feed.stop()
        await asyncio.wait({task}, timeout=5.0)
        print("\n".join(summary(engine, feed, time.monotonic() - start)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trxstation.cluster",
                                 description="Essai autonome du cluster DX (lecture seule)")
    ap.add_argument("--indicatif", help="VOTRE indicatif (obligatoire pour se connecter)")
    ap.add_argument("--source", type=_hostport, action="append", metavar="HÔTE:PORT",
                    help="cluster telnet, dans l'ordre de priorité (répétable)")
    ap.add_argument("--connu", action="append", metavar="NOM", help="serveur de la liste (--serveurs)")
    ap.add_argument("--rbn", action="store_true", help="ajouter le RBN CW (beaucoup de spots)")
    ap.add_argument("--cb", action="store_true",
                    help="ajouter le Cluster DX des cibistes (clusterdx.org, 11 m) ; seul : --connu clusterdx")
    ap.add_argument("--mot-de-passe", action="store_true", help="demander un mot de passe pour la 1re source")
    ap.add_argument("--bandes", nargs="+", choices=BAND_NAMES, metavar="BANDE")
    ap.add_argument("--modes", nargs="+", type=str.upper, choices=MODES, metavar="MODE")
    ap.add_argument("--continent", nargs="+", type=str.upper, choices=CONTINENTS, metavar="CONT",
                    help="continent du SPOTTEUR (EU = ce qui est entendu en Europe)")
    ap.add_argument("--liste-noire", nargs="+", metavar="INDICATIF", help="« XX* » = préfixe")
    ap.add_argument("--duree-vie", type=float, default=15.0, help="minutes, spots de cluster (15)")
    ap.add_argument("--duree-vie-rbn", type=float, default=10.0, help="minutes, spots RBN (10)")
    ap.add_argument("--duree", type=float, default=0.0, help="secondes d'essai (0 = jusqu'à Ctrl+C)")
    ap.add_argument("--cty", help="fichier cty.dat (sinon dossier d'état de la station, mis à jour chaque semaine)")
    ap.add_argument("--maj-cty", action="store_true", help="télécharger cty.dat maintenant")
    ap.add_argument("--tout", action="store_true", help="afficher aussi les mises à jour (doublons)")
    ap.add_argument("--serveurs", action="store_true", help="lister les serveurs proposés")
    ap.add_argument("--verifier-serveurs", action="store_true", help="vérifier qu'ils répondent")
    args = ap.parse_args(argv)

    if args.serveurs:
        print(f"Serveurs proposés (vérifiés le {VERIFIED_ON}) :")
        for k in KNOWN:
            print(f"  {k.name:<12} {k.address:<31} {k.software:<9} {k.where}")
        return 0
    if args.verifier_serveurs:
        return verify_servers()
    if args.duree_vie <= 0 or args.duree_vie_rbn <= 0:
        print("les durées de vie doivent être positives", file=sys.stderr)
        return 2
    sources = build_sources(args)
    if not sources:
        print("aucune source", file=sys.stderr)
        return 2
    call = ""
    if any(s.kind != "web" for s in sources):              # la page des cibistes ne demande aucun indicatif
        try:
            call = check_own_call(args.indicatif)
        except ValueError as exc:
            print(f"{exc}. Exemple : --indicatif F4XXX", file=sys.stderr)
            return 2
    try:
        return asyncio.run(run(args, call, sources))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
