// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Analyse du son reçu, comme l'AnalyserNode de la page (Web Audio) : FFT de `fftSize` points, fenêtre de Blackman,
 * module divisé par N, lissage temporel `smoothing`, niveaux en dBFS. Mêmes réglages que la page (4096 ; 0,35) :
 * mêmes niveaux, donc mêmes couleurs. Les échantillons arrivent d'un autre fil : `push` et `analyse` sont synchronisés.
 */
class SpectrumAnalyser(val fftSize: Int = 4096, private val smoothing: Double = 0.35) {
    init { require(fftSize >= 32 && fftSize and (fftSize - 1) == 0) { "fftSize : puissance de 2" } }

    private val ring = FloatArray(fftSize)
    private var write = 0
    private val window = DoubleArray(fftSize) { n ->
        val a = 2 * PI * n / fftSize                               // Blackman (alpha 0,16), comme Web Audio
        0.42 - 0.5 * cos(a) + 0.08 * cos(2 * a)
    }
    private val smoothed = DoubleArray(fftSize / 2)
    private val re = DoubleArray(fftSize)
    private val im = DoubleArray(fftSize)
    private val out = FloatArray(fftSize / 2)

    @Synchronized
    fun push(samples: FloatArray, count: Int = samples.size) {
        for (i in 0 until count) {
            ring[write] = samples[i]
            write = (write + 1) % fftSize
        }
    }

    @Synchronized
    fun reset() {
        ring.fill(0f)
        smoothed.fill(0.0)
        write = 0
    }

    /** Niveaux en dBFS des raies 0 .. fftSize/2 - 1 (raie i centrée sur i × sampleRate / fftSize). */
    @Synchronized
    fun analyse(): FloatArray {
        for (n in 0 until fftSize) {
            re[n] = ring[(write + n) % fftSize] * window[n]
            im[n] = 0.0
        }
        fft(re, im)
        for (k in 0 until fftSize / 2) {
            val magnitude = sqrt(re[k] * re[k] + im[k] * im[k]) / fftSize
            smoothed[k] = smoothing * smoothed[k] + (1 - smoothing) * magnitude
            out[k] = if (smoothed[k] > 0) (20 * ln(smoothed[k]) / ln(10.0)).toFloat() else -200f
        }
        return out.copyOf()
    }

    /** FFT radix 2 sur place. */
    private fun fft(re: DoubleArray, im: DoubleArray) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
            j = j xor bit
            if (i < j) { re[i] = re[j].also { re[j] = re[i] }; im[i] = im[j].also { im[j] = im[i] } }
        }
        var len = 2
        while (len <= n) {
            val ang = -2 * PI / len
            val wr = cos(ang)
            val wi = sin(ang)
            var i = 0
            while (i < n) {
                var cr = 1.0
                var ci = 0.0
                for (k in 0 until len / 2) {
                    val ar = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci
                    val ai = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr
                    re[i + k + len / 2] = re[i + k] - ar
                    im[i + k + len / 2] = im[i + k] - ai
                    re[i + k] += ar
                    im[i + k] += ai
                    val nr = cr * wr - ci * wi
                    ci = cr * wi + ci * wr
                    cr = nr
                }
                i += len
            }
            len = len shl 1
        }
    }
}

/** Réglages du waterfall audio (gardés sur le téléphone) ; `peak` en secondes, 0 = pas de pics, infini = maintien. */
data class WaterfallSettings(val speed: Int = 12, val width: Int = 5000, val gain: Int = 0, val peak: Double = 2.0)

/** Raie la plus forte : fréquence et niveau. */
data class Peak(val hz: Int, val db: Float)

/** Graduation de l'axe du waterfall audio (en kHz sans unité, comme la page). */
data class AudioTick(val hz: Int, val fraction: Float, val label: String)

/** Calculs du waterfall audio, repris de la page (waterfall.js). */
object AudioWaterfall {
    val SPEEDS = listOf(3, 6, 12, 25, 50)                         // lignes par seconde
    val WIDTHS = listOf(5000, 3000, 2500, 2000, 1000)             // bande affichée : 0 à N Hz
    val GAINS = listOf(-12, -6, 0, 6, 12, 18)
    val PEAK_TIMES = listOf(0.0, 0.5, 2.0, 5.0, Double.POSITIVE_INFINITY)
    const val FLOOR_DB = -85.0
    const val RANGE_DB = 55.0
    const val GRID_HZ = 500

