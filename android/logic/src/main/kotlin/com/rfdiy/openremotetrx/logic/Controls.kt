// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Command
import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.State
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

/** Bouton d'une fonction du poste (NR, NB, P.AMP, ATT, Notch, IP+, AGC, COMP, FIL, TUNER, PWR). */
data class ControlChip(val key: String, val label: String, val on: Boolean)

/** Indicateur (barre + texte) : Po, SWR, ALC, COMP, Vd, température. */
data class Meter(val key: String, val label: String, val text: String, val fraction: Float)

/**
 * Boutons et indicateurs du poste, repris de la page (client.js : view().controls, instruments, pressControl).
 * Kotlin pur ; les réglages ne sont proposés qu'en RÉCEPTION (la station refuse aussi pendant l'émission).
 */
object Controls {
    val AGC_LABELS = mapOf(0 to "AGC-OFF", 1 to "AGC-SF", 2 to "AGC-F", 3 to "AGC-S", 4 to "AGC-U", 5 to "AGC-M", 6 to "AGC-A")
    val AGC_CYCLE = listOf(2, 5, 3)                                  // FAST, MEDIUM, SLOW
    val POWER_STEPS = listOf(0.05, 0.1, 0.25, 0.5, 0.8, 1.0)
    private const val POWER_TOLERANCE = 0.015

    private fun powerStepIndex(fraction: Double): Int = POWER_STEPS.indexOfFirst { abs(it - fraction) <= POWER_TOLERANCE }

    /** « PWR 25W » si la station connaît la puissance maximale, sinon « PWR 25% ». */
    fun powerLabel(fraction: Double?, maxWatts: Int): String {
        if (fraction == null || fraction < 0) return "PWR"
        val f = powerStepIndex(fraction).let { if (it >= 0) POWER_STEPS[it] else fraction }
        if (maxWatts > 0) {
            val watts = f * maxWatts
            return "PWR " + (if (abs(watts - watts.roundToInt()) < 0.05) "${watts.roundToInt()}" else "%.1f".format(Locale.ROOT, watts)) + "W"
        }
        return "PWR ${(f * 100).roundToInt()}%"
    }

    /** Palier SUPÉRIEUR de puissance, en bouclant ; inconnue : le plus faible. */
    fun nextPower(fraction: Double?): Double {
        if (fraction == null || fraction < 0) return POWER_STEPS.first()
        val at = powerStepIndex(fraction)
        if (at >= 0) return POWER_STEPS[(at + 1) % POWER_STEPS.size]
        return POWER_STEPS.firstOrNull { it > fraction } ?: POWER_STEPS.first()
    }

    fun formatWidth(hz: Int): String =
        if (hz >= 1000) (if (hz % 1000 == 0) "${hz / 1000}" else "%.1f".format(Locale.ROOT, hz / 1000.0)) + "k" else "$hz"

    private fun nearestIndex(values: List<Int>, target: Int): Int = values.indices.minByOrNull { abs(values[it] - target) } ?: -1

    /** Préréglage FIL1/2/3 relu par la station sur le port B (state.spectrum.settings.filter), sinon null. */
    fun filterPreset(state: State?): Int? {
        val settings = state?.spectrum?.get("settings") as? JsonObject ?: return null
        return (settings["filter"] as? JsonPrimitive)?.intOrNull?.takeIf { it in 1..3 }
    }

    /** Station à port B (Icom) : la largeur par Hamlib réécrirait les préréglages du poste (CLAUDE.md, pièges). */
    private fun presetsExpected(hello: Hello?): Boolean = hello?.spectrum?.source == "civ_port"

    fun chips(hello: Hello?, state: State?): List<ControlChip> {
        val rig = state?.rig ?: return emptyList()
        val fn = rig.functions
        val lv = rig.levels
        val caps = hello?.capabilities
        val out = mutableListOf<ControlChip>()
        fun function(key: String, label: String) { fn[key]?.let { out += ControlChip(key, label, it) } }
        function("NR", "NR")
        function("NB", "NB")
        lv["PREAMP"]?.let { out += ControlChip("PREAMP", if (it > 0) "P.AMP ${it.roundToInt()}" else "P.AMP", it > 0) }
        lv["ATT"]?.let { out += ControlChip("ATT", if (it > 0) "ATT ${it.roundToInt()}" else "ATT", it > 0) }
        if ("ANF" in fn || "MN" in fn) {
            val label = if (fn["MN"] == true) "NOTCH M" else if (fn["ANF"] == true) "NOTCH A" else "NOTCH"
            out += ControlChip("NOTCH", label, fn["ANF"] == true || fn["MN"] == true)
        }
        function("AIP", "IP+")
        lv["AGC"]?.let { out += ControlChip("AGC", AGC_LABELS[it.roundToInt()] ?: "AGC", it > 0) }
        function("COMP", "COMP")
        val preset = filterPreset(state)
        val widths = rig.mode?.let { caps?.filters?.get(it) }
        val passband = rig.passbandHz
        if (preset != null) {
            out += ControlChip("FIL", "FIL$preset" + (passband?.let { " " + formatWidth(it) } ?: ""), true)
        } else if (!presetsExpected(hello) && widths != null && widths.size > 1 && passband != null && passband > 0) {
            val i = nearestIndex(widths, passband)
            val close = i >= 0 && abs(widths[i] - passband) <= maxOf(50.0, widths[i] * 0.15)
            out += ControlChip("FIL", "FIL " + formatWidth(if (close) widths[i] else passband), true)
        }
        function("TUNER", "TUNER")
        lv["RFPOWER"]?.let { out += ControlChip("PWR", powerLabel(it, hello?.maxPowerW ?: 0), true) }
        return out
    }

