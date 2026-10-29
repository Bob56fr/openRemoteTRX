// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import com.rfdiy.openremotetrx.logic.SpectrumAnalyser
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.webrtc.AudioTrackSink

/**
 * Prise du son REÇU de la station (piste distante), pour le waterfall audio : échantillons 16 bits ramenés en mono
 * puis confiés à l'analyseur. Branchée seulement pendant que le waterfall est affiché ; n'a aucun effet sur l'écoute.
 */
class AudioTap {
    val analyser = SpectrumAnalyser()
    @Volatile var sampleRate = 48_000
        private set
    private var mono = FloatArray(0)

    /** Branchée sur la piste distante par RtcLink (type WebRTC : reste interne à :core). */
    internal val sink = AudioTrackSink { data: ByteBuffer, bitsPerSample: Int, rate: Int, channels: Int, frames: Int, _: Long ->
        if (bitsPerSample != 16 || channels < 1 || frames <= 0) return@AudioTrackSink
        sampleRate = rate
        val pcm = data.duplicate().order(ByteOrder.nativeOrder())
        if (mono.size < frames) mono = FloatArray(frames)
        for (f in 0 until frames) {
            var sum = 0
            for (c in 0 until channels) sum += pcm.getShort((f * channels + c) * 2).toInt()
            mono[f] = sum / channels / 32768f
        }
        analyser.push(mono, frames)
    }
}
