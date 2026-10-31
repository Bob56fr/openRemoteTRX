// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.media.AudioAttributes
import java.nio.ByteBuffer
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
import org.webrtc.AudioTrackSink
import org.webrtc.DataChannel
import org.webrtc.ExternalAudioProcessingFactory
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.MediaStreamTrack
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.audio.JavaAudioDeviceModule
import com.rfdiy.openremotetrx.logic.MicProcessing

/**
 * Liaison WebRTC avec la station, comme la page : une piste audio dans chaque sens (micro FERMÉ tant que la
 * session ne l'ouvre pas, en TX confirmé), canal « control » en JSON, canal « spectrum » (binaire, non ordonné,
 * sans renvoi : un balayage perdu est remplacé par le suivant ; la station n'envoie rien sans `spectrum_watch`).
 *
 * Toutes les méthodes s'appellent sur le fil de RigService ; les rappels de WebRTC y sont renvoyés par `post`,
 * et ceux d'une liaison déjà fermée sont ignorés (numéro de génération).
 */
class RtcLink(
    context: Context,
    private val post: (() -> Unit) -> Unit,
    private val onMessage: (String) -> Unit,
    private val onClosed: (String) -> Unit,
    /** Balayage du spectre HF (binaire), sur le fil de WebRTC : à traiter vite (une copie, pas de calcul lourd). */
    private val onSpectrum: (ByteArray) -> Unit = {},
    /** Micro d'un casque Bluetooth : le son passe alors comme un appel (qualité téléphone, dans le casque). */
    voiceCall: Boolean = false,
    /** Annulation d'écho et réduction de bruit du micro (profil choisi par l'utilisateur, logic.MicProfiles). */
    private val processing: MicProcessing = MicProcessing(echo = true, noise = true),
) {
    private val factory: PeerConnectionFactory
    private var generation = 0
    private var pc: PeerConnection? = null
    private var dc: DataChannel? = null
    private var sc: DataChannel? = null
    private var micSource: AudioSource? = null
    private var micTrack: AudioTrack? = null
    private var remoteTrack: AudioTrack? = null
    private var sink: AudioTrackSink? = null                       // waterfall audio : gardée d'une connexion à l'autre
    private var muted = false

    init {
        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions())
        val adm = JavaAudioDeviceModule.builder(context.applicationContext)
            .setUseHardwareAcousticEchoCanceler(processing.echo)
            .setUseHardwareNoiseSuppressor(processing.noise)
            // Son de la station joué comme un média : haut-parleur, casque, Bluetooth ou voiture, volume « média ».
            // Micro du casque Bluetooth choisi : comme un appel, sinon le son partirait sur le haut-parleur du téléphone.
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(if (voiceCall) AudioAttributes.USAGE_VOICE_COMMUNICATION else AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
            )
            .createAudioDeviceModule()
        factory = PeerConnectionFactory.builder().setAudioDeviceModule(adm)
            .apply { voiceFx()?.let { setAudioProcessingFactory(it) } }
            .createPeerConnectionFactory()
    }

    /**
     * Un essai de connexion complet jusqu'à la réponse de la station. AttemptException en cas d'échec (la liaison
     * est alors déjà fermée). `useMic` faux : réception seule (pas d'autorisation du micro).
     */
    suspend fun open(account: StationAccount, password: String, useMic: Boolean) {
        close()
        val gen = ++generation
        val http = StationHttp(account.url, account.fingerprint)
        val ice = withContext(Dispatchers.IO) { http.iceServers() }
        val gathered = CompletableDeferred<Unit>()
        val config = PeerConnection.RTCConfiguration(ice.map { PeerConnection.IceServer.builder(it).createIceServer() }).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }
        val peer = factory.createPeerConnection(config, object : PeerConnection.Observer {
            override fun onSignalingChange(s: PeerConnection.SignalingState?) {}
            override fun onIceConnectionChange(s: PeerConnection.IceConnectionState?) {
                if (s == PeerConnection.IceConnectionState.FAILED) closedBy(gen, "ice_failed")
            }
            override fun onConnectionChange(s: PeerConnection.PeerConnectionState?) {
                when (s) {
                    PeerConnection.PeerConnectionState.FAILED -> closedBy(gen, "connection_failed")
                    PeerConnection.PeerConnectionState.CLOSED -> closedBy(gen, "connection_closed")
                    else -> Unit
                }
            }
            override fun onIceConnectionReceivingChange(b: Boolean) {}
            override fun onIceGatheringChange(s: PeerConnection.IceGatheringState?) {
                if (s == PeerConnection.IceGatheringState.COMPLETE) gathered.complete(Unit)
            }
            override fun onIceCandidate(c: IceCandidate?) {}
            override fun onIceCandidatesRemoved(c: Array<out IceCandidate>?) {}
            override fun onAddStream(m: MediaStream?) {}
            override fun onRemoveStream(m: MediaStream?) {}
            override fun onDataChannel(d: DataChannel?) {}
            override fun onRenegotiationNeeded() {}
            override fun onTrack(t: RtpTransceiver?) {
                val track = t?.receiver?.track() as? AudioTrack ?: return
                post {
                    if (gen != generation) return@post
                    remoteTrack = track
                    track.setEnabled(!muted)
                    sink?.let { track.addSink(it) }
                }
            }
        }) ?: throw AttemptException("client_error", "WebRTC indisponible")
        pc = peer

        if (useMic) {
            val constraints = MediaConstraints().apply {
                // Comme la page : pas de contrôle automatique de gain (il fausserait le niveau d'émission).
                optional.add(MediaConstraints.KeyValuePair("googAutoGainControl", "false"))
                optional.add(MediaConstraints.KeyValuePair("googEchoCancellation", processing.echo.toString()))
                optional.add(MediaConstraints.KeyValuePair("googNoiseSuppression", processing.noise.toString()))
                optional.add(MediaConstraints.KeyValuePair("googHighpassFilter", "true"))
            }
            val source = factory.createAudioSource(constraints)
            val track = factory.createAudioTrack("mic", source)
            track.setEnabled(false)                                   // FERMÉ tant que l'émission n'est pas confirmée
            micSource = source
            micTrack = track
            peer.addTrack(track, listOf("trx"))
        } else {
            peer.addTransceiver(
                MediaStreamTrack.MediaType.MEDIA_TYPE_AUDIO,
                RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY),
            )
        }

        val channel = peer.createDataChannel("control", DataChannel.Init())
            ?: throw fail("client_error", "canal de contrôle impossible")
        dc = channel
        channel.registerObserver(object : DataChannel.Observer {
            override fun onBufferedAmountChange(amount: Long) {}
            override fun onStateChange() {
                if (channel.state() == DataChannel.State.CLOSED) closedBy(gen, "datachannel_closed")
            }
            override fun onMessage(buffer: DataChannel.Buffer) {
                if (buffer.binary) return
                val bytes = ByteArray(buffer.data.remaining()).also { buffer.data.get(it) }
                val text = String(bytes, Charsets.UTF_8)
                post { if (gen == generation) onMessage(text) }
            }
        })

        // Spectre HF : non ordonné, sans renvoi (comme la page) ; facultatif, le reste fonctionne sans lui.
        val spectrumInit = DataChannel.Init().apply { ordered = false; maxRetransmits = 0 }
        peer.createDataChannel("spectrum", spectrumInit)?.let { channel ->
            sc = channel
            channel.registerObserver(object : DataChannel.Observer {
                override fun onBufferedAmountChange(amount: Long) {}
                override fun onStateChange() {}
                override fun onMessage(buffer: DataChannel.Buffer) {
                    if (!buffer.binary || gen != generation) return
                    val bytes = ByteArray(buffer.data.remaining()).also { buffer.data.get(it) }
                    onSpectrum(bytes)
                }
            })
        }

        try {
            val offer = sdp { peer.createOffer(it, MediaConstraints()) }
            sdpSet { peer.setLocalDescription(it, offer) }
            withTimeoutOrNull(3000) { gathered.await() }            // la station attend un SDP complet
            val local = peer.localDescription?.description ?: throw AttemptException("client_error", "offre vide")
            val answer = withContext(Dispatchers.IO) { http.offer(account.user, password, local) }
            if (gen != generation) throw AttemptException("client_error", "essai annulé")
            sdpSet { peer.setRemoteDescription(it, SessionDescription(SessionDescription.Type.ANSWER, answer)) }
        } catch (e: AttemptException) {
            if (gen == generation) close()
            throw e
        } catch (e: Exception) {
            if (gen == generation) close()
            throw AttemptException("client_error", (e.message ?: e.javaClass.simpleName).take(160))
        }
    }

    fun send(text: String): Boolean {
        val channel = dc ?: return false
        if (channel.state() != DataChannel.State.OPEN) return false
        return channel.send(DataChannel.Buffer(ByteBuffer.wrap(text.toByteArray(Charsets.UTF_8)), false))
    }

    fun setMicOpen(open: Boolean) {
        micTrack?.setEnabled(open)
        VoiceHub.setTx(open)                                        // traîne coupée, relecture arrêtée à la prise
    }

    /** Sourdine de la réception (le volume se règle par les touches « média » du téléphone). */
    fun setMuted(value: Boolean) {
        muted = value
        remoteTrack?.setEnabled(!value)
    }

    /** Prise du son reçu (waterfall audio) ; null = débranchée. */
    fun setAudioSink(value: AudioTrackSink?) {
        sink?.let { old -> remoteTrack?.let { runCatching { it.removeSink(old) } } }
        sink = value
        value?.let { s -> remoteTrack?.let { runCatching { it.addSink(s) } } }
    }

    /** Ferme tout, micro d'abord ; les rappels de cette liaison seront ignorés. */
    fun close() {
        generation++
        micTrack?.setEnabled(false)
        VoiceHub.setTx(false)
        dc?.let { d -> runCatching { d.unregisterObserver(); d.close(); d.dispose() } }
        dc = null
        sc?.let { d -> runCatching { d.unregisterObserver(); d.close(); d.dispose() } }
        sc = null
        sink?.let { s -> remoteTrack?.let { runCatching { it.removeSink(s) } } }   // avant de libérer la piste
        pc?.let { p -> runCatching { p.close(); p.dispose() } }
        pc = null
        micTrack?.let { t -> runCatching { t.dispose() } }
        micTrack = null
        micSource?.let { s -> runCatching { s.dispose() } }
        micSource = null
        remoteTrack = null
    }

    fun release() {
        close()
        runCatching { factory.dispose() }
        // JAMAIS voiceFx.destroy() : voir voiceFx() plus bas.
    }

    private fun closedBy(gen: Int, code: String) {
        post { if (gen == generation) onClosed(code) }
    }

    private fun fail(code: String, detail: String): AttemptException {
        close()
        return AttemptException(code, detail)
    }

    private suspend fun sdp(call: (SdpObserver) -> Unit): SessionDescription = suspendCancellableCoroutine { cont ->
        call(object : SdpObserver {
            override fun onCreateSuccess(d: SessionDescription?) {
                if (d != null) cont.resume(d) else cont.resumeWithException(AttemptException("client_error", "offre vide"))
            }
            override fun onSetSuccess() {}
            override fun onCreateFailure(e: String?) = cont.resumeWithException(AttemptException("client_error", e ?: "offre"))
            override fun onSetFailure(e: String?) {}
        })
    }

    private suspend fun sdpSet(call: (SdpObserver) -> Unit): Unit = suspendCancellableCoroutine { cont ->
        call(object : SdpObserver {
            override fun onCreateSuccess(d: SessionDescription?) {}
            override fun onSetSuccess() = cont.resume(Unit)
            override fun onCreateFailure(e: String?) {}
            override fun onSetFailure(e: String?) = cont.resumeWithException(AttemptException("client_error", e ?: "SDP refusé"))
        })
    }

    private companion object {
        private var voiceFx: ExternalAudioProcessingFactory? = null
        private var voiceFxTried = false

        /**
         * Égaliseur et effets de voix (VoiceHub) : après l'annulation d'écho, avant l'encodage Opus. UN SEUL par processus,
         * gardé jusqu'à sa fin : le code natif de stream-webrtc (1.3.10) tient un objet GLOBAL que `destroy()` libère sans
         * l'oublier ; la liaison suivante réutilisait l'objet libéré et la fermeture suivante le libérait deux fois
         * (SIGABRT dans ExternalAudioProcessingFactory.destroy, relevé par trx-journal-android le 2026-10-30, étape 95).
         * Appelé APRÈS PeerConnectionFactory.initialize (bibliothèque chargée) ; en cas d'échec, liaison sans égaliseur.
         */
        @Synchronized
        fun voiceFx(): ExternalAudioProcessingFactory? {
            if (voiceFxTried) return voiceFx
            voiceFxTried = true
            voiceFx = try {
                ExternalAudioProcessingFactory().apply {
                    setCapturePostProcessing(VoiceHub.processor)
                    setBypassFlagForCapturePost(false)
                    setRenderPreProcessing(VoiceHub.rxProcessor)            // débrouillage du scrambler (réception)
                    setBypassFlagForRenderPre(false)
                }
            } catch (e: Throwable) {                               // UnsatisfiedLinkError compris
                VoiceHub.unavailable("Égaliseur indisponible sur ce téléphone (${e.javaClass.simpleName}) : voix sans traitement.")
                null
            }
            return voiceFx
        }
    }
}
