// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tanh

/**
 * Traitement du micro de l'application, même chaîne que la page (voice.js) : gain, porte de bruit, puis (égaliseur
 * allumé) coupe-bas, coupe-haut, 10 bandes, chorus, réverbération (algorithmique, type Freeverb), et TOUJOURS le
 * limiteur (compresseur 20:1 à -6 dBFS puis écrêtage doux à -3 dBFS).
 *
 * Échantillons normalisés (-1..1), mono, sur UN fil (celui de l'audio). `apply` peut venir d'un autre fil : les
 * réglages sont repris au bloc suivant. Sécurité : une erreur ou un calcul qui diverge => contournement (gain et
 * limiteur seuls), jamais de silence ni de son abîmé ; `setTx` coupe net la traîne (chorus, réverbération) à chaque
 * changement d'émission.
 */
class VoiceDsp(private val rate: Int) {
    @Volatile private var wanted: VoiceSettings = VoiceSettings()
    @Volatile private var resetWanted = false
    private var current: VoiceSettings? = null
    /** Vrai après une erreur : contournement jusqu'à la fin de la liaison. */
    @Volatile var failed = false
        private set
    var onFail: ((String) -> Unit)? = null

    private val hp = Biquad()
    private val lp = Biquad()
    private val eq = Array(VoiceEq.BANDS_HZ.size) { Biquad() }
    private val chorus = ChorusLine(rate)
    private val reverb = FreeVerb(rate)
    private var preGain = 1.0
    private var gate = 1.0
    private var gateOpenUntil = 0L
    private var clock = 0L                                   // échantillons traités (horloge de la porte)
    private var env = 0.0                                    // enveloppe du limiteur
    private val attack = exp(-1.0 / (0.002 * rate))
    private val release = exp(-1.0 / (0.08 * rate))
    private val gateUp = exp(-1.0 / (0.003 * rate))
    private val gateDown = exp(-1.0 / (0.05 * rate))

    fun apply(settings: VoiceSettings) { wanted = settings }

    /** Prise ou fin d'émission : traîne du chorus et de la réverbération coupée net (rien ne prolonge une émission). */
    fun setTx(@Suppress("UNUSED_PARAMETER") on: Boolean) { resetWanted = true }

    /** Niveau efficace du micro (dBFS) du dernier bloc, après le gain : pour régler gain et seuil de la porte. */
    @Volatile var micLevelDb = -120.0
        private set

    fun process(buf: FloatArray, n: Int = buf.size) {
        val s = wanted
        if (s !== current) configure(s)
        if (resetWanted) {
            resetWanted = false
            chorus.clear(); reverb.clear()
            scrambler?.clear()                                       // rien de l'émission précédente ne ressort
        }
        val set = current ?: return
        // gain du micro et mesure du niveau (porte de bruit)
        var sum = 0.0
        for (i in 0 until n) {
            val x = buf[i] * preGain
            buf[i] = x.toFloat()
            sum += x * x
        }
        val rms = sqrt(sum / maxOf(1, n))
        micLevelDb = if (rms > 1e-6) 20 * log10(rms) else -120.0
        val gateOn = set.mic.gateOn
        if (gateOn && micLevelDb >= set.mic.gateDb) gateOpenUntil = clock + (GATE_HOLD_S * rate).toLong()
        val target = if (!gateOn || clock < gateOpenUntil) 1.0 else GATE_FLOOR
        clock += n
        val on = set.enabled && !failed
        try {
            for (i in 0 until n) {
                gate = target + (gate - target) * (if (target > gate) gateUp else gateDown)
                var x = buf[i] * gate
                if (on) {
                    x = hp.run(x)
                    x = lp.run(x)
                    for (f in eq) x = f.run(x)
                    x = chorus.run(x)
                    x = reverb.run(x)
                    if (!x.isFinite()) throw ArithmeticException("calcul divergent")
                }
                buf[i] = x.toFloat()
            }
        } catch (e: RuntimeException) {
            fail(e.message ?: e.javaClass.simpleName)
            for (i in 0 until n) if (!buf[i].isFinite()) buf[i] = 0f
        }
        scramble(buf, n)
        for (i in 0 until n) buf[i] = limit(buf[i].toDouble()).toFloat()          // limiteur TOUJOURS en bout de chaîne
    }

