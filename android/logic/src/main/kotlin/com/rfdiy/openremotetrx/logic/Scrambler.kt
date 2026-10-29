// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.PI
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.roundToInt
import kotlin.math.sin

/** Mode du scrambler : perm[i] = case où va la bande i ; inv[i] = bande retournée. */
data class ScramblerMode(val label: String, val perm: List<Int>, val inv: List<Int>)

/** Réglages : tx et rx ne sont JAMAIS enregistrés (toujours éteints au démarrage), seulement le mode et le décalage. */
data class ScramblerSettings(val tx: Boolean = false, val rx: Boolean = false, val mode: String = "inv1", val offsetHz: Int = 0)

/**
 * Scrambler de voix à bandes inversées / permutées, même calcul que la page (scrambler.js, docs/scrambler.md) :
 * transformée de Fourier à court terme de 2 048 points (demi-recouvrement, fenêtres racine de Hann), bande 300-3 000 Hz
 * découpée en 1 à 5 bandes sur des bins PAIRS (indépendant du découpage en trames : émetteur et récepteur n'ont pas à
 * être synchronisés), décalage fin en réception (BLU mal accordée) par transformée de Hilbert.
 */
object Scramblers {
    const val FRAME = 2048
    const val HOP = 1024
    const val LO_HZ = 300.0
    const val HI_HZ = 3000.0
    const val OFFSET_MAX_HZ = 300

    val MODES = linkedMapOf(
        "inv1" to ScramblerMode("Inversion simple (1 bande)", listOf(0), listOf(1)),
        "inv2" to ScramblerMode("2 bandes inversées", listOf(0, 1), listOf(1, 1)),
        "inv3" to ScramblerMode("3 bandes inversées", listOf(0, 1, 2), listOf(1, 1, 1)),
        "inv4" to ScramblerMode("4 bandes inversées", listOf(0, 1, 2, 3), listOf(1, 1, 1, 1)),
        "inv5" to ScramblerMode("5 bandes inversées", listOf(0, 1, 2, 3, 4), listOf(1, 1, 1, 1, 1)),
        "mix2" to ScramblerMode("2 bandes échangées", listOf(1, 0), listOf(0, 0)),
        "mix3" to ScramblerMode("3 bandes mélangées", listOf(2, 0, 1), listOf(1, 0, 1)),
        "mix4" to ScramblerMode("4 bandes mélangées", listOf(1, 3, 0, 2), listOf(1, 1, 0, 0)),
        "mix5a" to ScramblerMode("5 bandes mélangées A", listOf(4, 2, 0, 3, 1), listOf(1, 1, 1, 1, 1)),
        "mix5b" to ScramblerMode("5 bandes mélangées B", listOf(2, 4, 1, 0, 3), listOf(0, 1, 0, 1, 1)),
    )

    /** Réglages relus : seuls le mode et le décalage sont repris (tx et rx toujours éteints). */
    fun validate(mode: String?, offsetHz: Int?): ScramblerSettings = ScramblerSettings(
        mode = mode?.takeIf { it in MODES } ?: "inv1",
        offsetHz = (offsetHz ?: 0).coerceIn(-OFFSET_MAX_HZ, OFFSET_MAX_HZ),
    )

    /** Bandes [a, b] en bins (a et b pairs), un bin libre entre deux bandes. */
    fun bands(n: Int, rate: Int, frame: Int = FRAME): List<IntArray> {
        val df = rate.toDouble() / frame
        var lo = ceil(LO_HZ / df).toInt(); if (lo % 2 != 0) lo++
        val hi = floor(HI_HZ / df).toInt()
        var w = (hi - lo) / n; if (w % 2 != 0) w--
        return (0 until n).map { i -> intArrayOf(lo + i * w, lo + i * w + w - 2) }
    }

    /** dest[k] = bin où va le bin k (-1 : supprimé) ; conj[k] = retourné. `tx` brouille, sinon débrouille. */
    fun binMap(modeKey: String, tx: Boolean, rate: Int, frame: Int = FRAME): Pair<IntArray, BooleanArray> {
        val mode = MODES[modeKey] ?: throw IllegalArgumentException("mode de scrambler inconnu : $modeKey")
        val half = frame / 2 + 1
        val dest = IntArray(half) { -1 }
        val conj = BooleanArray(half)
        val b = bands(mode.perm.size, rate, frame)
        mode.perm.forEachIndexed { i, slot ->
            val src = if (tx) b[i] else b[slot]
            val dst = if (tx) b[slot] else b[i]
            for (k in src[0]..src[1]) {
                val off = k - src[0]
                dest[k] = if (mode.inv[i] == 1) dst[1] - off else dst[0] + off
                conj[k] = mode.inv[i] == 1
            }
        }
        return dest to conj
    }

    /** FFT complexe en place (radix 2) ; inverse normalisée par 1/n (scrambler.js : fft). */
    fun fft(re: DoubleArray, im: DoubleArray, inverse: Boolean) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) { j = j xor bit; bit = bit shr 1 }
            j = j xor bit
            if (i < j) {
                var t = re[i]; re[i] = re[j]; re[j] = t
                t = im[i]; im[i] = im[j]; im[j] = t
            }
        }
        var len = 2
        while (len <= n) {
            val ang = (if (inverse) 2 else -2) * PI / len
            val wr = cos(ang); val wi = sin(ang)
            var i = 0
            while (i < n) {
                var cr = 1.0; var ci = 0.0
                for (k in 0 until len / 2) {
                    val a = i + k; val b = a + len / 2
                    val xr = re[b] * cr - im[b] * ci; val xi = re[b] * ci + im[b] * cr
                    re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi
                    val t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t
                }
                i += len
            }
            len = len shl 1
        }
        if (inverse) for (i in 0 until n) { re[i] /= n; im[i] /= n }
    }
}

