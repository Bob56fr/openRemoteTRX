// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.SpectrumFrame
import com.rfdiy.openremotetrx.protocol.State
import java.util.Locale
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.roundToInt
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/**
 * Palette du waterfall de la page (waterfall.js : 6 couleurs aux positions fixes, thème par défaut) ; table de 256
 * couleurs ARGB, partagée par le spectre HF et le waterfall audio.
 */
object Palette {
    private val POSITIONS = doubleArrayOf(0.0, 0.2, 0.45, 0.7, 0.88, 1.0)
    val DEFAULT_GRADIENT = listOf("#06080c", "#1e2432", "#345698", "#62a2ec", "#bee2ff", "#ffffff")

    val LUT: IntArray = IntArray(256) { i -> argb(i / 255.0) }

    private fun rgb(hex: String) = Triple(hex.substring(1, 3).toInt(16), hex.substring(3, 5).toInt(16), hex.substring(5, 7).toInt(16))

    private fun argb(t: Double): Int {
        val x = t.coerceIn(0.0, 1.0)
        for (i in 1 until POSITIONS.size) {
            if (x <= POSITIONS[i]) {
                val (r0, g0, b0) = rgb(DEFAULT_GRADIENT[i - 1])
                val (r1, g1, b1) = rgb(DEFAULT_GRADIENT[i])
                val k = (x - POSITIONS[i - 1]) / (POSITIONS[i] - POSITIONS[i - 1])
                val r = (r0 + (r1 - r0) * k).roundToInt()
                val g = (g0 + (g1 - g0) * k).roundToInt()
                val b = (b0 + (b1 - b0) * k).roundToInt()
                return (0xFF shl 24) or (r shl 16) or (g shl 8) or b
            }
        }
        return -1
    }

    /** Couleur de `t` (0..1). */
    fun color(t: Float): Int = LUT[(t.coerceIn(0f, 1f) * 255).roundToInt()]
}

/** Fenêtre de niveaux colorée du noir au blanc (hfscope.js : colorWindow). */
data class ColorWindow(val bottom: Double, val span: Double, val floor: Double?)

/** Graduation de l'échelle : position 0..1 et libellé en MHz. */
data class Tick(val hz: Long, val fraction: Float, val label: String)

/** Réglages du spectre DU POSTE relus par la station (state.spectrum.settings). */
data class ScopeSettings(val mode: String?, val spanHz: Long?, val speed: String?, val refDb: Double?, val filter: Int?)

/** Calculs du spectre HF, repris de la page (hfscope.js) ; le dessin est dans l'application. */
object HfScope {
    val GAINS = listOf(-12, -6, 0, 6, 12, 18)
    const val LEVELS_PER_DB = 2
    val RANGES_DB = listOf(80, 60, 40, 30, 20)
    const val DEFAULT_RANGE_DB = 40
    private const val FLOOR_MARGIN_DB = 2
    private const val FLOOR_SMOOTHING = 0.2
    private val TICK_STEPS = listOf(1e3, 2e3, 2.5e3, 5e3, 1e4, 2e4, 2.5e4, 5e4, 1e5, 2e5, 2.5e5, 5e5, 1e6, 2e6, 5e6)
    val SPANS_HZ = listOf(2500L, 5000L, 10_000L, 25_000L, 50_000L, 100_000L, 250_000L, 500_000L)
    private val MODE_LABELS = mapOf("center" to "CENT", "fixed" to "FIX", "scroll_center" to "SCR-C", "scroll_fixed" to "SCR-F")
    private val SPEED_LABELS = mapOf("fast" to "VIT RAP", "mid" to "VIT MOY", "slow" to "VIT LENT")
    private val SPEED_ORDER = listOf("fast", "mid", "slow")
    private const val REF_MIN = -20.0
    private const val REF_MAX = 20.0
    private val TUNE_STEPS = listOf(10L, 50L, 100L, 500L, 1000L)

    /** La station a un spectre configuré : la vue est proposée (elle dit pourquoi si rien n'arrive). */
    fun configured(hello: Hello?): Boolean = hello?.spectrum != null

    private fun spectrum(state: State?): JsonObject? = state?.spectrum

    private fun text(obj: JsonObject?, key: String): String? = (obj?.get(key) as? JsonPrimitive)?.contentOrNull

