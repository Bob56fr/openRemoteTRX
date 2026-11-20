// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.os.Build
import android.os.Handler
import android.os.Looper
import com.rfdiy.openremotetrx.logic.Spatial
import com.rfdiy.openremotetrx.logic.SpatialSettings
import com.rfdiy.openremotetrx.logic.Spatials
import com.rfdiy.openremotetrx.logic.Tr
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.webrtc.AudioTrackSink

/** Ce que l'écran observe. */
data class SpatialUi(
    val settings: SpatialSettings = SpatialSettings(),
    /** Le son passe-t-il en ce moment par la sortie stéréo de l'application ? */
    val playing: Boolean = false,
    /** Raison d'un mono imposé (sortie mono, voiture…), vide sinon. */
    val monoReason: String = "",
    val ab: Boolean = false,
    val correlation: Double = 1.0,
    val failed: String = "",
)

/**
 * Spatialisation stéréo de la réception « ST » (docs/spatialisation-cahier-des-charges.md), réglages du téléphone.
 *
 * Le crochet de la réception de WebRTC (« render pre-processing ») ne traite qu'une voie : il ne peut pas produire de
 * stéréo. Quand ST est en service, le son reçu est donc pris par une `AudioTrackSink` (avant le volume de la piste),
 * spatialisé (jamais avec le débrouillage du scrambler : exclusifs), puis joué par un `AudioTrack` stéréo de l'application (mêmes
 * attributs « média » que WebRTC) ; la piste de WebRTC est mise au volume 0. Sinon rien ne change.
 * Mono imposé : sortie mono (casque en mode appel, haut-parleur unique), voiture (Android Auto), case « Sortie mono ».
 * Pendant l'émission, le chemin n'est jamais changé (le casque Bluetooth passe alors en mode appel, étape 96).
 */
object SpatialHub {
    private const val PREF = "spatial_json"
    private val _ui = MutableStateFlow(SpatialUi())
    val ui: StateFlow<SpatialUi> = _ui.asStateFlow()

    @Volatile private var app: Context? = null
    @Volatile private var tx = false
    @Volatile private var muted = false
    @Volatile private var car = false
    @Volatile private var link: RtcLink? = null
    @Volatile private var post: (() -> Unit) -> Unit = { it() }
    private val out = StereoOut()
    private val main by lazy { Handler(Looper.getMainLooper()) }
    /** Rouvertures de la sortie stéréo après une émission (ms après le retour en réception). */
    private val AFTER_TX_MS = longArrayOf(800L, 2500L)
    private var txEnd = 0                                          // numéro de la dernière fin d'émission

    private var watching = false