    /** Scrambler d'émission (mode, ou null = voix en clair) ; inséré juste avant le limiteur, comme la page. */
    @Volatile var scrambleMode: String? = null
    private var scrambler: Scrambler? = null
    private var scrambled: String? = null

    private fun scramble(buf: FloatArray, n: Int) {
        val want = scrambleMode
        if (want != scrambled) {
            scrambled = want
            if (want != null && scrambler == null) scrambler = Scrambler(rate, tx = true)
            scrambler?.set(want, 0)
        }
        val s = scrambler ?: return
        if (!s.active) return
        try {
            s.process(buf, n)
        } catch (e: RuntimeException) {
            scrambleMode = null
            scrambled = null
            s.set(null, 0)
            onFail?.invoke("Scrambler en erreur (${e.message ?: e.javaClass.simpleName}) : voix en CLAIR.")
        }
    }

    private fun limit(x: Double): Double {
        val a = abs(x)
        env = if (a > env) a + (env - a) * attack else a + (env - a) * release
        val g = if (env > COMP_THRESHOLD) (COMP_THRESHOLD * (env / COMP_THRESHOLD).pow(1.0 / 20)) / env else 1.0
        return CEIL * tanh(x * g / CEIL)
    }

    private fun configure(s: VoiceSettings) {
        current = s
        preGain = 10.0.pow(s.mic.gainDb / 20)
        if (failed) return
        try {
            val fs = rate.toDouble()
            hp.set(VoiceEq.biquad("highpass", s.highpassHz, 0.707, 0.0, fs))
            lp.set(VoiceEq.biquad("lowpass", minOf(s.lowpassHz, fs * 0.45), 0.707, 0.0, fs))
            s.bands.forEachIndexed { i, b -> eq[i].set(VoiceEq.biquad(VoiceEq.bandType(b), minOf(b.hz, fs * 0.45), b.q, b.gainDb, fs)) }
            val t = VoiceEq.CHORUS_TYPES[s.chorus.type] ?: VoiceEq.CHORUS_TYPES.getValue("classic")
            chorus.set(if (s.chorus.on) s.chorus.mix / 100 else 0.0, t.voices, t.delayMs, s.chorus.rateHz, s.chorus.depthMs)
            val r = VoiceEq.REVERB_TYPES[s.reverb.type] ?: VoiceEq.REVERB_TYPES.getValue("room")
            reverb.set(if (s.reverb.on) s.reverb.mix / 100 else 0.0, s.reverb.seconds, r.bright, spring = s.reverb.type == "spring")
        } catch (e: RuntimeException) {
            fail(e.message ?: e.javaClass.simpleName)
        }
    }

    private fun fail(why: String) {
        if (failed) return
        failed = true
        chorus.clear(); reverb.clear()
        onFail?.invoke("Égaliseur en erreur ($why) : voix envoyée sans traitement (limiteur seul).")
    }

    companion object {
        const val GATE_HOLD_S = 0.25
        const val GATE_FLOOR = 0.03
        val CEIL = 10.0.pow(VoiceEq.LIMIT_DBFS / 20)
        val COMP_THRESHOLD = 10.0.pow((VoiceEq.LIMIT_DBFS - 3) / 20)
    }
}

/** Biquad en forme transposée II (coefficients a0 = 1) ; les états restent quand les réglages changent. */
internal class Biquad {
    private var b0 = 1.0; private var b1 = 0.0; private var b2 = 0.0; private var a1 = 0.0; private var a2 = 0.0
    private var z1 = 0.0; private var z2 = 0.0

