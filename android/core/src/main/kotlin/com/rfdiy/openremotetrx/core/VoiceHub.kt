// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.AudioTrack
import com.rfdiy.openremotetrx.logic.VoiceDsp
import com.rfdiy.openremotetrx.logic.VoiceEq
import com.rfdiy.openremotetrx.logic.VoiceSettings
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.webrtc.ExternalAudioProcessingFactory
import kotlin.math.abs

/** Ce que l'écran « Égaliseur » observe. */
data class VoiceUi(
    val settings: VoiceSettings = VoiceSettings(),
    /** Secondes enregistrées (prise en cours ou dernière prise), 0 = aucune. */
    val recordedS: Double = 0.0,
    val recording: Boolean = false,
    val playing: Boolean = false,
    val micLevelDb: Double = -120.0,
    /** Le micro passe-t-il par le traitement ? (connecté avec le micro) */
    val live: Boolean = false,
    val failed: String = "",
)

/**
 * Égaliseur et effets de voix de l'application (docs/egaliseur-voix.md) : réglages enregistrés sur le téléphone,
 * traitement branché dans WebRTC APRÈS l'annulation d'écho et AVANT l'encodage Opus (« capture post-processing »).
 *
 * Sécurité (comme la page) : l'émission reste décidée par la station et la piste micro n'est ouverte qu'en TX
 * confirmé (RtcLink) ; la traîne est coupée à chaque changement d'émission ; l'enregistrement et la relecture ne vont
 * JAMAIS vers la station (lecture sur le téléphone seulement), sont refusés en émission et arrêtés par toute prise.
 */
object VoiceHub {
    private const val PREF = "voice_json"
    private val _ui = MutableStateFlow(VoiceUi())
    val ui: StateFlow<VoiceUi> = _ui.asStateFlow()

    @Volatile private var tx = false
    @Volatile private var recording = false
    private var record = FloatArray(0)
    @Volatile private var recordLen = 0
    @Volatile private var recordRate = 48000
    private var player: Thread? = null
    private var recorder: Thread? = null
    @Volatile private var recLevel = -120.0
    private const val RECORD_RATE = 48000
    @Volatile private var playing = false

    internal val processor = Processor()