/** Décalage de fréquence de `hz` (Hilbert FIR 127 coefficients, fenêtre de Blackman) : x·cos − H{x}·sin. */
class FrequencyShifter(private val rate: Int) {
    @Volatile var hz = 0.0
    private val h = DoubleArray(127)
    private val line = DoubleArray(127)
    private var pos = 0
    private val mid = 63
    private var phase = 0.0

    init {
        val n = h.size
        for (i in 0 until n) {
            val k = i - mid
            val w = 0.42 - 0.5 * cos(2 * PI * i / (n - 1)) + 0.08 * cos(4 * PI * i / (n - 1))
            h[i] = if (k % 2 != 0) (2 / (PI * k)) * w else 0.0
        }
    }

    fun run(x: Double): Double {
        val n = h.size
        line[pos] = x
        val f = hz
        if (f == 0.0) {
            pos = (pos + 1) % n
            return line[(pos + n - 1 - mid) % n]
        }
        var hil = 0.0
        for (i in 0 until n) hil += h[i] * line[(pos - i + n) % n]
        val direct = line[(pos - mid + n) % n]
        pos = (pos + 1) % n
        phase += 2 * PI * f / rate
        if (phase > PI) phase -= 2 * PI
        if (phase < -PI) phase += 2 * PI
        return direct * cos(phase) - hil * sin(phase)
    }
}

/** `tx` : brouille ; sinon débrouille (avec décalage fin). Mode null = transparent, sans retard. Un seul fil. */
class Scrambler(private val rate: Int, private val tx: Boolean) {
    private val frame = Scramblers.FRAME
    private val hop = Scramblers.HOP
    private val win = DoubleArray(frame) { sin(PI * it / frame) }
    private val inBuf = DoubleArray(frame)
    private val outAcc = DoubleArray(frame)
    private val re = DoubleArray(frame); private val im = DoubleArray(frame)
    private val ore = DoubleArray(frame); private val oim = DoubleArray(frame)
    private val ready = DoubleArray(hop)
    private var fill = 0
    private var readPos = hop
    private val shifter = FrequencyShifter(rate)
    private var mode: String? = null
    private var dest: IntArray? = null
    private var conj: BooleanArray? = null

    val active: Boolean get() = dest != null

    fun set(modeKey: String?, offsetHz: Int) {
        val m = modeKey?.takeIf { it in Scramblers.MODES }
        if (m != mode) {
            mode = m
            if (m == null) { dest = null; conj = null } else Scramblers.binMap(m, tx, rate, frame).let { dest = it.first; conj = it.second }
            clear()
        }
        shifter.hz = if (tx) 0.0 else offsetHz.coerceIn(-Scramblers.OFFSET_MAX_HZ, Scramblers.OFFSET_MAX_HZ).toDouble()
    }

    fun clear() {
        inBuf.fill(0.0); outAcc.fill(0.0); ready.fill(0.0); fill = 0; readPos = hop
    }

    private fun frame(d: IntArray, c: BooleanArray) {
        for (i in 0 until frame) { re[i] = inBuf[i] * win[i]; im[i] = 0.0 }
        Scramblers.fft(re, im, false)
        ore.fill(0.0); oim.fill(0.0)
        for (k in 0..frame / 2) {
            val to = d[k]
            if (to < 0) continue
            ore[to] = re[k]; oim[to] = if (c[k]) -im[k] else im[k]
        }
        for (k in 1 until frame / 2) { ore[frame - k] = ore[k]; oim[frame - k] = -oim[k] }
        Scramblers.fft(ore, oim, true)
        for (i in 0 until frame) outAcc[i] += ore[i] * win[i]
        for (i in 0 until hop) ready[i] = outAcc[i]
        System.arraycopy(outAcc, hop, outAcc, 0, frame - hop); outAcc.fill(0.0, frame - hop, frame)
        System.arraycopy(inBuf, hop, inBuf, 0, frame - hop)
        readPos = 0
    }

    /** Bloc de taille quelconque, en place ; sortie retardée de 2 048 échantillons (43 ms à 48 kHz). */
    fun process(buf: FloatArray, n: Int = buf.size) {
        val d = dest
        val c = conj
        if (d == null || c == null) {
            if (!tx) for (i in 0 until n) buf[i] = shifter.run(buf[i].toDouble()).toFloat()
            return
        }
        for (i in 0 until n) {
            val x = if (tx) buf[i].toDouble() else shifter.run(buf[i].toDouble())
            inBuf[frame - hop + fill] = x
            fill++
            if (fill == hop) { fill = 0; frame(d, c) }
            buf[i] = if (readPos < hop) ready[readPos++].toFloat() else 0f
        }
    }

    companion object {
        fun offsetLabel(hz: Int) = (if (hz > 0) "+" else "") + hz.toDouble().roundToInt() + " Hz"
    }
}