    /** Texte à la place du spectre tant qu'aucun balayage n'arrive. */
    fun waitText(state: State?): String {
        val sp = spectrum(state)
        return when (text(sp, "state")) {
            "ok" -> "En attente du spectre du poste…"
            "waiting", "starting" -> "Mise en route du spectre du poste…"
            else -> {
                val why = text(sp, "message")?.takeIf { it.isNotEmpty() }?.take(300) ?: text(sp, "code")?.takeIf { it.isNotEmpty() } ?: "raison inconnue"
                "Le poste n'envoie pas de spectre : $why Nouvel essai à chaque ouverture de cette vue."
            }
        }
    }

    fun settings(state: State?): ScopeSettings {
        val s = spectrum(state)?.get("settings") as? JsonObject
        fun prim(k: String) = s?.get(k) as? JsonPrimitive
        return ScopeSettings(
            mode = prim("mode")?.contentOrNull, spanHz = prim("span")?.intOrNull?.toLong(), speed = prim("speed")?.contentOrNull,
            refDb = prim("ref")?.doubleOrNull, filter = prim("filter")?.intOrNull,
        )
    }

    /** Plancher de bruit d'un balayage : médiane des niveaux. */
    fun noiseFloor(frame: SpectrumFrame): Int {
        if (frame.size == 0) return 0
        val sorted = IntArray(frame.size) { frame.level(it) }.also { it.sort() }
        return sorted[sorted.size / 2]
    }

    fun colorWindow(frame: SpectrumFrame, levelMax: Int, rangeDb: Int, previousFloor: Double?): ColorWindow {
        val max = (if (levelMax > 0) levelMax else 160).toDouble()
        val span = minOf(max, (if (rangeDb in RANGES_DB) rangeDb else DEFAULT_RANGE_DB) * LEVELS_PER_DB.toDouble())
        if (span >= max) return ColorWindow(0.0, max, null)
        val current = noiseFloor(frame).toDouble()
        val floor = if (previousFloor != null) previousFloor + (current - previousFloor) * FLOOR_SMOOTHING else current
        val bottom = minOf(max - span, maxOf(0.0, floor - FLOOR_MARGIN_DB * LEVELS_PER_DB))
        return ColorWindow(bottom, span, floor)
    }

    /** Niveau du poste -> 0..1 dans la fenêtre ; le gain (dB) éclaircit ou assombrit. */
    fun windowT(value: Double, win: ColorWindow, gainDb: Int): Float =
        ((value + gainDb * LEVELS_PER_DB - win.bottom) / win.span).coerceIn(0.0, 1.0).toFloat()

    /** `width` valeurs interpolées entre les points du poste (on lisse, on n'invente pas de signal). */
    fun interpolateRow(frame: SpectrumFrame, width: Int, out: FloatArray? = null): FloatArray {
        val result = if (out != null && out.size == width) out else FloatArray(width)
        val n = frame.size
        if (n == 1) { result.fill(frame.level(0).toFloat()); return result }
        val scale = if (width > 1) (n - 1).toDouble() / (width - 1) else 0.0
        for (x in 0 until width) {
            val pos = x * scale
            val i = minOf(n - 2, floor(pos).toInt())
            val k = pos - i
            result[x] = (frame.level(i) * (1 - k) + frame.level(i + 1) * k).toFloat()
        }
        return result
    }

    private fun tickStep(spanHz: Double, maxTicks: Int): Double = TICK_STEPS.firstOrNull { spanHz / it <= maxTicks } ?: TICK_STEPS.last()

    fun mhzLabel(hz: Long, stepHz: Double): String {
        var decimals = 0
        while (decimals < 6) {
            val unit = Math.pow(10.0, (6 - decimals).toDouble())
            if (abs(Math.round(stepHz / unit) * unit - stepHz) <= 1e-6) break
            decimals++
        }
        return String.format(Locale.ROOT, "%.${decimals}f", hz / 1e6)
    }

    /** Graduations « rondes » entre les deux bords. */
    fun ticks(lowHz: Long, highHz: Long, maxTicks: Int = 8): List<Tick> {
        val span = (highHz - lowHz).toDouble()
        if (span <= 0) return emptyList()
        val step = tickStep(span, maxTicks)
        val out = mutableListOf<Tick>()
        var hz = ceil(lowHz / step) * step
        while (hz <= highHz) {
            out += Tick(hz.toLong(), ((hz - lowHz) / span).toFloat(), mhzLabel(hz.toLong(), step))
            hz += step
        }
        return out
    }