    fun load(context: Context) {
        val text = context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).getString(PREF, null)
        val s = text?.let { runCatching { VoiceEq.validate(Json.parseToJsonElement(it) as? JsonObject) }.getOrNull() } ?: VoiceSettings()
        processor.dsp?.apply(s)
        _ui.value = _ui.value.copy(settings = s)
    }

    fun save(context: Context, settings: VoiceSettings) {
        val s = VoiceEq.validate(settings)
        context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).edit().putString(PREF, VoiceEq.toJson(s).toString()).apply()
        processor.dsp?.apply(s)
        _ui.value = _ui.value.copy(settings = s)
    }

    internal fun unavailable(text: String) {
        android.util.Log.w("VoiceHub", text)
        _ui.value = _ui.value.copy(failed = text)
    }

    /** Bouton marche/arrêt d'accès direct. */
    fun setEnabled(context: Context, on: Boolean) = save(context, _ui.value.settings.copy(enabled = on))

    /** Émission confirmée (piste micro ouverte) ou non : traîne coupée ; prise => enregistrement et relecture arrêtés. */
    internal fun setTx(on: Boolean) {
        if (on == tx) return
        tx = on
        processor.dsp?.setTx(on)
        if (on) {
            recording = false
            stopPlayback()
            publish()
        }
    }

    /**
     * Enregistrement du micro BRUT (avant traitement), 30 s au plus, par le micro du téléphone directement (WebRTC ne
     * l'ouvre qu'en émission) ; refusé en émission, arrêté par toute prise d'émission.
     */
    fun startRecording(): String? {
        if (tx) return "Pas d'enregistrement pendant une émission."
        stopPlayback()
        stopRecording()
        val rate = RECORD_RATE
        val min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT)
        val rec = try {
            AudioRecord(MediaRecorder.AudioSource.MIC, rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT, maxOf(min, rate / 5 * 4))
        } catch (e: SecurityException) {
            return "Micro non autorisé : autorisez-le dans les réglages d'Android."
        } catch (e: IllegalArgumentException) {
            return "Micro indisponible."
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            return "Micro indisponible (occupé par une autre application ?)."
        }
        recordRate = rate
        record = FloatArray(rate * VoiceEq.RECORD_MAX_S)
        recordLen = 0
        recording = true
        publish()
        recorder = Thread({
            val block = FloatArray(rate / 100)
            try {
                rec.startRecording()
                while (recording && !tx && recordLen < record.size) {
                    val n = rec.read(block, 0, block.size, AudioRecord.READ_BLOCKING)
                    if (n <= 0) break
                    val k = minOf(n, record.size - recordLen)
                    System.arraycopy(block, 0, record, recordLen, k)
                    recordLen += k
                    var sum = 0.0
                    for (i in 0 until n) sum += block[i] * block[i]
                    val rms = kotlin.math.sqrt(sum / n)
                    recLevel = if (rms > 1e-6) 20 * kotlin.math.log10(rms) else -120.0
                    publish()
                }
            } catch (_: RuntimeException) {
            } finally {
                runCatching { rec.stop() }
                rec.release()
                recording = false
                recLevel = -120.0
                publish()
            }
        }, "voice-record").also { it.start() }
        return null
    }

    fun stopRecording() {
        recording = false
        recorder?.let { if (it !== Thread.currentThread()) runCatching { it.join(300) } }
        recorder = null
        publish()
    }

    /** Relecture de la prise à travers les réglages EN COURS, sur le téléphone seulement (jamais vers la station). */
    fun play(): String? {
        if (tx) return "Pas de relecture pendant une émission."
        if (recordLen == 0) return "Enregistrez d'abord quelques secondes."
        stopPlayback()
        recording = false
        val rate = recordRate
        val take = record.copyOf(recordLen)
        playing = true
        publish()
        player = Thread({
            val minBuf = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT)
            val track = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(rate).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_FLOAT).build())
                .setBufferSizeInBytes(maxOf(minBuf, rate / 5 * 4))
                .build()
            try {
                val dsp = VoiceDsp(rate)
                val block = rate / 100
                track.play()
                var i = 0
                while (playing && !tx && i < take.size) {
                    val n = minOf(block, take.size - i)
                    val chunk = take.copyOfRange(i, i + n)
                    dsp.apply(_ui.value.settings)                   // réglages modifiables pendant la relecture
                    dsp.process(chunk, n)
                    track.write(chunk, 0, n, AudioTrack.WRITE_BLOCKING)
                    i += n
                }
                if (playing && !tx) track.stop()
            } catch (_: RuntimeException) {
            } finally {
                runCatching { track.pause(); track.flush(); track.release() }
                playing = false
                publish()
            }
        }, "voice-play").also { it.start() }
        return null
    }

    fun stopPlayback() {
        playing = false
        player?.let { if (it !== Thread.currentThread()) runCatching { it.join(300) } }
        player = null
    }

    private var lastPublish = 0L
    @Volatile private var lastProcess = 0L

    private fun publish() {
        _ui.value = _ui.value.copy(
            recordedS = recordLen.toDouble() / recordRate, recording = recording, playing = playing,
            micLevelDb = if (recording) recLevel else processor.dsp?.micLevelDb ?: -120.0,
            live = recording || System.nanoTime() - lastProcess < 1_000_000_000L,
        )
    }

    /** Traitement appelé par WebRTC (fil audio, blocs de 10 ms), échantillons flottants mono. */
    internal class Processor : ExternalAudioProcessingFactory.AudioProcessing {
        @Volatile var dsp: VoiceDsp? = null
        private var scale = 1f                                      // 32768 si WebRTC donne des « FloatS16 »
        private var work = FloatArray(480)
        private var seen = 0                                        // blocs vus depuis l'initialisation (journal)
        private var peak = 0f

        override fun initialize(sampleRateHz: Int, numChannels: Int) {
            dsp = VoiceDsp(sampleRateHz).also { d ->
                d.apply(_ui.value.settings)
                d.onFail = { text ->
                    _ui.value = _ui.value.copy(failed = text)
                    RigHub.service?.onRig { s, now -> s.note(now, text, warn = true) }
                }
            }
            scale = 1f
            seen = 0
            peak = 0f
            android.util.Log.i("VoiceHub", "traitement du micro : $sampleRateHz Hz, $numChannels canal(aux)")
            publish()
        }

        override fun reset(sampleRateHz: Int) = initialize(sampleRateHz, 1)

        override fun process(numBands: Int, numFrames: Int, buffer: ByteBuffer) {
            val d = dsp ?: return
            try {
                val fb = buffer.order(ByteOrder.nativeOrder()).asFloatBuffer()
                val n = minOf(numFrames, fb.capacity())
                if (n <= 0) return
                if (work.size < n) work = FloatArray(n)
                fb.position(0)
                fb.get(work, 0, n)
                // Échelle : -1..1 ou ±32768 selon la version de WebRTC ; une valeur au-delà de 4 tranche pour de bon
                if (scale == 1f) for (i in 0 until n) if (abs(work[i]) > 4f) { scale = 32768f; break }
                if (seen < 500) {                                    // 5 premières secondes : échelle constatée (journal)
                    for (i in 0 until n) peak = maxOf(peak, abs(work[i]))
                    if (++seen == 500) android.util.Log.i("VoiceHub", "échelle ${if (scale == 1f) "-1..1" else "FloatS16"}, crête brute $peak, bandes $numBands, $numFrames échantillons par bloc")
                }
                if (scale != 1f) for (i in 0 until n) work[i] /= scale
                d.process(work, n)
                if (scale != 1f) for (i in 0 until n) work[i] *= scale
                fb.position(0)
                fb.put(work, 0, n)
                val now = System.nanoTime()
                lastProcess = now
                if (now - lastPublish > 200_000_000L) {
                    lastPublish = now
                    publish()
                }
            } catch (_: RuntimeException) {
                // le bloc part tel quel (jamais de silence)
            }
        }

    }
}
