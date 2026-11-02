// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.roundToInt

/** Ce que l'onglet « Audio » et l'onglet « Station » montrent de la rediffusion. */
data class ReplayUi(
    val recording: Boolean = false,
    val recordedS: Double = 0.0,
    val maxS: Int = 0,
    val levelDb: Double = -120.0,
    /** Émission demandée, en attente de la confirmation de la station. */
    val pending: Boolean = false,
    /** Diffusion en cours (émission confirmée de ce téléphone). */
    val playing: Boolean = false,
    val positionS: Double = 0.0,
)

/**
 * Rediffusion d'un enregistrement de l'audio REÇU (demande de l'utilisateur du 2026-11-02) : accordée sur la station
 * par l'assistant (`hello.replay`, `[safety] allow_replay`), durée au plus TOT - 5 s.
 *
 * Enregistrement : le son reçu de la station, capté juste avant le haut-parleur (traitement de réception de WebRTC),
 * jamais pendant une émission. Diffusion : un appui demande une émission NORMALE (même chemin que le PTT : armement,
 * station maîtresse de l'état, battements, TOT) ; dès l'émission CONFIRMÉE de ce téléphone, l'enregistrement remplace
 * ce que capte le micro (le micro n'est pas entendu) et passe aussi sur le haut-parleur du téléphone ; à la fin de
 * l'enregistrement, STOP (jamais un « toggle », qui pourrait reprendre l'émission après une coupure). STOP ou toute
 * coupure arrête la diffusion net.
 */
object ReplayHub {
    private val _ui = MutableStateFlow(ReplayUi())
    val ui: StateFlow<ReplayUi> = _ui.asStateFlow()

    private const val PENDING_TIMEOUT_MS = 5000L
    private const val PEAK = 0.7f                      // crête de la diffusion (-3 dBFS)

    private var buf = ShortArray(0)
    @Volatile private var len = 0
    @Volatile private var maxLen = 0
    @Volatile private var rate = 48000
    @Volatile private var recording = false
    @Volatile private var pending = false
    @Volatile private var pendingAt = 0L
    @Volatile private var playing = false
    @Volatile private var pos = 0.0                     // position de lecture (échantillons de l'enregistrement)
    @Volatile private var tx = false
    @Volatile private var level = -120.0
    private var local: Thread? = null
    private val main = Handler(Looper.getMainLooper())
    private var lastPublish = 0L

    fun setMax(maxS: Int?) {
        _ui.value = _ui.value.copy(maxS = maxS ?: 0)
        if (maxS == null || maxS <= 0) { stopRecording(); pending = false }
    }

    fun startRecording(): String? {
        val maxS = _ui.value.maxS
        if (maxS <= 0) return "Rediffusion non accordée par la station."
        if (tx || pending || playing) return "Pas d'enregistrement pendant une émission."
        maxLen = maxS * rate
        if (buf.size < maxLen) buf = ShortArray(maxLen)
        len = 0
        recording = true
        publish(force = true)
        return null
    }

    fun stopRecording() {
        recording = false
        publish(force = true)
    }

    /** Diffuser : demande d'émission normale ; la diffusion commence à la confirmation (onTx). */
    fun broadcast(): String? {
        if (_ui.value.maxS <= 0) return "Rediffusion non accordée par la station."
        if (len <= 0) return "Rien n'a été enregistré."
        if (tx || pending || playing) return "Une émission est déjà en cours."
        recording = false
        pending = true
        pendingAt = SystemClock.elapsedRealtime()
        publish(force = true)
        main.postDelayed({ if (pending && !playing) { pending = false; publish(force = true) } }, PENDING_TIMEOUT_MS)
        RigHub.toggle()
        return null
    }

    /** STOP de l'écran : coupe l'émission (station) et la diffusion. */
    fun stop() {
        pending = false
        finish()
        RigHub.stop()
    }

    /** Émission confirmée (piste micro ouverte) ou terminée, appelé par VoiceHub.setTx. */
    internal fun onTx(on: Boolean) {
        tx = on
        if (on) {
            recording = false
            if (pending && SystemClock.elapsedRealtime() - pendingAt <= PENDING_TIMEOUT_MS) {
                pending = false
                pos = 0.0
                playing = true
                startLocal()
            }
        } else {
            pending = false
            finish()
        }
        publish(force = true)
    }

    private fun finish() {
        playing = false
        local?.interrupt()
        local = null
    }

    /** Fil de réception (blocs de 10 ms, valeurs -1..1) : enregistrement. */
    internal fun onRx(work: FloatArray, n: Int, sampleRate: Int) {
        if (!recording) return
        if (len == 0) rate = sampleRate
        var peak = 0f
        val room = minOf(n, maxLen - len)
        for (i in 0 until room) {
            val v = work[i].coerceIn(-1f, 1f)
            peak = maxOf(peak, abs(v))
            buf[len + i] = (v * 32767f).roundToInt().toShort()
        }
        len += room
        level = if (peak > 0f) 20 * log10(peak.toDouble()) else -120.0
        if (len >= maxLen) recording = false
        publish()
    }

    /** Fil du micro (blocs de 10 ms, valeurs -1..1) : remplace le micro par l'enregistrement pendant la diffusion. */
    internal fun fillTx(work: FloatArray, n: Int, sampleRate: Int): Boolean {
        if (!playing) return false
        val step = rate.toDouble() / sampleRate
        for (i in 0 until n) {
            val p = pos
            val k = p.toInt()
            work[i] = if (k + 1 < len) {
                val f = (p - k).toFloat()
                ((buf[k] * (1 - f) + buf[k + 1] * f) / 32768f).coerceIn(-PEAK, PEAK)
            } else 0f
            pos = p + step
        }
        if (pos >= len) {                                    // fin de l'enregistrement : fin d'émission (STOP)
            playing = false
            main.post { if (tx) RigHub.stop() }
        }
        publish()
        return true
    }

    /** Écoute de l'enregistrement sur le téléphone pendant la diffusion (sortie média : haut-parleur ou casque). */
    private fun startLocal() {
        local?.interrupt()
        val samples = buf.copyOf(len)
        val r = rate
        local = Thread {
            val min = AudioTrack.getMinBufferSize(r, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val track = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(r).setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(maxOf(min, r / 5 * 2)).setTransferMode(AudioTrack.MODE_STREAM).build()
            try {
                track.play()
                var at = 0
                while (at < samples.size && playing && !Thread.currentThread().isInterrupted) {
                    val n = minOf(r / 20, samples.size - at)
                    val written = track.write(samples, at, n)
                    if (written <= 0) break
                    at += written
                }
            } catch (_: RuntimeException) {
                // écoute locale impossible : la diffusion vers la station continue
            } finally {
                runCatching { track.pause(); track.flush(); track.release() }
            }
        }.also { it.start() }
    }

    private fun publish(force: Boolean = false) {
        val now = SystemClock.elapsedRealtime()
        if (!force && now - lastPublish < 200) return
        lastPublish = now
        _ui.value = _ui.value.copy(recording = recording, recordedS = len.toDouble() / rate, levelDb = level,
            pending = pending, playing = playing, positionS = pos / rate)
    }
}
