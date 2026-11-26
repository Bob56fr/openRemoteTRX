// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.Process
import kotlin.math.PI
import kotlin.math.sin

/**
 * Retour local de la manipulation CW (branche exp/cw, cahier § 6) : la tonalité suit la clé du TÉLÉPHONE, jamais le
 * son reçu de la station. Sortie à faible latence (AudioTrack PERFORMANCE_MODE_LOW_LATENCY, tampon minimal, blocs de
 * 2 ms), fronts de 5 ms sans clic. Ne sert qu'à l'oreille de l'opérateur : la station recrée sa propre tonalité.
 */
object CwSidetone {
    private const val RATE = 48_000
    private const val CHUNK = 96                                  // 2 ms
    private const val EDGE_S = 0.005

    @Volatile private var keyDown = false
    @Volatile var toneHz: Double = 700.0
    @Volatile var volume: Double = 0.6
    @Volatile private var running = false
    private var thread: Thread? = null

    /** Latence de sortie annoncée par Android (ms), pour l'afficher ; null tant que la sortie n'est pas ouverte. */
    @Volatile var latencyMs: Int? = null
        private set

    fun start() {
        if (running) return
        running = true
        thread = Thread({ loop() }, "cw-sidetone").also { it.start() }      // i18n-ok
    }

    fun stop() {
        running = false
        keyDown = false
        thread?.join(300)
        thread = null
        latencyMs = null
    }

    fun key(down: Boolean) { keyDown = down }

    private fun loop() {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
        val min = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val track = runCatching {
            AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(RATE).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setBufferSizeInBytes(maxOf(min, CHUNK * 2 * 2))
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
        }.getOrNull() ?: run { running = false; return }
        latencyMs = (track.bufferSizeInFrames * 1000L / RATE).toInt()
        track.play()
        val buf = ShortArray(CHUNK)
        var phase = 0.0
        var level = 0.0
        val step = 1.0 / (RATE * EDGE_S)
        try {
            while (running) {
                val target = if (keyDown) 1.0 else 0.0
                val inc = 2 * PI * toneHz / RATE
                val gain = volume.coerceIn(0.0, 1.0) * 0.5 * Short.MAX_VALUE
                for (i in 0 until CHUNK) {
                    level = if (level < target) minOf(target, level + step) else maxOf(target, level - step)
                    val shaped = 0.5 - 0.5 * kotlin.math.cos(PI * level)          // front en cosinus surélevé
                    buf[i] = (gain * shaped * sin(phase)).toInt().toShort()
                    phase += inc
                    if (phase > 2 * PI) phase -= 2 * PI
                }
                track.write(buf, 0, CHUNK)                                       // bloquant : cadence de la sortie
            }
        } finally {
            runCatching { track.stop() }
            track.release()
        }
    }
}