    /** Commandes à envoyer pour un appui sur `key` (vide si rien à faire). Notch : on éteint avant d'allumer. */
    fun press(key: String, hello: Hello?, state: State?): List<Command> {
        val rig = state?.rig ?: return emptyList()
        val fn = rig.functions
        val lv = rig.levels
        val caps = hello?.capabilities
        return when (key) {
            "PWR" -> listOf(Command.SetLevel("RFPOWER", nextPower(lv["RFPOWER"])))
            "ATT" -> {
                val on = caps?.attenuators?.firstOrNull() ?: 20
                listOf(Command.SetLevel("ATT", if ((lv["ATT"] ?: 0.0) > 0) 0 else on))
            }
            "PREAMP" -> {
                val values = listOf(0) + (caps?.preamps?.takeIf { it.isNotEmpty() } ?: listOf(10))
                val i = values.indexOf((lv["PREAMP"] ?: 0.0).roundToInt())
                listOf(Command.SetLevel("PREAMP", values[(i + 1) % values.size]))
            }
            "AGC" -> {
                val i = lv["AGC"]?.let { AGC_CYCLE.indexOf(it.roundToInt()) } ?: -1
                listOf(Command.SetLevel("AGC", AGC_CYCLE[(i + 1) % AGC_CYCLE.size]))
            }
            "NOTCH" -> {
                val order = listOf("off") + (if ("ANF" in fn) listOf("auto") else emptyList()) + (if ("MN" in fn) listOf("manual") else emptyList())
                val current = if (fn["MN"] == true) "manual" else if (fn["ANF"] == true) "auto" else "off"
                val next = order[(order.indexOf(current) + 1) % order.size]
                val want = mapOf("ANF" to (next == "auto"), "MN" to (next == "manual"))
                val off = listOf("ANF", "MN").filter { it in fn && fn[it] == true && want[it] == false }.map { Command.SetFunction(it, false) }
                val on = listOf("ANF", "MN").filter { it in fn && fn[it] != true && want[it] == true }.map { Command.SetFunction(it, true) }
                off + on
            }
            "FIL" -> {
                val preset = filterPreset(state)
                when {
                    preset != null -> listOf(Command.SpectrumSet("filter", JsonPrimitive(preset % 3 + 1)))   // FIL1 -> 2 -> 3 -> 1
                    presetsExpected(hello) -> emptyList()
                    else -> {
                        val widths = rig.mode?.let { caps?.filters?.get(it) }
                        val passband = rig.passbandHz
                        if (widths == null || widths.size < 2 || passband == null || passband <= 0) emptyList()
                        else listOf(Command.SetMode(rig.mode!!, widths[(nearestIndex(widths, passband) + 1) % widths.size]))
                    }
                }
            }
            else -> if (key in fn) listOf(Command.SetFunction(key, fn[key] != true)) else emptyList()
        }
    }

    /** Indicateurs d'émission : Po (part de la puissance maximale), SWR, ALC ; puis COMP, Vd, température s'ils existent. */
    fun meters(state: State?): List<Meter> {
        val lv = state?.rig?.levels ?: return emptyList()
        val out = mutableListOf<Meter>()
        lv["RFPOWER_METER"]?.let { val f = it.coerceIn(0.0, 1.0); out += Meter("PO", "Po", "${(f * 100).roundToInt()} %", f.toFloat()) }
        lv["SWR"]?.let { out += Meter("SWR", "SWR", "%.1f".format(Locale.ROOT, it), ((it - 1) / 2).coerceIn(0.0, 1.0).toFloat()) }
        lv["ALC"]?.let { val f = it.coerceIn(0.0, 1.0); out += Meter("ALC", "ALC", "${(f * 100).roundToInt()} %", f.toFloat()) }
        lv["COMP_METER"]?.let { out += Meter("COMP", "COMP", "%.1f dB".format(Locale.ROOT, it), (it / 30).coerceIn(0.0, 1.0).toFloat()) }
        lv["VD_METER"]?.let { out += Meter("VD", "Vd", "%.1f V".format(Locale.ROOT, it), ((it - 10) / 6).coerceIn(0.0, 1.0).toFloat()) }
        lv["TEMP_METER"]?.let { out += Meter("TEMP", "Temp", "${it.roundToInt()} °C", ((it - 20) / 50).coerceIn(0.0, 1.0).toFloat()) }
        return out
    }
}
