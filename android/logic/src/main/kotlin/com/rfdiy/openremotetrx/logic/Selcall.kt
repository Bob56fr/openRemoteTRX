// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

/** Dernier appel reçu par la station : code, décalage d'accord, SNR, heure Unix (s). */
data class SelcallCall(val code: String, val deltaHz: Double, val snrDb: Double, val at: Double)

/** État du SELCALL de la station (`hello.selcall`, message `selcall`) ; docs/selcall-cahier-des-charges.md. */
data class SelcallStatus(
    val state: String,
    val code: String,
    val history: List<String>,
    val filterMode: String,
    val attenuationDb: Int,
    val lastCall: SelcallCall?,
    /** Trame émise en fin d'émission à la place du roger bip. */
    val sendOnTxEnd: Boolean = false,
    /** Appel manuel en cours : « 1/3 »…, sinon vide. */
    val sending: String = "",
) {
    val disabled get() = state == DISABLED
    val open get() = state == OPEN

    /** Indicateur de l'afficheur : « SEL 4721 » (veille), « SEL OUVERT » ; null si désactivé (comme la page). */
    val indicator: String? get() = when (state) {
        OPEN -> "SEL OUVERT"
        STANDBY -> "SEL $code"
        else -> null
    }

    companion object {
        const val DISABLED = "disabled"
        const val STANDBY = "standby"
        const val OPEN = "open"
        val STATE_LABELS = mapOf(
            DISABLED to "désactivé : son reçu normal", STANDBY to "VEILLE : son coupé jusqu'à l'appel du code",
            OPEN to "OUVERT : appel reçu, son transmis",
        )
        val FILTER_MODES = listOf("attenuate" to "atténuées", "mute" to "coupées", "chime" to "coupées + carillon")

        private fun JsonObject.text(key: String) = (this[key] as? JsonPrimitive)?.contentOrNull

        fun parse(obj: JsonObject?): SelcallStatus? {
            if (obj == null || obj.isEmpty()) return null
            val state = obj.text("state")?.takeIf { it in STATE_LABELS } ?: return null
            val call = (obj["last_call"] as? JsonObject)?.let { c ->
                val code = c.text("code")?.takeIf { SelcallTones.validCode(it) } ?: return@let null
                SelcallCall(code, (c["delta_hz"] as? JsonPrimitive)?.doubleOrNull ?: 0.0,
                    (c["snr_db"] as? JsonPrimitive)?.doubleOrNull ?: 0.0, (c["at"] as? JsonPrimitive)?.doubleOrNull ?: 0.0)
            }
            return SelcallStatus(
                state = state,
                code = obj.text("code")?.takeIf { SelcallTones.validCode(it) }.orEmpty(),
                history = (obj["history"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                    .filter { SelcallTones.validCode(it) }.take(50),
                filterMode = obj.text("filter_mode")?.takeIf { m -> FILTER_MODES.any { it.first == m } } ?: "attenuate",
                attenuationDb = (obj["attenuation_db"] as? JsonPrimitive)?.intOrNull?.coerceIn(6, 60) ?: 20,
                lastCall = call,
                sendOnTxEnd = (obj["send_on_tx_end"] as? JsonPrimitive)?.contentOrNull == "true",
                sending = obj.text("sending")?.take(8).orEmpty(),
            )
        }
    }
}

/**
 * Trame SELCALL et fichier de test, comme la station (selcall/protocol.py, signal.py) et la page (selcall.js) :
 * mêmes tons vérifiés par tests/protocol/selcall_vectors.json. Fichier de test : 2 s de silence, la trame 3 fois
 * séparées de 0,5 s, puis 0,5 s ; WAV mono 16 bits.
 */
object SelcallTones {
    const val F0_HZ = 1000.0
    const val PILOT_S = 1.0
    const val SYMBOL_S = 0.3
    const val RAMP_S = 0.005
    const val LEVEL_DBFS = -6.0
    private const val REPEAT = "R"

    fun validCode(code: String?): Boolean = code != null && code.length in 3..8 && code.all { it in '0'..'9' }

    /** Chiffres puis contrôle (somme modulo 10), chaque répétition remplacée par R : « 4477 » -> 4 R 7 R 2. */
    fun symbols(code: String): List<String> {
        require(validCode(code)) { "code SELCALL : 3 à 8 chiffres" }
        val raw = code.map { it.toString() } + (code.sumOf { it - '0' } % 10).toString()
        return raw.mapIndexed { i, s -> if (i > 0 && s == raw[i - 1]) REPEAT else s }
    }

    fun symbolHz(s: String): Double = if (s == REPEAT) F0_HZ + 1200 else F0_HZ + 200 + 100 * s.toInt()

    /** (Hz, s) : pilote puis symboles. */
    fun tones(code: String): List<Pair<Double, Double>> = listOf(F0_HZ to PILOT_S) + symbols(code).map { symbolHz(it) to SYMBOL_S }

    fun frameSamples(code: String, rate: Int): FloatArray {
        val plan = tones(code)
        val total = plan.sumOf { (it.second * rate).roundToInt() }
        val out = FloatArray(total)
        val amp = 10.0.pow(LEVEL_DBFS / 20)
        val rampN = max(1, (RAMP_S * rate).roundToInt())
        var phase = 0.0
        var pos = 0
        for ((hz, d) in plan) {
            val n = (d * rate).roundToInt()
            for (i in 0 until n) {
                phase += 2 * PI * hz / rate
                val env = when {
                    i < rampN -> 0.5 - 0.5 * cos(PI * i / rampN)
                    i >= n - rampN -> 0.5 - 0.5 * cos(PI * (n - 1 - i) / rampN)
                    else -> 1.0
                }
                out[pos + i] = (amp * env * sin(phase)).toFloat()
            }
            phase %= 2 * PI
            pos += n
        }
        return out
    }

    fun testSamples(code: String, rate: Int = 48_000, leadS: Double = 2.0, repeat: Int = 3, gapS: Double = 0.5): FloatArray {
        val frame = frameSamples(code, rate)
        val lead = (leadS * rate).roundToInt()
        val gap = (gapS * rate).roundToInt()
        val tail = (0.5 * rate).roundToInt()
        val out = FloatArray(lead + repeat * frame.size + (repeat - 1) * gap + tail)
        for (k in 0 until repeat) frame.copyInto(out, lead + k * (frame.size + gap))
        return out
    }

    fun wavBytes(samples: FloatArray, rate: Int): ByteArray {
        val n = samples.size
        val out = ByteArray(44 + 2 * n)
        fun text(o: Int, s: String) = s.forEachIndexed { i, c -> out[o + i] = c.code.toByte() }
        fun u32(o: Int, v: Int) { for (i in 0..3) out[o + i] = (v ushr (8 * i)).toByte() }
        fun u16(o: Int, v: Int) { out[o] = v.toByte(); out[o + 1] = (v ushr 8).toByte() }
        text(0, "RIFF"); u32(4, 36 + 2 * n); text(8, "WAVE"); text(12, "fmt ")
        u32(16, 16); u16(20, 1); u16(22, 1); u32(24, rate); u32(28, rate * 2); u16(32, 2); u16(34, 16)
        text(36, "data"); u32(40, 2 * n)
        for (i in 0 until n) u16(44 + 2 * i, (max(-1f, min(1f, samples[i])) * 32767).roundToInt())
        return out
    }

    fun testWav(code: String, rate: Int = 48_000): ByteArray = wavBytes(testSamples(code, rate), rate)
}
