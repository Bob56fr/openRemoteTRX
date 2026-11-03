// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/** Préréglage d'usine (lecture seule) ; `engine` nul = Mono (bypass). */
data class SpatialPreset(val label: String, val engine: String?, val width: Int, val presence: Int)

/** Réglages de la spatialisation, enregistrés sur le téléphone. */
data class SpatialSettings(
    val on: Boolean = false,
    val preset: String = "comfort",
    val width: Int = 70,
    val presence: Int = 40,
    val balance: Int = 0,
    val monoOut: Boolean = false,
)

/** Paramètres du traitement (largeur, présence en 0..1, équilibre en -1..1). */
data class SpatialParams(val engine: String, val width: Double, val presence: Double, val balance: Double, val bypass: Boolean)

/**
 * Spatialisation stéréo de la réception « ST », même calcul que la page (spatial.js,
 * docs/spatialisation-cahier-des-charges.md) ; réponses de référence communes : tests/protocol/spatial_presets.json.
 *
 * Chaque moteur fournit milieu / côté (M, S) de même puissance ; G = g·(M + w·S), D = g·(M − w·S),
 * g = 1/√(1 + (w·(1 − p))²). Décorrélation : S = 6 passe-tout de Schroeder. Binaural : paire de passe-tout à 90°
 * (Niemitalo), voie A retardée d'un échantillon. Présence : S − p·passe-bande 300-2 700 Hz (FIR à phase linéaire,
 * tout retardé de LATENCY échantillons). Lissage 20 ms, fondus 50 ms, limiteur stéréo lié à −1 dBFS toujours actif.
 */
object Spatials {
    const val WIDTH_MAX = 150
    const val FIR_TAPS = 255
    const val LATENCY = (FIR_TAPS - 1) / 2
    const val VOICE_LO_HZ = 300.0
    const val VOICE_HI_HZ = 2700.0
    val CEILING = 10.0.pow(-1.0 / 20)
    internal const val SMOOTH_S = 0.02
    internal const val FADE_S = 0.05
    internal const val RELEASE_S = 0.1
    internal val HILBERT_A = doubleArrayOf(0.6923878, 0.9360654322959, 0.9882295226860, 0.9987488452737)
    internal val HILBERT_B = doubleArrayOf(0.4021921162426, 0.8561710882420, 0.9722909545651, 0.9952884791278)
    internal val DECOR_MS = doubleArrayOf(1.3, 2.1, 2.9, 3.7, 4.9, 6.7)
    internal const val DECOR_G = 0.5

    val PRESETS = linkedMapOf(
        "mono" to SpatialPreset("Mono", null, 0, 0),
        "comfort" to SpatialPreset("Confort", "decor", 70, 40),
        "dx" to SpatialPreset("DX BLU", "binaural", 80, 25),
        "cw" to SpatialPreset("CW binaural", "binaural", 100, 0),
    )

