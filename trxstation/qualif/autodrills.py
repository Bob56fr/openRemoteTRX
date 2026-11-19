# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Essais AUTOMATIQUES de la valise de qualification (lot T2, docs/qualification-terrain-cahier-des-charges.md § 5.4).

Un CLIENT AUTOMATIQUE (le faux client WebRTC des tests, `devtools/fake_client.py`) se connecte à la station avec un
compte opérateur et joue STOP, battements arrêtés, connexion coupée, TOT et fréquence hors bande ; l'observateur en
lecture seule de la valise chronomètre le retour en réception relu sur le poste.

SÉCURITÉ :
- aucune commande n'est envoyée au poste par cet outil : il ne parle qu'à la PASSERELLE, comme la page ou
  l'application, et toutes ses sécurités s'appliquent (verrou, battements, TOT, bandes, porte audio) ;
- le micro du client automatique est MUET (aucun son n'est émis, la porte reste celle de la station) ;
- chaque essai qui émet exige le mot de confirmation (EMETTRE) tapé par l'OPÉRATEUR ;
- quoi qu'il arrive (erreur, Ctrl+C, essai raté), le client envoie « stop » puis ferme sa connexion, et l'outil
  vérifie sur le poste le retour en réception ; sinon : alerte « COUPE LE POSTE ».
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Callable

from ..answers import typed
from ..i18n import tool_translator
from .bus import CHOICE, SECRET, ask_typed, ask_word, bus_of
from .terrain import Drill, Observer, Session, _iso, _redactor, drill_choices, journal_lines
from .texts import _t

AUTO_DRILLS: tuple[Drill, ...] = (
    Drill("auto_stop", "auto_stop", optional=True, bound_s=0.5),
    Drill("auto_heartbeat", "auto_heartbeat", optional=True, bound_s=3.0),
    Drill("auto_disconnect", "auto_disconnect", optional=True, bound_s=3.0),
    Drill("auto_out_of_band", "auto_out_of_band", optional=True),
    Drill("auto_tot", "auto_tot", optional=True, bound_s=2.0),
    # Étape 282 (accord de l'utilisateur, 2026-11-19) : ce que l'humain faisait à la main, la valise le fait elle-même
    Drill("auto_dashboard_stop", "auto_dashboard_stop", optional=True, bound_s=1.0),   # STOP TX du tableau de bord
    Drill("auto_station_stop", "auto_station_stop", optional=True, bound_s=10.0),      # station arrêtée en émission
    Drill("auto_startup", "auto_startup", optional=True),                              # démarrage de la station
)
NO_CLIENT = ("auto_startup",)          # essais sans client automatique (aucune émission demandée)
STARTUP_WATCH_S = 40.0                 # démarrage observé (rigctld, passerelle, connexion au poste)
STATION_WAIT_S = 60.0
HEARTBEAT_S = 0.5            # comme l'application
TX_WAIT_S = 5.0              # délai pour voir l'émission demandée sur le poste
HOLD_S = 2.0                 # émission tenue avant l'action
OUT_OF_BAND_MARGIN_HZ = 50_000
UNREADABLE = "PTT illisible (station d'essai ou rigctld arrêtés ?) : essai non joué, rien n'a été demandé"
COOLDOWN_TRIES = 3           # « cooldown » = anti-rebond de la station (rekey_cooldown_s) : on attend, jamais on force
COOLDOWN_WAIT_S = 1.5


class AutoDrillError(RuntimeError):
    pass


def station_url(cfg) -> str:
    net = cfg.network
    host = net.gateway_bind if net.gateway_bind not in ("0.0.0.0", "::", "") else "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"{'https' if net.tls_cert else 'http'}://{host}:{net.gateway_port}"


def pinned_ssl(cfg):
    """Certificat de la passerelle ÉPINGLÉ (empreinte SHA-256 du premier certificat du fichier) ; None sans TLS."""
    if not cfg.network.tls_cert:
        return None
    import aiohttp
    from ..gateway.api.tls import certificate_fingerprint
    digest = bytes.fromhex(certificate_fingerprint(cfg.network.tls_cert).replace(":", ""))
    return aiohttp.Fingerprint(digest)


def out_of_band_frequency(cfg) -> int | None:
    """Une fréquence de réception proche d'une bande autorisée mais hors de TOUTES (None : pas de bandes, ou pas de
    contrôle des bandes par la station : l'essai est sans objet)."""
    if not cfg.safety.enforce_bands or not cfg.bands:
        return None
    ranges = [(round(b.low_mhz * 1e6), round(b.high_mhz * 1e6)) for b in cfg.bands]
    for low, high in sorted(ranges):
        for candidate in (low - OUT_OF_BAND_MARGIN_HZ, high + OUT_OF_BAND_MARGIN_HZ):
            if candidate > 100_000 and not any(lo <= candidate <= hi for lo, hi in ranges):
                return candidate
    return None


def _last(observer: Observer) -> int | None:
    return observer.events[-1][1] if observer.events else None


async def _wait_value(observer: Observer, value: int, timeout: float, since: float = 0.0) -> float | None:
    """Instant du premier changement vers `value` après `since` (ou de l'état courant s'il y est déjà)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for ts, v in observer.events:
            if v == value and ts >= since:
                return ts
        if since and _last(observer) == value and observer.events[-1][0] < since:
            return since
        await asyncio.sleep(0.02)
    return None


async def _wait_rx(observer: Observer, timeout: float) -> float | None:
    """Attend que le poste soit relu en réception ; instant du retour, None au-delà du délai."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _last(observer) == 0:
            return observer.events[-1][0]
        await asyncio.sleep(0.02)
    return None


def _refusal(result: dict) -> str:
    return str(result.get("reason") or result.get("detail") or result.get("ptt") or "")


def _watch_ptt(observer: Observer, ask) -> None:
    """Mesure en direct pour la page (lot G2b) : le PTT que l'observateur RELIT déjà, rien d'autre."""
    bus = bus_of(ask)
    if bus is not None:
        observer.notify = lambda value: bus.measure("poste", {"ptt": None if value is None else bool(value)})


def _confirmed(answer: str | None) -> bool:
    word = tool_translator("hwtest")("word.emit")
    return typed(answer, word) or typed(answer, "EMETTRE")


async def play_auto(drill: Drill, session: Session, *, client_factory: Callable, host: str, port: int, cfg,
                    state_dir: Path, ask: Callable[[str], str] = input, out: Callable[[str], None] = print,
                    period: float = 0.2, actions: dict | None = None) -> dict:
    """`actions` (A6 à A8) : `dashboard_stop()` -> (ok, message) = STOP TX du tableau de bord (« T 0 », ne peut que
    couper) ; `station_control(start)` -> code ; `station_running()` -> bool ; `confirm_rx()` -> 0 / 1 / None =
    PTT relu par un rigctld de la valise, station arrêtée."""
    """Un essai automatique ; enregistré dans la session comme les essais à la main."""
    tot_s = float(cfg.safety.tot_s)
    out(_t(f"terrain.drill.{drill.id}.title"))
    out(_t(f"terrain.drill.{drill.id}.how", tot=f"{tot_s:.0f}"))
    out(_t("terrain.expected", text=_t(f"terrain.drill.{drill.id}.expected", tot=f"{tot_s:.0f}")))
    if drill.kind == "auto_out_of_band" and out_of_band_frequency(cfg) is None:
        out(_t("terrain.auto.no_bands"))
        return {}
    context = (_t(f"terrain.drill.{drill.id}.title").strip() + "\n"
               + _t(f"terrain.drill.{drill.id}.how", tot=f"{tot_s:.0f}").strip())
    no_client = drill.kind in NO_CLIENT
    if not no_client and not _confirmed(await asyncio.to_thread(ask_word, ask, _t("terrain.auto.confirm"), "EMETTRE",
                                                                context=context)):
        out(_t("terrain.auto.cancelled"))
        return {}
    if no_client and actions is None:
        out(_t("terrain.auto.no_actions"))
        return {}
    if not no_client and await Observer(host, port, period=period).read_once() is None:
        out(_t("terrain.unreadable"))                    # station d'essai arrêtée : rien n'est lancé ni enregistré
        return {}
    observer = Observer(host, port, period=period)
    _watch_ptt(observer, ask)
    stop = asyncio.Event()
    watch = asyncio.create_task(observer.run(stop))
    start = time.time()
    measured, reason, detail = "echec", "", {}
    client = None
    try:
        await asyncio.sleep(period * 2)
        if no_client:
            measured, reason, detail = await _startup(observer, actions)
        else:
            if _last(observer) is None:
                raise AutoDrillError(UNREADABLE)
            if _last(observer) != 0:
                raise AutoDrillError("le poste n'est pas en réception au départ : essai non joué")
            client = client_factory()
            await client.connect()
            measured, reason, detail = await _scenario(drill, client, observer, cfg, tot_s, actions)
    except AutoDrillError as exc:
        measured, reason = "non_mesure", str(exc)
    except Exception as exc:                     # noqa: BLE001 : toute erreur finit par la remise en réception
        measured, reason = "non_mesure", f"erreur : {exc!r}"
    finally:
        if client is not None:
            try:
                await asyncio.wait_for(client.command("stop"), 2.0)
            except Exception:                    # noqa: BLE001 : déjà fermé, ou station qui ne répond plus
                pass
            try:
                await asyncio.wait_for(client.close(), 5.0)
            except Exception:                    # noqa: BLE001
                pass
        back = await _wait_rx(observer, 5.0)
        end = time.time()
        stop.set()
        await watch
    if _last(observer) == 1:
        measured, reason = "echec", "LE POSTE EST RESTÉ EN ÉMISSION après l'essai"
        out(_t("terrain.auto.still_tx"))
    elif back is None and client is not None and not detail.get("verifie_par_la_valise"):
        # Émission demandée mais état final ILLISIBLE : on ne sait pas (jamais « resté en émission » sans l'avoir lu).
        measured, reason = "non_mesure", "état final du poste ILLISIBLE après l'essai : vérifier qu'il est en réception"
        out(_t("terrain.auto.unknown_end"))
    out(_t("terrain.measured", result=_t(f"terrain.result.{measured}"), reason=reason))
    record = {
        "id": drill.id, "kind": drill.kind, "optional": True, "played_by": "client automatique",
        "bound_s": drill.bound_s or None, "start": _iso(start), "end": _iso(end), "measures": detail,
        "measured": measured, "reason": reason, "declared_ok": None, "note": "", "result": measured,
        "observer": {"period_s": period, "reads": observer.reads, "unreadable": observer.failures,
                     "changes": [[_iso(ts), v] for ts, v in observer.events]},
        "journal": journal_lines(state_dir, start - 2, end + 2, _redactor()),
    }
    (session.folder / "essais").mkdir(exist_ok=True)
    (session.folder / "essais" / f"{drill.id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    session.drills[drill.id] = {k: record[k] for k in ("result", "measured", "reason", "declared_ok", "note")}
    session.save()
    out(_t("terrain.drill_saved", result=_t(f"terrain.result.{measured}")))
    bus = bus_of(ask)
    if bus is not None:
        bus.state(drill.id, measured, mesure=measured, raison=reason)
    return record


async def _transmit(client, observer: Observer) -> tuple[float, asyncio.Task]:
    """Prise d'émission par la passerelle (battements lancés) ; instant où le poste est VU en émission."""
    for _ in range(COOLDOWN_TRIES):
        asked = time.time()
        result = await client.command("toggle")
        if result.get("reason") != "cooldown":
            break
        await asyncio.sleep(COOLDOWN_WAIT_S)     # anti-rebond de la station après l'émission précédente (vu : A2)
    if not result.get("ok") or (result.get("ptt") or {}).get("state") != "TX":
        raise AutoDrillError(f"émission refusée par la station : {_refusal(result)}")
    beat = client.start_heartbeat(HEARTBEAT_S)
    seen = await _wait_value(observer, 1, TX_WAIT_S, since=asked - 0.5)
    if seen is None:
        raise AutoDrillError("émission acceptée par la station mais jamais vue sur le poste")
    return seen, beat


async def _wait_station(actions: dict, want: bool, timeout: float = STATION_WAIT_S) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if actions["station_running"]() == want:
            return True
        await asyncio.sleep(0.25)
    return False


async def _startup(observer: Observer, actions: dict) -> tuple[str, str, dict]:
    """A8 : station arrêtée (par la valise si besoin), puis DÉMARRÉE par la valise ; le PTT est relu dès que le
    rigctld de la station répond, pendant tout le démarrage. Aucune émission n'est demandée par personne."""
    if actions["station_running"]():
        if await asyncio.to_thread(actions["station_control"], False) != 0 or not await _wait_station(actions, False):
            raise AutoDrillError("la station n'a pas pu être arrêtée avant l'essai")
        await asyncio.sleep(2.0)
    start = time.time()
    if await asyncio.to_thread(actions["station_control"], True) != 0:
        raise AutoDrillError("démarrage de la station refusé")
    await asyncio.sleep(STARTUP_WATCH_S)
    seen = [(ts, v) for ts, v in observer.events if ts >= start]
    read = [v for _, v in seen if v in (0, 1)]
    first = next((ts for ts, v in seen if v in (0, 1)), None)
    running = actions["station_running"]()
    detail = {"observe_s": STARTUP_WATCH_S, "lectures": len(read), "station_demarree": running,
              "premiere_lecture_s": round(first - start, 1) if first else None}
    if 1 in read:
        return "echec", "le poste est passé en ÉMISSION pendant le démarrage de la station", detail
    if not read:
        return "non_mesure", f"PTT jamais lisible pendant les {STARTUP_WATCH_S:.0f} s du démarrage", detail
    if not running:
        return "non_mesure", "station pas démarrée au bout de l'observation", detail
    return "reussi", f"aucune émission pendant les {STARTUP_WATCH_S:.0f} s du démarrage (poste relu en réception " \
        f"dès {first - start:.1f} s)", detail


async def _station_stop(observer: Observer, actions: dict, action: float) -> tuple[str, str, dict]:
    """A7 : la valise ARRÊTE la station pendant l'émission du client ; son rigctld disparaît avec elle, donc le poste
    est relu ensuite par un rigctld de la valise (`confirm_rx`) ; s'il émettait encore : « T 0 » aussitôt."""
    if await asyncio.to_thread(actions["station_control"], False) != 0:
        raise AutoDrillError("arrêt de la station refusé")
    if not await _wait_station(actions, False):
        raise AutoDrillError("la station ne s'est pas arrêtée")
    stopped = time.time() - action
    value, confirmed = await asyncio.to_thread(actions["confirm_rx"])
    detail = {"arret_s": round(stopped, 3), "relu_par_la_valise": value, "verifie_par_la_valise": True}
    if value == 1:
        return "echec", "POSTE EN ÉMISSION après l'arrêt de la station (coupé ensuite par la valise)", detail
    if value is None:
        return "non_mesure", "poste illisible après l'arrêt de la station", detail
    after = (confirmed or time.time()) - action
    return "reussi", f"station arrêtée en {stopped:.1f} s, poste relu en RÉCEPTION {after:.1f} s après l'ordre", detail


async def _scenario(drill: Drill, client, observer: Observer, cfg, tot_s: float,
                    actions: dict | None = None) -> tuple[str, str, dict]:
    kind = drill.kind
    if kind in ("auto_dashboard_stop", "auto_station_stop") and actions is None:
        raise AutoDrillError("essai réservé à la valise (actions de la station absentes)")
    if kind == "auto_out_of_band":
        state = (client.state or {}).get("rig") or {}
        original = state.get("frequency_hz")
        target = out_of_band_frequency(cfg)
        moved = await client.command("set_frequency", hz=target)
        if not moved.get("ok"):
            raise AutoDrillError(f"fréquence hors bande refusée par la station : {_refusal(moved)}")
        await asyncio.sleep(1.0)
        try:
            asked = time.time()
            result = await client.command("toggle")
            await asyncio.sleep(1.5)
            tx = any(v == 1 and ts >= asked for ts, v in observer.events)
            if result.get("ok") and (result.get("ptt") or {}).get("state") == "TX":
                tx = True
        finally:
            await client.command("stop")
            await asyncio.sleep(0.5)
            if original:
                await client.command("set_frequency", hz=int(original))
        detail = {"frequence_hz": target, "refus": _refusal(result), "emission_vue": tx}
        if tx:
            return "echec", f"émission ACCEPTÉE sur {target} Hz hors des bandes", detail
        return "reussi", f"émission refusée sur {target} Hz ({_refusal(result) or 'refus'}), aucune émission vue", detail
    tx_at, beat = await _transmit(client, observer)
    if kind == "auto_tot":
        back = await _wait_value(observer, 0, tot_s + 15.0, since=tx_at)
        if back is None:
            return "echec", f"pas de retour en réception {tot_s + 15:.0f} s après la prise", {}
        duration = back - tx_at
        ok = abs(duration - tot_s) <= drill.bound_s
        return ("reussi" if ok else "echec"), f"émission coupée après {duration:.1f} s (TOT {tot_s:.0f} s ± " \
            f"{drill.bound_s:.0f})", {"duree_s": round(duration, 3)}
    await asyncio.sleep(HOLD_S)
    action = time.time()
    if kind == "auto_station_stop":
        return await _station_stop(observer, actions, action)
    if kind == "auto_dashboard_stop":
        ok, message = await asyncio.to_thread(actions["dashboard_stop"])     # même code que le bouton STOP TX
        if not ok:
            raise AutoDrillError(f"STOP TX du tableau de bord sans effet relu : {message}")
    elif kind == "auto_stop":
        await client.command("stop")
    elif kind == "auto_heartbeat":
        beat.cancel()
    elif kind == "auto_disconnect":
        await client.close()
    back = await _wait_value(observer, 0, drill.bound_s + 5.0, since=action)
    if back is None:
        return "echec", f"pas de retour en réception {drill.bound_s + 5:.0f} s après l'action", {}
    delay = max(0.0, back - action)
    ok = delay <= drill.bound_s + observer.period
    return ("reussi" if ok else "echec"), f"retour en réception {delay:.2f} s après l'action (attendu : {drill.bound_s:.1f} s au plus)", \
        {"delai_s": round(delay, 3)}


def make_factory(cfg, client_id: str, password: str) -> Callable:
    from ..devtools.fake_client import FakeClient, ToneTrack
    url, ssl = station_url(cfg), pinned_ssl(cfg)
    return lambda: FakeClient(url, client_id, password, track=ToneTrack(active=False), ssl=ssl)


PASSWORD_FILE = "valise.pw"     # mot de passe du compte de la valise, à côté de sa station.toml (dossier de qualification)


def operator_factory(cfg, *, ask: Callable[[str], str], out: Callable[[str], None],
                     factory: Callable[[str, str], Callable] | None = None,
                     secret: Callable[[str], str] | None = None,
                     password_file: Path | None = None) -> Callable | None:
    """Compte opérateur des essais automatiques (demandé une fois par session de la valise) ; None si aucun.

    Compte et mot de passe VÉRIFIÉS tout de suite contre station.toml (essai du 2026-11-18 : un compte faux
    donnait « HTTP 401 » à CHAQUE essai, notés « non mesuré », EMETTRE redemandé pour rien). Trois essais au plus."""
    from ..passwords import verify_password
    out(_t("terrain.auto.intro"))
    operators = {c.id: c.password_hash for c in getattr(cfg, "clients", []) or []
                 if getattr(c, "role", "operator") == "operator" and c.password_hash}
    if not operators:
        _tell(ask, out, _t("terrain.auto.no_account"))
        return None
    factory_for = factory or (lambda cid, pw: make_factory(cfg, cid, pw))
    # Dossier de qualification : son mot de passe est dans valise.pw ; s'il ouvre un compte opérateur, rien à taper.
    if password_file is not None and password_file.is_file():
        try:
            stored = password_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            stored = ""
        for cid, hashed in operators.items():
            if stored and verify_password(stored, hashed):
                out(_t("terrain.auto.account_file", account=cid, file=password_file.name))
                return factory_for(cid, stored)
    prompt = _t("terrain.auto.password")
    if secret is None and bus_of(ask) is not None:    # valise : champ masqué de la page ou getpass du terminal
        secret = lambda p: ask_typed(ask, p, SECRET)      # noqa: E731
    if secret is None:
        from .. import formhint
        if formhint.enabled():                    # console web : champ masqué de la page
            formhint.emit("password", prompt.strip(), prompt)
            secret = input
        else:
            import getpass
            secret = getpass.getpass
    choices = [{"cle": cid, "texte": cid} for cid in operators] + [{"cle": "", "libelle": "annuler"}]
    for _ in range(3):
        client_id = ask_typed(ask, _t("terrain.auto.account_choice", accounts=", ".join(operators)), CHOICE,
                              choices=choices).strip()
        if not client_id:
            return None
        if client_id not in operators:
            _tell(ask, out, _t("terrain.auto.unknown_account", account=client_id, accounts=", ".join(operators)))
            continue
        password = secret(prompt)
        if not password:
            return None
        if verify_password(password, operators[client_id]):
            out(_t("terrain.auto.account_ok", account=client_id))
            return factory_for(client_id, password)
        _tell(ask, out, _t("terrain.auto.bad_password", account=client_id))
    return None


def _tell(ask, out: Callable[[str], None], text: str) -> None:
    """Refus : ligne du journal et avis bien visible dans la page de la valise."""
    out(text)
    bus = bus_of(ask)
    if bus is not None:
        bus.publish("avis", texte=text.strip())


def auto_menu(session: Session, cfg, state_dir: Path, *, ask: Callable[[str], str], out: Callable[[str], None],
              factory: Callable[[str, str], Callable] | None = None, secret: Callable[[str], str] | None = None,
              client_factory: Callable | None = None) -> Callable | None:
    """Compte opérateur demandé une fois (sauf `client_factory` déjà connu), puis essais au choix ; chaque émission
    confirmée par EMETTRE. Renvoie le client automatique (la valise le garde pour ses tuiles)."""
    if client_factory is None:
        client_factory = operator_factory(cfg, ask=ask, out=out, factory=factory, secret=secret)
    if client_factory is None:
        return None
    while True:
        for n, d in enumerate(AUTO_DRILLS, 1):
            r = session.drills.get(d.id, {}).get("result")
            out(f"  {n}  {_t(f'terrain.drill.{d.id}.title').strip()}  [{_t('terrain.result.' + r) if r else '-'}]")
        choice = ask_typed(ask, _t("terrain.drills_choice"), CHOICE,
                           choices=drill_choices(session, AUTO_DRILLS)).strip().lower()
        if choice in ("r", "q", ""):
            return client_factory
        if choice == "t":
            todo = [d for d in AUTO_DRILLS if d.id not in session.drills]
        elif choice.isdigit() and 1 <= int(choice) <= len(AUTO_DRILLS):
            todo = [AUTO_DRILLS[int(choice) - 1]]
        else:
            continue
        for d in todo:
            asyncio.run(play_auto(d, session, client_factory=client_factory, host=cfg.network.rigctld_host,
                                  port=cfg.network.rigctld_port, cfg=cfg, state_dir=state_dir, ask=ask, out=out))