    fun speedLabel(v: Int) = "VIT $v"
    fun widthLabel(v: Int) = "LARG " + (v / 1000.0).let { if (it % 1.0 == 0.0) "${it.toInt()}" else "$it" } + "k"
    fun gainLabel(v: Int) = "GAIN " + if (v > 0) "+$v" else "$v"
    fun peakLabel(v: Double) = when {
        v == 0.0 -> "PIC OFF"
        v.isInfinite() -> "PIC MAX"
        else -> "PIC " + (if (v % 1.0 == 0.0) "${v.toInt()}" else "$v") + "s"
    }

    private fun <T> cycle(list: List<T>, value: T): T = list[(list.indexOf(value) + 1) % list.size]
    fun nextSpeed(s: WaterfallSettings) = s.copy(speed = cycle(SPEEDS, s.speed))
    fun nextWidth(s: WaterfallSettings) = s.copy(width = cycle(WIDTHS, s.width))
    fun nextGain(s: WaterfallSettings) = s.copy(gain = cycle(GAINS, s.gain))
    fun nextPeak(s: WaterfallSettings) = s.copy(peak = cycle(PEAK_TIMES, s.peak))

    /** Réglages relus (préférences) : valeur inconnue = valeur par défaut. `peak` est rangé par son rang. */
    fun normalize(speed: Int, width: Int, gain: Int, peakIndex: Int): WaterfallSettings {
        val d = WaterfallSettings()
        return WaterfallSettings(
            speed = speed.takeIf { it in SPEEDS } ?: d.speed,
            width = width.takeIf { it in WIDTHS } ?: d.width,
            gain = gain.takeIf { it in GAINS } ?: d.gain,
            peak = PEAK_TIMES.getOrNull(peakIndex) ?: d.peak,
        )
    }

    /** dBFS -> 0..1 : sans gain, de -85 dBFS (noir) à -30 dBFS (blanc). */
    fun levelToT(db: Float, gain: Int): Float {
        val floor = FLOOR_DB - gain
        return ((db - floor) / RANGE_DB).coerceIn(0.0, 1.0).toFloat()
    }

    /** Une valeur en dB par pixel, de 0 Hz à `spanHz` : la raie la plus forte du pixel, sinon interpolation. */
    fun resample(db: FloatArray, sampleRate: Int, fftSize: Int, spanHz: Int, width: Int, out: FloatArray? = null): FloatArray {
        val result = if (out != null && out.size == width) out else FloatArray(width)
        val binHz = sampleRate.toDouble() / fftSize
        val last = db.size - 1
        fun value(i: Int): Float = db[min(last, max(0, i))].let { if (it.isFinite()) it else -200f }
        for (x in 0 until width) {
            val f0 = x.toDouble() / width * spanHz
            val f1 = (x + 1).toDouble() / width * spanHz
            val b0 = kotlin.math.ceil(f0 / binHz).toInt()
            val b1 = kotlin.math.ceil(f1 / binHz).toInt() - 1
            result[x] = if (b1 >= b0) {
                var peak = -200f
                for (b in b0..b1) peak = max(peak, value(b))
                peak
            } else {
                val pos = (f0 + f1) / 2 / binHz
                val i = kotlin.math.floor(pos).toInt()
                val k = (pos - i).toFloat()
                value(i) * (1 - k) + value(i + 1) * k
            }
        }
        return result
    }

    /** La raie la plus forte au-dessus de `minDb` (par défaut 20 dB au-dessus du noir), ou null. */
    fun strongest(values: FloatArray, spanHz: Int, minDb: Float = (FLOOR_DB + 20).toFloat()): Peak? {
        var best = -1
        var top = Float.NEGATIVE_INFINITY
        for (i in values.indices) if (values[i] > top) { top = values[i]; best = i }
        if (best < 0 || top <= minDb) return null
        return Peak(((best + 0.5) / values.size * spanHz).roundToInt(), top)
    }

    /** Une graduation tous les 500 Hz, en kHz sans unité. */
    fun axisTicks(spanHz: Int): List<AudioTick> = (0..spanHz step GRID_HZ).map { hz ->
        AudioTick(hz, hz.toFloat() / spanHz, (hz / 1000.0).let { if (it % 1.0 == 0.0) "${it.toInt()}" else "$it" })
    }
}

/** Pics avec décroissance réglable (waterfall.js : PeakTracker). */
class PeakTracker {
    private var peaks: FloatArray? = null

    fun reset() { peaks = null }

    fun update(values: FloatArray, dtSeconds: Double, tau: Double): FloatArray? {
        if (tau <= 0) { peaks = null; return null }
        val p = peaks?.takeIf { it.size == values.size } ?: values.copyOf().also { peaks = it }
        val decay = if (tau.isInfinite()) 0.0 else AudioWaterfall.RANGE_DB / tau * max(0.0, dtSeconds)
        for (i in values.indices) p[i] = max(values[i], (p[i] - decay).toFloat())
        return p
    }
}
