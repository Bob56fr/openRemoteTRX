# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 RF-DIY.COM
"""Transport WebRTC (aiortc) : fine couche au-dessus de la logique testée (session, porte, hub).

Une connexion par client :
  * piste audio sortante  : le son reçu du poste (RxHub -> RxTrack) ;
  * piste audio entrante  : le micro du client -> porte d'émission (jetée hors TX ou hors propriétaire) ;
  * canal de données « control » : commandes JSON <-> ControlSession ;
  * canal de données « spectrum » (ouvert par le client, non ordonné, sans renvoi) : balayages du spectre HF
    en binaire (spectrum/frame.py), du serveur vers le client seulement ; ce qui arrive dessus est ignoré.
    Rien n'y part tant que le client n'affiche pas la vue HF (commande `spectrum_watch`).
Le jeton est vérifié AVANT la création de la connexion (server.py). Un client qui se reconnecte
remplace l'ancienne connexion (ce qui coupe l'émission s'il l'avait).
Visiteur (rôle listener, access.py) : admis selon les quotas et la présence d'un opérateur ; son micro éventuel est
consommé et jeté (jamais vers la porte d'émission) ; son reçu est remplacé par du silence hors [[bands]].

Nécessite : pip install -e ".[audio]"   (aiortc, aiohttp, sounddevice).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from fractions import Fraction

import av
from aiortc import MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from ...spectrum.frame import SpectrumFanout
from ..audio.listeners import ListenerMix, TxTap
from ..audio.pcm import FRAME_SAMPLES, SAMPLE_RATE, FrameAssembler
from .access import LISTENER, OPERATOR
from .session import ControlSession

log = logging.getLogger(__name__)
CONTROL_LABEL = "control"
SPECTRUM_LABEL = "spectrum"


class PeerLimitError(Exception):
    pass


def pcm_to_frame(pcm: bytes) -> av.AudioFrame:
    frame = av.AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
    plane = frame.planes[0]
    plane.update(pcm.ljust(plane.buffer_size, b"\x00"))        # le tampon peut être plus grand que nécessaire
    frame.sample_rate = SAMPLE_RATE
    return frame


def frame_to_pcm(frame: av.AudioFrame) -> bytes:
    return bytes(frame.planes[0])[: frame.samples * 2]          # mono s16 : 2 octets par échantillon


def as_list(result) -> list:
    """AudioResampler.resample renvoie une liste (PyAV récent) ou une trame / None (ancien)."""
    if result is None:
        return []
    return list(result) if isinstance(result, (list, tuple)) else [result]


class RxTrack(MediaStreamTrack):
    """Son reçu du poste, vers UN client. `mix` (visiteur, audio/listeners.py) : voix de l'opérateur pendant ses
    émissions, silence hors bandes ; même cadence (horloge : le son du poste)."""

    kind = "audio"

    def __init__(self, hub, mix=None):
        super().__init__()
        self._hub, self._queue, self._pts = hub, hub.subscribe(), 0
        self._mix = mix

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        pcm = await self._queue.get()
        if self._mix is not None:
            pcm = self._mix.next(pcm)
        frame = pcm_to_frame(pcm)
        frame.pts, frame.time_base = self._pts, Fraction(1, SAMPLE_RATE)
        self._pts += FRAME_SAMPLES
        return frame

    def stop(self) -> None:
        self._hub.unsubscribe(self._queue)
        if self._mix is not None:
            self._mix.close()
        super().stop()


async def receive_tx_audio(track, client_id: str, gate) -> None:
    """Micro d'un client -> porte d'émission. Consomme toujours la piste (sinon elle s'engorge)."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    assembler = FrameAssembler()
    try:
        while True:
            frame = await track.recv()
            for out in as_list(resampler.resample(frame)):
                for chunk in assembler.feed(frame_to_pcm(out)):
                    gate.push(client_id, chunk)
    except MediaStreamError:
        pass


async def drain_audio(track) -> None:
    """Micro d'un visiteur : lu (sinon la piste s'engorge) et jeté, JAMAIS vers la porte d'émission."""
    try:
        while True:
            await track.recv()
    except MediaStreamError:
        pass


@dataclass
class _Peer:
    client_id: str
    pc: RTCPeerConnection
    role: str = OPERATOR
    session: ControlSession | None = None
    rx_track: RxTrack | None = None
    tx_task: asyncio.Task | None = None
    spectrum_channel: object | None = None
    closed: bool = False


class PeerManager:
    def __init__(self, ctrl, link, pipeline, capabilities, *, max_peers: int = 4, peer_timeout_s: float = 20.0,
                 ice_servers: list[str] | None = None, memories=None, layouts=None, spectrum=None, reports=None,
                 access=None, muted=None, alert=None):
        self.reports = reports                  # ReportStore : rapports de problème envoyés par la page
        self.access = access                    # AccessControl : rôles, quotas, présence ; None = tout client est opérateur
        self.listener_muted = muted             # () -> bool : silence pour les visiteurs (réception hors bandes)
        self.alert = alert                      # (titre, message) -> None : alerte ntfy
        self.ctrl, self.link, self.pipeline, self.capabilities = ctrl, link, pipeline, capabilities
        self.spectrum = spectrum                # SpectrumService : son état est joint aux messages « state »
        self.fanout = SpectrumFanout(spectrum.cfg.max_fps if spectrum is not None else 10, time.monotonic)
        if spectrum is not None:
            spectrum.add_listener(self.fanout.publish)
        self.memories = memories
        self.layouts = layouts
        self.ice_servers = ice_servers          # None : défaut d'aiortc ; [] : aucun (réseau local / VPN) ; sinon la liste
        self.max_peers, self.peer_timeout_s = max_peers, peer_timeout_s
        self.on_hf_view = None                  # (session, ouverte) -> None ; posé par gateway/main (ModuleBridge.replay)
        self.peers: dict[str, _Peer] = {}
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def handle_offer(self, client_id: str, sdp: str, sdp_type: str, source: str = "") -> dict:
        """AccessRefused (access.py) : compte désactivé, quota atteint, opérateur absent..."""
        await self.close_peer(client_id)                        # reconnexion : l'ancienne connexion est remplacée
        if self.access is not None:
            role = self.access.admit(client_id, source).role    # SANS attente jusqu'à l'enregistrement : pas de course
        elif len(self.peers) >= self.max_peers:
            raise PeerLimitError(f"{self.max_peers} connexions simultanées au maximum")
        else:
            role = OPERATOR
        configuration = None if self.ice_servers is None else RTCConfiguration(
            iceServers=[RTCIceServer(urls=url) for url in self.ice_servers])
        try:
            pc = RTCPeerConnection(configuration)
        except Exception:
            if self.access is not None:
                self.access.closed(client_id)                   # admis mais jamais créé : la place est rendue
            raise
        peer = _Peer(client_id, pc, role)
        self.peers[client_id] = peer

        @pc.on("datachannel")
        def on_datachannel(channel) -> None:
            if channel.label == SPECTRUM_LABEL:
                self._attach_spectrum(client_id, peer, channel)
                return
            if channel.label != CONTROL_LABEL or peer.session is not None:
                return                                          # un seul canal de contrôle par client

            def send(message: dict) -> None:
                if channel.readyState == "open":
                    channel.send(json.dumps(message, separators=(",", ":")))

            session = ControlSession(client_id, self.ctrl, self.link, self.pipeline, self.capabilities, send,
                                     memories=self.memories, layouts=self.layouts, spectrum=self.spectrum,
                                     spectrum_watch=lambda on: self._watch_spectrum(client_id, peer, on),
                                     reports=self.reports, role=role, access=self.access, alert=self.alert,
                                     kick_listener=self._kick_listener,
                                     disconnect=lambda reason: self._spawn(self.kick(client_id, reason, peer)))
            session.on_hf_view = self.on_hf_view        # vue HF ouverte : messages retenus des modules rejoués
            peer.session = session

            @channel.on("message")
            def on_message(message) -> None:
                self._spawn(session.on_message(message))

            @channel.on("close")
            def on_close() -> None:
                self._spawn(self.close_peer(client_id, peer))

            self._spawn(session.start())

        @pc.on("track")
        def on_track(track) -> None:
            if track.kind == "audio" and peer.tx_task is None:
                peer.tx_task = self._spawn(drain_audio(track) if role == LISTENER
                                           else receive_tx_audio(track, client_id, self.pipeline.gate))

        @pc.on("connectionstatechange")
        async def on_state() -> None:
            if pc.connectionState in ("failed", "closed"):
                await self.close_peer(client_id, peer)

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))
            peer.rx_track = RxTrack(self.pipeline.hub, self._listener_mix() if role == LISTENER else None)
            pc.addTrack(peer.rx_track)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
        except Exception:
            await self.close_peer(client_id, peer)
            raise
        self._spawn(self._expire_if_not_connected(client_id, peer))
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    def _attach_spectrum(self, client_id: str, peer: _Peer, channel) -> None:
        """Un seul canal « spectrum » par client ; rien n'y est lu."""
        if peer.spectrum_channel is not None or self.spectrum is None:
            return
        peer.spectrum_channel = channel

        def send(frame: bytes) -> None:
            if channel.readyState != "open":
                raise ConnectionError("canal du spectre fermé")
            channel.send(frame)

        access = self.access
        cap = (lambda: access.settings.listener_spectrum_fps) if peer.role == LISTENER and access is not None else None

        def subscribe() -> None:
            if not peer.closed:
                self.fanout.add(client_id, send, lambda: channel.bufferedAmount, cap)   # visiteur : cadence plafonnée

        if channel.readyState == "open":
            subscribe()
        else:
            channel.on("open", subscribe)
        channel.on("close", lambda: self.fanout.remove(client_id, send))

    def _watch_spectrum(self, client_id: str, peer: _Peer, on: bool) -> None:
        """Balayages envoyés seulement pendant que ce client affiche la vue HF (connexion encore active)."""
        if not peer.closed and self.peers.get(client_id) is peer:
            self.fanout.watch(client_id, on)
            retry = getattr(self.spectrum, "retry_now", None)
            if on and retry is not None:
                retry()                            # spectre en panne passagère : nouvel essai sans attendre une minute

    async def _expire_if_not_connected(self, client_id: str, peer: _Peer) -> None:
        await asyncio.sleep(self.peer_timeout_s)
        if not peer.closed and peer.pc.connectionState != "connected":
            log.warning("connexion de %s jamais établie : abandon", client_id)
            await self.close_peer(client_id, peer)

    async def kick(self, client_id: str, reason: str, peer: _Peer | None = None, message: str = "") -> None:
        """Ferme une connexion en disant pourquoi (message « bye » avant la fermeture)."""
        peer = peer or self.peers.get(client_id)
        if peer is None or peer.closed:
            return
        log.warning("connexion de %s (%s) fermée par la station : %s", client_id, peer.role, reason)
        if peer.session is not None:
            peer.session.bye(reason, message)
            await asyncio.sleep(0.3)                            # le temps que le message parte avant la fermeture
        await self.close_peer(client_id, peer)

    def _kick_listener(self, client_id: str) -> bool:
        """« Déconnecter » demandé par un OPÉRATEUR : un visiteur connecté seulement."""
        peer = self.peers.get(client_id)
        if peer is None or peer.role != LISTENER:
            return False
        self._spawn(self.kick(client_id, "kicked", peer))
        return True

    def _listener_mix(self) -> ListenerMix:
        tap = getattr(self.pipeline, "tx_tap", None) or TxTap()        # banc d'essai sans copie : son du poste seul
        return ListenerMix(tap, self.listener_muted)

    def listener_ids(self) -> list[str]:
        return [cid for cid, peer in self.peers.items() if peer.role == LISTENER]

    async def close_peer(self, client_id: str, peer: _Peer | None = None) -> None:
        peer = peer or self.peers.get(client_id)
        if peer is None or peer.closed:
            return
        peer.closed = True
        if self.peers.get(client_id) is peer:
            del self.peers[client_id]
            self.fanout.remove(client_id)
            if self.access is not None:
                self.access.closed(client_id)                   # dernier opérateur parti : attente des visiteurs
        if peer.session is not None:
            await peer.session.close()                          # coupe l'émission si ce client la détenait
        if peer.tx_task is not None:
            peer.tx_task.cancel()
        if peer.rx_track is not None:
            peer.rx_track.stop()
        try:
            await peer.pc.close()
        except asyncio.InvalidStateError:
            pass                                                # aiortc : fermeture simultanée, sans conséquence

    async def close_all(self) -> None:
        for client_id in list(self.peers):
            await self.close_peer(client_id)
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