    private fun JsonObject.int(key: String, lo: Int, hi: Int, dflt: Int): Int {
        val v = (get(key) as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull ?: return dflt
        return if (v.isFinite()) v.coerceIn(lo.toDouble(), hi.toDouble()).roundToInt() else dflt
    }

    /** Réglages relus (préférences) : toute valeur hors bornes est ramenée dans les bornes, comme validate() de la page. */
    fun validate(raw: JsonObject?): SpatialSettings {
        var d = SpatialSettings()
        if (raw == null) return d
        (raw["on"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull?.let { d = d.copy(on = it) }
        (raw["monoOut"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull?.let { d = d.copy(monoOut = it) }
        (raw["preset"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull?.let { key ->
            PRESETS[key]?.let { d = d.copy(preset = key, width = it.width, presence = it.presence) }
        }
        return d.copy(width = raw.int("width", 0, WIDTH_MAX, d.width), presence = raw.int("presence", 0, 100, d.presence),
            balance = raw.int("balance", -100, 100, 0))
    }

    fun validate(s: SpatialSettings): SpatialSettings = validate(toJson(s))

    fun toJson(s: SpatialSettings): JsonObject = buildJsonObject {
        put("on", s.on); put("preset", s.preset); put("width", s.width); put("presence", s.presence)
        put("balance", s.balance); put("monoOut", s.monoOut)
    }

    /** Choix d'un préréglage : ses valeurs remplacent les curseurs (l'équilibre reste). */
    fun choose(s: SpatialSettings, key: String): SpatialSettings {
        val p = PRESETS[key] ?: return s
        return s.copy(preset = key, width = p.width, presence = p.presence)
    }

    fun isModified(s: SpatialSettings): Boolean {
        val p = PRESETS[s.preset] ?: return false
        return p.engine != null && (s.width != p.width || s.presence != p.presence)
    }

    fun label(s: SpatialSettings): String = PRESETS[s.preset]?.let { it.label + if (isModified(s)) " (modifié)" else "" } ?: "?"

    /** Bypass : ST éteint, préréglage Mono, sortie mono, ou A/B maintenu. */
    fun params(s: SpatialSettings, abMono: Boolean = false): SpatialParams {
        val p = PRESETS[s.preset] ?: PRESETS.getValue("mono")
        val bypass = !s.on || s.monoOut || abMono || p.engine == null
        return SpatialParams(p.engine ?: "decor", s.width / 100.0, s.presence / 100.0, s.balance / 100.0, bypass)
    }

    /** Passe-bande 300-2 700 Hz à phase linéaire (sinus cardinal fenêtré de Hamming). */
    internal fun voiceFir(rate: Int): DoubleArray {
        val c = (FIR_TAPS - 1) / 2.0
        fun lp(fc: Double, k: Double) = if (k == 0.0) 2 * fc / rate else sin(2 * PI * fc * k / rate) / (PI * k)
        return DoubleArray(FIR_TAPS) { i ->
            val k = i - c
            (lp(VOICE_HI_HZ, k) - lp(VOICE_LO_HZ, k)) * (0.54 - 0.46 * cos(2 * PI * i / (FIR_TAPS - 1)))
        }
    }
}

/** Traitement : un appel par bloc, sur un seul fil. */
class Spatial(private val rate: Int, initial: SpatialParams? = null) {
    private val smooth = 1 - exp(-1 / (Spatials.SMOOTH_S * rate))
    private val fadeStep = 1 / (Spatials.FADE_S * rate)
    private val release = 1 - exp(-1 / (Spatials.RELEASE_S * rate))
    private val ka = DoubleArray(4) { Spatials.HILBERT_A[it] * Spatials.HILBERT_A[it] }
    private val kb = DoubleArray(4) { Spatials.HILBERT_B[it] * Spatials.HILBERT_B[it] }
    private val sa = DoubleArray(16)
    private val sb = DoubleArray(16)
    private var aDelay = 0.0
    private val lines = Array(Spatials.DECOR_MS.size) { DoubleArray(max(1, (Spatials.DECOR_MS[it] * rate / 1000).roundToInt())) }
    private val linePos = IntArray(lines.size)
    private val fir = Spatials.voiceFir(rate)
    private val hx = DoubleArray(Spatials.FIR_TAPS)
    private val hm = DoubleArray(Spatials.FIR_TAPS)
    private val hs = DoubleArray(Spatials.FIR_TAPS)
    private var pos = 0
    private var gain = 1.0
    private var corrLr = 0.0
    private var corrLl = 0.0
    private var corrRr = 0.0
    private var corrN = 0

    @Volatile private var target = SpatialParams("decor", 0.0, 0.0, 0.0, true)
    private var w = 0.0
    private var p = 0.0
    private var bal = 0.0
    private var mixB = 0.0
    private var dry = 1.0

    /** Corrélation G/D du dernier quart de seconde (1 = mono). */
    @Volatile var correlation = 1.0
        private set

    /** Sorties du dernier échantillon (step). */
    var left = 0.0
        private set
    var right = 0.0
        private set

    init {
        initial?.let { set(it) }
        jump()
    }

    /** Nouveaux paramètres : atteints en douceur (curseurs 20 ms, moteur et bypass 50 ms). Appelable depuis un autre fil. */
    fun set(p: SpatialParams) {
        target = SpatialParams(
            if (p.engine == "binaural" || p.engine == "decor") p.engine else target.engine,
            p.width.takeIf { it.isFinite() }?.coerceIn(0.0, Spatials.WIDTH_MAX / 100.0) ?: 0.0,
            p.presence.takeIf { it.isFinite() }?.coerceIn(0.0, 1.0) ?: 0.0,
            p.balance.takeIf { it.isFinite() }?.coerceIn(-1.0, 1.0) ?: 0.0,
            p.bypass,
        )
    }

    /** Valeurs atteintes tout de suite (création, tests). */
    fun jump() {
        val t = target
        w = t.width; p = t.presence; bal = t.balance
        mixB = if (t.engine == "binaural") 1.0 else 0.0
        dry = if (t.bypass) 1.0 else 0.0
    }

    /** Démarrage en mono, fondu vers l'effet (comme le module AudioWorklet de la page). */
    fun startDry() { dry = 1.0 }

    private fun reset() {
        sa.fill(0.0); sb.fill(0.0); aDelay = 0.0
        for (l in lines) l.fill(0.0)
        hx.fill(0.0); hm.fill(0.0); hs.fill(0.0)
        gain = 1.0
    }

    private fun cells(k: DoubleArray, st: DoubleArray, input: Double): Double {
        var x = input
        for (i in 0 until 4) {
            val j = 4 * i
            val y = k[i] * (x + st[j + 3]) - st[j + 1]
            st[j + 1] = st[j]; st[j] = x; st[j + 3] = st[j + 2]; st[j + 2] = y
            x = y
        }
        return x
    }

    private fun decor(input: Double): Double {
        var x = input
        for (i in lines.indices) {
            val line = lines[i]
            val q = linePos[i]
            val old = line[q]
            val v = x + Spatials.DECOR_G * old
            line[q] = v
            linePos[i] = if (q + 1 == line.size) 0 else q + 1
            x = old - Spatials.DECOR_G * v
        }
        return x
    }

    private fun toward(value: Double, want: Double, step: Double) = value + (want - value).coerceIn(-step, step)

    /** Un échantillon : résultat dans left / right. */
    fun step(input: Double) {
        val t = target
        var x = if (input.isFinite()) input else 0.0
        w += (t.width - w) * smooth
        p += (t.presence - p) * smooth
        bal += (t.balance - bal) * smooth
        mixB = toward(mixB, if (t.engine == "binaural") 1.0 else 0.0, fadeStep)
        dry = toward(dry, if (t.bypass) 1.0 else 0.0, fadeStep)
        // Les deux moteurs tournent toujours : changement de moteur sans transitoire
        val a = aDelay
        aDelay = cells(ka, sa, x)
        val b = cells(kb, sb, x)
        val r2 = sqrt(0.5)
        val mB = (a + b) * r2
        val sB = (a - b) * r2
        val sD = decor(x)
        val at = pos
        hx[at] = x; hm[at] = mixB * mB + (1 - mixB) * x; hs[at] = mixB * sB + (1 - mixB) * sD
        pos = if (at + 1 == Spatials.FIR_TAPS) 0 else at + 1
        val old = (at + Spatials.FIR_TAPS - Spatials.LATENCY) % Spatials.FIR_TAPS
        x = hx[old]
        val m = hm[old]
        var s = hs[old]
        if (p > 1e-6) {
            var band = 0.0
            var j = at
            for (k in 0 until Spatials.FIR_TAPS) {
                band += fir[k] * hs[j]
                j = if (j == 0) Spatials.FIR_TAPS - 1 else j - 1
            }
            s -= p * band
        }
        val we = w * (1 - p)
        val g = 1 / sqrt(1 + we * we)
        var l = g * (m + w * s)
        var r = g * (m - w * s)
        l = dry * x + (1 - dry) * l
        r = dry * x + (1 - dry) * r
        if (bal > 0) l *= 1 - bal else r *= 1 + bal
        // Limiteur lié : réduction instantanée, remontée en 100 ms sans jamais dépasser le plafond
        val peak = max(abs(l), abs(r))
        val need = if (peak > Spatials.CEILING) Spatials.CEILING / peak else 1.0
        gain = min(need, gain + (1 - gain) * release)
        l *= gain; r *= gain
        if (!l.isFinite() || !r.isFinite()) { reset(); l = 0.0; r = 0.0 }
        left = l; right = r
        corrLr += l * r; corrLl += l * l; corrRr += r * r
        if (++corrN >= rate / 4) {
            correlation = if (corrLl > 1e-12 && corrRr > 1e-12) corrLr / sqrt(corrLl * corrRr) else 1.0
            corrLr = 0.0; corrLl = 0.0; corrRr = 0.0; corrN = 0
        }
    }

    /** Bloc mono -> stéréo entrelacé (G, D, G, D…). */
    fun process(input: FloatArray, n: Int, interleaved: FloatArray) {
        for (i in 0 until n) {
            step(input[i].toDouble())
            interleaved[2 * i] = left.toFloat()
            interleaved[2 * i + 1] = right.toFloat()
        }
    }
}