    fun set(c: DoubleArray) { b0 = c[0]; b1 = c[1]; b2 = c[2]; a1 = c[3]; a2 = c[4] }

    fun run(x: Double): Double {
        val y = b0 * x + z1
        z1 = b1 * x - a1 * y + z2
        z2 = b2 * x - a2 * y
        return y
    }
}

/** Chorus : voix retardées (18 à 46 ms) modulées par des oscillateurs lents, comme la page. */
internal class ChorusLine(private val rate: Int) {
    private val buf = DoubleArray((0.1 * rate).toInt() + 2)
    private var pos = 0
    private var wet = 0.0
    private var voices = 1
    private var delayMs = 18.0
    private var rateHz = 0.8
    private var depthMs = 3.0
    private val phase = DoubleArray(3)

    fun set(wet: Double, voices: Int, delayMs: Double, rateHz: Double, depthMs: Double) {
        this.wet = wet; this.voices = voices.coerceIn(1, 3); this.delayMs = delayMs; this.rateHz = rateHz; this.depthMs = depthMs
    }

    fun clear() { buf.fill(0.0) }

    fun run(x: Double): Double {
        buf[pos] = x
        var out = x
        if (wet > 0) {
            var sum = 0.0
            for (v in 0 until voices) {
                phase[v] = (phase[v] + 2 * PI * rateHz * (1 + v * 0.27) / rate) % (2 * PI)
                val d = ((delayMs + v * 7) + depthMs * sin(phase[v])) * rate / 1000
                var p = pos - d
                while (p < 0) p += buf.size
                val i = p.toInt() % buf.size
                val f = p - p.toInt()
                sum += buf[i] * (1 - f) + buf[(i + 1) % buf.size] * f
            }
            out = x * (1 - wet / 2) + wet * sum / voices
        }
        pos = (pos + 1) % buf.size
        return out
    }
}

/** Réverbération algorithmique (Freeverb mono : 8 filtres en peigne amortis, 4 passe-tout). */
internal class FreeVerb(private val rate: Int) {
    private val combLen = intArrayOf(1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617).map { it * rate / 44100 }
    private val apLen = intArrayOf(556, 441, 341, 225).map { it * rate / 44100 }
    private val combs = combLen.map { DoubleArray(it) }
    private val combPos = IntArray(8)
    private val combStore = DoubleArray(8)
    private val aps = apLen.map { DoubleArray(it) }
    private val apPos = IntArray(4)
    private val feedback = DoubleArray(8)
    private var damp = 0.5
    private var wet = 0.0
    private var spring = false
    private var t = 0L

    fun set(wet: Double, seconds: Double, bright: Double, spring: Boolean) {
        this.wet = wet; this.spring = spring
        damp = (1 - bright).coerceIn(0.05, 0.95)
        for (i in 0 until 8) feedback[i] = 10.0.pow(-3.0 * combLen[i] / rate / seconds).coerceAtMost(0.98)
    }

    fun clear() {
        combs.forEach { it.fill(0.0) }; aps.forEach { it.fill(0.0) }; combStore.fill(0.0)
    }

    fun run(x: Double): Double {
        if (wet <= 0) return x
        val input = x * 0.015
        var acc = 0.0
        for (i in 0 until 8) {
            val c = combs[i]
            val y = c[combPos[i]]
            combStore[i] = y * (1 - damp) + combStore[i] * damp
            c[combPos[i]] = input + combStore[i] * feedback[i]
            combPos[i] = (combPos[i] + 1) % c.size
            acc += y
        }
        for (i in 0 until 4) {
            val a = aps[i]
            val b = a[apPos[i]]
            a[apPos[i]] = acc + b * 0.5
            acc = b - acc
            apPos[i] = (apPos[i] + 1) % a.size
        }
        if (spring) acc *= 0.7 + 0.3 * kotlin.math.cos(2 * PI * 9 * (t++) / rate)
        return x * (1 - wet / 2) + wet * acc * 3
    }
}
