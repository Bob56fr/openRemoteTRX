"""Transport WebRTC (aiortc) : fine couche au-dessus de la logique testée (session, porte, hub).

Une connexion par client :
  * piste audio sortante  : le son reçu du poste (RxHub -> RxTrack) ;
  * piste audio entrante  : le micro du client -> porte d'émission (jetée hors TX ou hors propriétaire) ;
  * canal de données « control » : commandes JSON <-> ControlSession.
Le jeton est vérifié AVANT la création de la connexion (server.py). Un client qui se reconnecte
remplace l'ancienne connexion (ce qui coupe l'émission s'il l'avait).

Nécessite : pip install -e ".[audio]"   (aiortc, aiohttp, sounddevice).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from fractions import Fraction

import av
from aiortc import MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from ..audio.pcm import FRAME_SAMPLES, SAMPLE_RATE, FrameAssembler
from .session import ControlSession

log = logging.getLogger(__name__)
CONTROL_LABEL = "control"


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
    """Son reçu du poste, vers UN client."""

    kind = "audio"

    def __init__(self, hub):
        super().__init__()
        self._hub, self._queue, self._pts = hub, hub.subscribe(), 0

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        pcm = await self._queue.get()
        frame = pcm_to_frame(pcm)
        frame.pts, frame.time_base = self._pts, Fraction(1, SAMPLE_RATE)
        self._pts += FRAME_SAMPLES
        return frame

    def stop(self) -> None:
        self._hub.unsubscribe(self._queue)
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


@dataclass
class _Peer:
    client_id: str
    pc: RTCPeerConnection
    session: ControlSession | None = None
    rx_track: RxTrack | None = None
    tx_task: asyncio.Task | None = None
    closed: bool = False


class PeerManager:
    def __init__(self, ctrl, link, pipeline, capabilities, *, max_peers: int = 4, peer_timeout_s: float = 20.0,
                 ice_servers: list[str] | None = None, memories=None, layouts=None):
        self.ctrl, self.link, self.pipeline, self.capabilities = ctrl, link, pipeline, capabilities
        self.memories = memories
        self.layouts = layouts
        self.ice_servers = ice_servers          # None : défaut d'aiortc ; [] : aucun (réseau local / VPN) ; sinon la liste
        self.max_peers, self.peer_timeout_s = max_peers, peer_timeout_s
        self.peers: dict[str, _Peer] = {}
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def handle_offer(self, client_id: str, sdp: str, sdp_type: str) -> dict:
        await self.close_peer(client_id)                        # reconnexion : l'ancienne connexion est remplacée
        if len(self.peers) >= self.max_peers:
            raise PeerLimitError(f"{self.max_peers} connexions simultanées au maximum")
        configuration = None if self.ice_servers is None else RTCConfiguration(
            iceServers=[RTCIceServer(urls=url) for url in self.ice_servers])
        pc = RTCPeerConnection(configuration)
        peer = _Peer(client_id, pc)
        self.peers[client_id] = peer

        @pc.on("datachannel")
        def on_datachannel(channel) -> None:
            if channel.label != CONTROL_LABEL or peer.session is not None:
                return                                          # un seul canal de contrôle par client

            def send(message: dict) -> None:
                if channel.readyState == "open":
                    channel.send(json.dumps(message, separators=(",", ":")))

            session = ControlSession(client_id, self.ctrl, self.link, self.pipeline, self.capabilities, send,
                                     memories=self.memories, layouts=self.layouts)
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
                peer.tx_task = self._spawn(receive_tx_audio(track, client_id, self.pipeline.gate))

        @pc.on("connectionstatechange")
        async def on_state() -> None:
            if pc.connectionState in ("failed", "closed"):
                await self.close_peer(client_id, peer)

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))
            peer.rx_track = RxTrack(self.pipeline.hub)
            pc.addTrack(peer.rx_track)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
        except Exception:
            await self.close_peer(client_id, peer)
            raise
        self._spawn(self._expire_if_not_connected(client_id, peer))
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    async def _expire_if_not_connected(self, client_id: str, peer: _Peer) -> None:
        await asyncio.sleep(self.peer_timeout_s)
        if not peer.closed and peer.pc.connectionState != "connected":
            log.warning("connexion de %s jamais établie : abandon", client_id)
            await self.close_peer(client_id, peer)

    async def close_peer(self, client_id: str, peer: _Peer | None = None) -> None:
        peer = peer or self.peers.get(client_id)
        if peer is None or peer.closed:
            return
        peer.closed = True
        if self.peers.get(client_id) is peer:
            del self.peers[client_id]
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