    /** Position de la fréquence du poste sur l'échelle (0..1), null hors de l'écran. */
    fun markerFraction(hz: Long?, lowHz: Long, highHz: Long): Float? {
        if (hz == null || highHz <= lowHz || hz < lowHz || hz > highHz) return null
        return ((hz - lowHz).toDouble() / (highHz - lowHz)).toFloat()
    }

    /** Même échelle et même nombre de points : l'historique du waterfall reste valable. */
    fun sameScale(a: SpectrumFrame?, b: SpectrumFrame?): Boolean =
        a != null && b != null && a.lowHz == b.lowHz && a.highHz == b.highHz && a.size == b.size

    fun spanLabel(lowHz: Long, highHz: Long): String {
        val span = highHz - lowHz
        return if (span >= 1_000_000) String.format(Locale.ROOT, if (span % 1_000_000 != 0L) "%.1f MHz" else "%.0f MHz", span / 1e6)
        else String.format(Locale.ROOT, if (span % 1000 != 0L) "%.1f kHz" else "%.0f kHz", span / 1e3)
    }

    fun gainLabel(v: Int) = "GAIN " + if (v > 0) "+$v" else "$v"
    fun rangeLabel(v: Int) = "PLAGE $v dB"
    fun nextGain(v: Int) = GAINS[(GAINS.indexOf(v) + 1) % GAINS.size]
    fun nextRange(v: Int) = RANGES_DB[(RANGES_DB.indexOf(v) + 1) % RANGES_DB.size]

    fun modeSettingLabel(m: String?) = MODE_LABELS[m] ?: "MODE ?"
    /** Défilement (lu seulement) -> centré ; centré <-> fixe. */
    fun nextMode(m: String?) = if (m == "center") "fixed" else "center"
    fun spanSettingLabel(hz: Long?): String =
        if (hz == null) "SPAN ?" else "±" + if (hz >= 1000) (hz / 1000.0).let { if (it % 1.0 == 0.0) "${it.toLong()}" else "$it".replace('.', ',') } + "k" else "$hz"
    fun nextSpan(hz: Long?) = SPANS_HZ[(SPANS_HZ.indexOf(hz ?: -1) + 1) % SPANS_HZ.size]
    fun speedSettingLabel(s: String?) = SPEED_LABELS[s] ?: "VIT ?"
    fun nextSpeed(s: String?) = SPEED_ORDER[(SPEED_ORDER.indexOf(s ?: "") + 1) % SPEED_ORDER.size]
    fun refLabel(db: Double?): String =
        if (db == null) "REF ?" else "REF " + (if (db > 0) "+" else "") + String.format(Locale.ROOT, "%.1f", db).replace('.', ',')

    /** Pas de 1 dB, ramené sur la grille de 0,5 dB du poste et borné à ±20 dB ; null si la valeur est inconnue. */
    fun stepRef(db: Double?, delta: Double): Double? =
        db?.let { (Math.round((it + delta) * 2) / 2.0).coerceIn(REF_MIN, REF_MAX) }

    /** Pas d'accord adapté à la largeur affichée : environ 400 pas sur l'écran. */
    fun tuneStep(spanHz: Long): Long {
        var step = TUNE_STEPS.first()
        for (s in TUNE_STEPS) if (s <= spanHz / 400.0) step = s
        return step
    }

    /** Glisser le spectre vers la GAUCHE fait monter la fréquence (le signal vient vers le repère), comme un VFO. */
    fun dragSteps(dx: Float, plotWidth: Float, spanHz: Long, stepHz: Long): Int {
        if (plotWidth <= 0 || spanHz <= 0 || stepHz <= 0) return 0
        return ((-dx * spanHz) / plotWidth / stepHz).roundToInt()
    }

    /** Toucher un point du spectre : fréquence correspondante, arrondie au pas d'accord. */
    fun frequencyAt(fraction: Float, lowHz: Long, highHz: Long): Long {
        val span = highHz - lowHz
        val raw = lowHz + (fraction.coerceIn(0f, 1f) * span).toDouble()
        val step = tuneStep(span)
        return Math.round(raw / step) * step
    }
}
