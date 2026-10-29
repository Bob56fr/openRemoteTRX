// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.put
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Égaliseur paramétrique et effets de voix de l'application (docs/egaliseur-voix.md), MÊMES réglages que la page
 * (voice.js : defaults, validate, préréglages, format JSON « openremotetrx-voice » commun). Le calcul du son est dans
 * VoiceDsp.
 */
data class EqBand(val hz: Double, val gainDb: Double, val q: Double, val shelf: Boolean)
data class Chorus(val on: Boolean = false, val type: String = "classic", val mix: Double = 30.0, val rateHz: Double = 0.8, val depthMs: Double = 3.0)
data class Reverb(val on: Boolean = false, val type: String = "room", val mix: Double = 20.0, val seconds: Double = 0.5)
data class MicSettings(val gainDb: Double = 0.0, val gateOn: Boolean = false, val gateDb: Double = -50.0)

data class VoiceSettings(
    val enabled: Boolean = false,
    val highpassHz: Double = 100.0,
    val lowpassHz: Double = 3000.0,
    val bands: List<EqBand> = VoiceEq.BANDS_HZ.mapIndexed { i, hz -> EqBand(hz, 0.0, 1.4, i == 0 || i == VoiceEq.BANDS_HZ.lastIndex) },
    val chorus: Chorus = Chorus(),
    val reverb: Reverb = Reverb(),
    val mic: MicSettings = MicSettings(),
)

data class EffectType(val label: String, val voices: Int = 1, val delayMs: Double = 0.0, val seconds: Double = 0.0, val bright: Double = 0.0)

object VoiceEq {
    val BANDS_HZ = listOf(100.0, 160.0, 250.0, 370.0, 570.0, 880.0, 1350.0, 2100.0, 3250.0, 5000.0)
    const val GAIN_MAX_DB = 12.0
    const val Q_MIN = 0.3
    const val Q_MAX = 8.0
    /** Plafond des crêtes (dBFS) : le limiteur est TOUJOURS actif, même égaliseur éteint. */
    const val LIMIT_DBFS = -3.0
    const val RECORD_MAX_S = 30
    const val FORMAT = "openremotetrx-voice"

    val CHORUS_TYPES = linkedMapOf(
        "classic" to EffectType("Classique", voices = 1, delayMs = 18.0),
        "ensemble" to EffectType("Ensemble 3 voix", voices = 3, delayMs = 22.0),
        "double" to EffectType("Doublage", voices = 1, delayMs = 32.0),
    )
    val REVERB_TYPES = linkedMapOf(
        "room" to EffectType("Pièce", seconds = 0.5, bright = 0.5),
        "hall" to EffectType("Salle", seconds = 1.8, bright = 0.35),
        "plate" to EffectType("Plaque", seconds = 1.2, bright = 0.8),
        "spring" to EffectType("Ressort", seconds = 0.9, bright = 0.6),
    )

    /** Préréglages de la page (voice.js, PRESETS), même ordre et mêmes valeurs. */
    val PRESETS: LinkedHashMap<String, Pair<String, () -> VoiceSettings>> = linkedMapOf(
        "neutre" to ("Neutre" to { VoiceSettings(enabled = true) }),
        "dx" to ("DX (aigus présents)" to { withGains(VoiceSettings(enabled = true, highpassHz = 250.0, lowpassHz = 2800.0), listOf(-6, -4, -2, 0, 0, 1, 3, 5, 4, 0)) }),
        "ragchew" to ("Ragchew (voix chaude)" to { withGains(VoiceSettings(enabled = true, highpassHz = 100.0, lowpassHz = 3000.0), listOf(2, 3, 2, 1, 0, 0, 1, 1, 0, -2)) }),
    )

    private fun withGains(s: VoiceSettings, gains: List<Int>) = s.copy(bands = s.bands.mapIndexed { i, b -> b.copy(gainDb = gains[i].toDouble()) })