    fun load(context: Context) {
        app = context.applicationContext
        if (!watching) {
            watching = true
            (context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager)?.registerAudioDeviceCallback(object : android.media.AudioDeviceCallback() {
                override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>?) = apply()
                override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>?) = apply()
            }, android.os.Handler(android.os.Looper.getMainLooper()))
        }
        val text = context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).getString(PREF, null)
        val s = text?.let { runCatching { Spatials.validate(Json.parseToJsonElement(it) as? JsonObject) }.getOrNull() } ?: SpatialSettings()
        _ui.value = _ui.value.copy(settings = s)
        apply()
    }

    fun save(context: Context, settings: SpatialSettings) {
        val s = Spatials.validate(settings)
        context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).edit().putString(PREF, Spatials.toJson(s).toString()).apply()
        val wasOn = _ui.value.settings.on
        _ui.value = _ui.value.copy(settings = s, failed = if (s.on && !wasOn) "" else _ui.value.failed)
        // Débrouillage du scrambler et spatialisation : exclusifs (décision de l'utilisateur du 2026-11-03)
        val scr = VoiceHub.ui.value.scrambler
        if (s.on && !wasOn && scr.rx) {
            VoiceHub.setScrambler(context, scr.copy(rx = false))
            RigHub.service?.onRig { session, now -> session.note(now, Tr.t("spatialhub.descrambler_off")) }
        }
        apply()
    }

    fun setEnabled(context: Context, on: Boolean) = save(context, _ui.value.settings.copy(on = on))

    /** A/B maintenu : mono dans le traitement (sans changer de chemin). */
    fun setAb(on: Boolean) {
        _ui.value = _ui.value.copy(ab = on)
        out.params(Spatials.params(_ui.value.settings, on))
    }

    /** `run` : fil de la liaison (RigService), seul à toucher la piste reçue. */
    internal fun attach(rtc: RtcLink, run: (() -> Unit) -> Unit) { link = rtc; post = run; apply() }
    internal fun detach(rtc: RtcLink) { if (link === rtc) { out.stop(); link = null; apply() } }
    internal fun setTx(on: Boolean) {
        val ended = tx && !on
        tx = on
        if (on) return
        apply()
        // Fin d'émission : le micro a mis le téléphone en mode appel ; juste après, la sortie peut encore paraître mono
        // (ST coupée, jamais relancée) ou la sortie stéréo rester figée sur le chemin du mode appel. La sortie stéréo est
        // donc ROUVERTE une fois le mode appel fini, puis revérifiée (essai réel du 2026-11-20 : ST perdue après une
        // émission).
        if (!ended) return
        val end = ++txEnd
        AFTER_TX_MS.forEachIndexed { i, delay -> main.postDelayed({ reopenAfterTx(end, reopen = i == 0) }, delay) }
    }

    @Synchronized
    private fun reopenAfterTx(end: Int, reopen: Boolean) {
        if (tx || end != txEnd) return                              // nouvelle émission entre-temps : rien
        if (reopen && out.running) {                                // nouvelle sortie = chemin audio relu
            out.stop()
            link?.let { rtc -> post { rtc.useStereo(null) } }
        }
        apply()
    }
    internal fun setMuted(on: Boolean) { muted = on }
    internal fun setCar(on: Boolean) { car = on; apply() }
    /** Sortie audio changée (casque branché, Bluetooth…). */
    fun outputChanged() = apply()

    /** Le son reçu passe-t-il par la sortie stéréo (enregistrement de rediffusion et débrouillage faits ici) ? */
    internal val playing: Boolean get() = out.running

    private fun monoReason(): String {
        val s = _ui.value.settings
        if (s.monoOut) return Tr.t("spatialhub.mono_chosen")
        if (car) return Tr.t("spatialhub.car_mono")
        val am = app?.getSystemService(Context.AUDIO_SERVICE) as? AudioManager ?: return ""
        val devices: List<AudioDeviceInfo> = if (Build.VERSION.SDK_INT >= 33) {
            am.getAudioDevicesForAttributes(StereoOut.ATTRIBUTES)
        } else {
            am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).toList()
                .sortedByDescending { it.type in StereoOut.HEADPHONES }.take(1)
        }
        val d = devices.firstOrNull() ?: return ""
        if (d.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) return Tr.t("spatialhub.bt_call_mode")
        val counts = d.channelCounts
        if (counts.isNotEmpty() && counts.max() < 2) return Tr.t("spatialhub.mono_output", "device" to d.productName)
        return ""
    }

    @Synchronized
    private fun apply() {
        val s = _ui.value.settings
        out.params(Spatials.params(s, _ui.value.ab))
        if (tx) return                                              // jamais de changement de chemin en émission
        val reason = if (s.on) monoReason() else ""
        val want = s.on && reason.isEmpty() && link != null && _ui.value.failed.isEmpty()
        val rtc = link
        if (want && !out.running && rtc != null) {
            val error = out.start()
            if (error == null) post { rtc.useStereo(out.sink) } else _ui.value = _ui.value.copy(failed = error)
        } else if (!want && out.running) {
            out.stop()
            if (rtc != null) post { rtc.useStereo(null) }
        }
        _ui.value = _ui.value.copy(playing = out.running, monoReason = reason)
    }

    internal fun publishCorrelation(c: Double) { _ui.value = _ui.value.copy(correlation = c) }

    /** Sortie stéréo de l'application : son reçu -> spatialisation -> AudioTrack stéréo. */
    internal class StereoOut {
        companion object {
            val ATTRIBUTES: AudioAttributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
            val HEADPHONES = setOf(
                AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_USB_HEADSET,
                AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLE_HEADSET, AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
            )
            private const val RATE = 48000
        }

        @Volatile var running = false
            private set
        @Volatile private var track: AudioTrack? = null
        @Volatile private var spatial: Spatial? = null
        @Volatile private var wanted = Spatials.params(SpatialSettings())
        private var mono = FloatArray(0)
        private var stereo = FloatArray(0)
        private var dropped = 0L
        private var blocks = 0L
        private var sumSq = 0.0
        private var lastLog = 0L
        private var lastPublish = 0L

        fun params(p: com.rfdiy.openremotetrx.logic.SpatialParams) { wanted = p; spatial?.set(p) }

        fun start(): String? {
            if (running) return null
            return try {
                val min = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_FLOAT)
                val t = AudioTrack.Builder()
                    .setAudioAttributes(ATTRIBUTES)
                    .setAudioFormat(AudioFormat.Builder().setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                        .setEncoding(AudioFormat.ENCODING_PCM_FLOAT).build())
                    .setBufferSizeInBytes(maxOf(min, RATE / 10 * 2 * 4))         // 100 ms au plus en réserve
                    .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .build()
                if (t.state != AudioTrack.STATE_INITIALIZED) { t.release(); return Tr.t("spatialhub.stereo_unavailable") }
                spatial = Spatial(RATE, wanted).also { it.startDry() }
                val prefill = FloatArray(RATE / 50 * 2)                      // 20 ms de silence : marge contre les trous
                t.write(prefill, 0, prefill.size, AudioTrack.WRITE_NON_BLOCKING)
                t.play()
                track = t
                running = true
                dropped = 0; blocks = 0; sumSq = 0.0; lastLog = System.nanoTime()
                android.util.Log.i("SpatialHub", "sortie stéréo ouverte (tampon ${t.bufferSizeInFrames} échantillons)") // i18n-ok
                null
            } catch (e: RuntimeException) {
                Tr.t("spatialhub.stereo_failed", "error" to e.javaClass.simpleName)
            }
        }

        fun stop() {
            running = false
            val t = track ?: return
            track = null
            runCatching { t.pause(); t.flush(); t.release() }
            android.util.Log.i("SpatialHub", "sortie stéréo fermée") // i18n-ok
        }

        /** Fil audio de WebRTC, blocs de 10 ms, 16 bits ; avant le volume de la piste. */
        val sink = AudioTrackSink { data: ByteBuffer, bits: Int, rate: Int, channels: Int, frames: Int, _: Long ->
            val t = track
            val sp = spatial
            if (!running || t == null || sp == null || bits != 16 || channels < 1 || frames <= 0) return@AudioTrackSink
            try {
                if (rate != RATE) { logOnce("débit $rate Hz inattendu : bloc ignoré"); return@AudioTrackSink } // i18n-ok
                val pcm = data.duplicate().order(ByteOrder.nativeOrder())
                if (mono.size < frames) { mono = FloatArray(frames); stereo = FloatArray(2 * frames) }
                for (f in 0 until frames) {
                    var sum = 0
                    for (c in 0 until channels) sum += pcm.getShort((f * channels + c) * 2).toInt()
                    mono[f] = sum / channels / 32768f
                }
                if (muted) mono.fill(0f, 0, frames)
                if (ReplayHub.ui.value.recording) ReplayHub.onRx(mono, frames, RATE)
                for (f in 0 until frames) sumSq += mono[f] * mono[f]
                sp.process(mono, frames, stereo)
                val n = t.write(stereo, 0, 2 * frames, AudioTrack.WRITE_NON_BLOCKING)
                if (n in 0 until 2 * frames) dropped += (2 * frames - n) / 2
                blocks++
                val now = System.nanoTime()
                if (now - lastPublish > 250_000_000L) { lastPublish = now; publishCorrelation(sp.correlation) }
                if (now - lastLog > 5_000_000_000L) {
                    val rms = if (blocks > 0) kotlin.math.sqrt(sumSq / (blocks * frames)) else 0.0
                    android.util.Log.i("SpatialHub", "blocs $blocks, $channels voie(s), niveau reçu ${"%.4f".format(rms)}, " + // i18n-ok
                        "échantillons perdus $dropped, trous ${t.underrunCount}, corrélation ${"%.2f".format(sp.correlation)}") // i18n-ok
                    lastLog = now; sumSq = 0.0; blocks = 0
                }
            } catch (e: RuntimeException) {
                logOnce("bloc perdu : ${e.javaClass.simpleName}") // i18n-ok
            }
        }

        private var logged = false
        private fun logOnce(text: String) { if (!logged) { logged = true; android.util.Log.w("SpatialHub", text) } }
    }
}