    private fun num(v: Any?, lo: Double, hi: Double, dflt: Double): Double {
        val d = (v as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull ?: return dflt
        return if (d.isFinite()) d.coerceIn(lo, hi) else dflt
    }

    private fun flag(v: Any?): Boolean = (v as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull == true

    private fun text(v: Any?): String? = (v as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Réglages lus (préférences, fichier importé) -> réglages sûrs et complets ; jamais d'exception (voice.js : validate). */
    fun validate(raw: JsonObject?): VoiceSettings {
        val d = VoiceSettings()
        if (raw == null) return d
        val hp = num(raw["highpassHz"], 20.0, 1000.0, d.highpassHz)
        var lp = num(raw["lowpassHz"], 1500.0, 8000.0, d.lowpassHz)
        if (lp <= hp + 300) lp = minOf(8000.0, hp + 300)
        val bands = (raw["bands"] as? JsonArray).orEmpty()
        val out = d.bands.mapIndexed { i, b ->
            val r = bands.getOrNull(i) as? JsonObject ?: JsonObject(emptyMap())
            val edge = i == 0 || i == BANDS_HZ.lastIndex
            EqBand(num(r["hz"], b.hz / 1.5, b.hz * 1.5, b.hz), num(r["gainDb"], -GAIN_MAX_DB, GAIN_MAX_DB, 0.0),
                num(r["q"], Q_MIN, Q_MAX, b.q), if (edge) (r["shelf"] as? JsonPrimitive)?.booleanOrNull != false else false)
        }
        val c = raw["chorus"] as? JsonObject ?: JsonObject(emptyMap())
        val r = raw["reverb"] as? JsonObject ?: JsonObject(emptyMap())
        val m = raw["mic"] as? JsonObject ?: JsonObject(emptyMap())
        return VoiceSettings(
            enabled = flag(raw["enabled"]), highpassHz = hp, lowpassHz = lp, bands = out,
            chorus = Chorus(flag(c["on"]), text(c["type"])?.takeIf { it in CHORUS_TYPES } ?: d.chorus.type, num(c["mix"], 0.0, 100.0, d.chorus.mix),
                num(c["rateHz"], 0.1, 5.0, d.chorus.rateHz), num(c["depthMs"], 0.5, 8.0, d.chorus.depthMs)),
            reverb = Reverb(flag(r["on"]), text(r["type"])?.takeIf { it in REVERB_TYPES } ?: d.reverb.type, num(r["mix"], 0.0, 100.0, d.reverb.mix),
                num(r["seconds"], 0.2, 4.0, d.reverb.seconds)),
            mic = MicSettings(num(m["gainDb"], -12.0, 20.0, 0.0), flag(m["gateOn"]), num(m["gateDb"], -80.0, -20.0, -50.0)),
        )
    }

    fun validate(s: VoiceSettings): VoiceSettings = validate(toJson(s))

    fun toJson(s: VoiceSettings): JsonObject = buildJsonObject {
        put("version", 1); put("enabled", s.enabled); put("highpassHz", s.highpassHz); put("lowpassHz", s.lowpassHz)
        put("bands", buildJsonArray {
            s.bands.forEach { b -> add(buildJsonObject { put("hz", b.hz); put("gainDb", b.gainDb); put("q", b.q); put("shelf", b.shelf) }) }
        })
        put("chorus", buildJsonObject { put("on", s.chorus.on); put("type", s.chorus.type); put("mix", s.chorus.mix); put("rateHz", s.chorus.rateHz); put("depthMs", s.chorus.depthMs) })
        put("reverb", buildJsonObject { put("on", s.reverb.on); put("type", s.reverb.type); put("mix", s.reverb.mix); put("seconds", s.reverb.seconds) })
        put("mic", buildJsonObject { put("gainDb", s.mic.gainDb); put("gateOn", s.mic.gateOn); put("gateDb", s.mic.gateDb) })
    }

    private val json = Json { prettyPrint = true }

    /** Format commun page / application (docs/egaliseur-voix.md § 6). */
    fun exportJson(s: VoiceSettings): String =
        json.encodeToString(JsonObject.serializer(), JsonObject(mapOf("format" to JsonPrimitive(FORMAT)) + toJson(validate(s))))

    /** Fichier importé ; IllegalArgumentException s'il n'est pas un réglage de voix openRemoteTRX. */
    fun importJson(text: String): VoiceSettings {
        val raw = runCatching { Json.parseToJsonElement(text) as? JsonObject }.getOrNull()
        require(raw != null && text(raw["format"]) == FORMAT) { "ce fichier n'est pas un réglage de voix openRemoteTRX" }
        return validate(raw)
    }

    /** Coefficients normalisés (a0 = 1) de l'« Audio EQ Cookbook » : [b0, b1, b2, a1, a2] (voice.js : biquad). */
    fun biquad(type: String, f0: Double, q: Double, gainDb: Double, fs: Double): DoubleArray {
        val a = 10.0.pow(gainDb / 40)
        val w0 = 2 * PI * f0 / fs
        val c = cos(w0)
        val alpha = sin(w0) / (2 * q)
        val (b, den) = when (type) {
            "peaking" -> doubleArrayOf(1 + alpha * a, -2 * c, 1 - alpha * a) to doubleArrayOf(1 + alpha / a, -2 * c, 1 - alpha / a)
            "lowshelf", "highshelf" -> {
                val s = if (type == "lowshelf") 1 else -1
                val k = 2 * sqrt(a) * alpha
                doubleArrayOf(a * ((a + 1) - s * (a - 1) * c + k), s * 2 * a * ((a - 1) - s * (a + 1) * c), a * ((a + 1) - s * (a - 1) * c - k)) to
                    doubleArrayOf((a + 1) + s * (a - 1) * c + k, -s * 2 * ((a - 1) + s * (a + 1) * c), (a + 1) + s * (a - 1) * c - k)
            }
            "highpass" -> doubleArrayOf((1 + c) / 2, -(1 + c), (1 + c) / 2) to doubleArrayOf(1 + alpha, -2 * c, 1 - alpha)
            "lowpass" -> doubleArrayOf((1 - c) / 2, 1 - c, (1 - c) / 2) to doubleArrayOf(1 + alpha, -2 * c, 1 - alpha)
            else -> throw IllegalArgumentException("filtre inconnu : $type")
        }
        return doubleArrayOf(b[0] / den[0], b[1] / den[0], b[2] / den[0], den[1] / den[0], den[2] / den[0])
    }

    fun bandType(b: EqBand): String = when {
        !b.shelf -> "peaking"
        b.hz <= BANDS_HZ[0] * 1.5 -> "lowshelf"
        else -> "highshelf"
    }
}
