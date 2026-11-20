// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import java.util.Locale

/**
 * Mesure de TOS : ce que l'écran de l'application montre des messages `swr` et des réponses `swr_plan` / `swr_last`
 * (page : onSwr, swr.js restoredLines / legendLines ; mêmes textes).
 */
data class SwrPoint(val hz: Long, val status: String, val swr: Double?, val powerW: Double?)

data class SwrResult(
    val points: List<SwrPoint>, val best: SwrPoint?, val reason: String, val detail: String, val warning: String,
    val powerW: Double?, val powerPct: Double, val fmMode: String, val restored: JsonObject?, val differences: List<String>,
    val atS: Double,
)

/** Plan de la station (réponse à swr_plan), déjà lu : complément du texte du plan et plafond de puissance. */
data class SwrPlanView(val text: String, val maxPowerPct: Double)

data class SwrProgress(val state: String, val total: Int, val points: List<SwrPoint>, val result: SwrResult?) {
    val running: Boolean get() = state !in setOf("done", "cut", "failed", "cancelled")
}

object SwrUi {
    private fun JsonObject.text(key: String) = (this[key] as? JsonPrimitive)?.contentOrNull.orEmpty()
    private fun JsonObject.num(key: String) = (this[key] as? JsonPrimitive)?.doubleOrNull

    fun points(raw: JsonElement?): List<SwrPoint> = (raw as? JsonArray).orEmpty().mapNotNull { item ->
        val o = item as? JsonObject ?: return@mapNotNull null
        val hz = (o["hz"] as? JsonPrimitive)?.longOrNull ?: return@mapNotNull null
        SwrPoint(hz, o.text("status"), o.num("swr"), o.num("power_w"))
    }

    fun result(raw: JsonElement?): SwrResult? {
        val o = raw as? JsonObject ?: return null
        val pts = points(o["points"])
        val best = (o["best"] as? JsonObject)?.let { b -> points(JsonArray(listOf(b))).firstOrNull() }
        return SwrResult(pts, best, o.text("reason"), o.text("detail"), o.text("warning"), o.num("power_w"), o.num("power_pct") ?: 0.0,
            o.text("fm_mode").ifEmpty { "FM" }, o["restored"] as? JsonObject,
            (o["differences"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }, o.num("at") ?: 0.0)
    }

    fun progress(raw: JsonObject): SwrProgress =
        SwrProgress(raw.text("state"), (raw.num("total") ?: 0.0).toInt(), points(raw["points"]), result(raw["result"]))

    fun freqLabel(hz: Long): String = String.format(Locale.ROOT, if (hz % 1000 != 0L) "%.4f" else "%.3f", hz / 1e6)

    fun swrText(swr: Double): String = if (swr > 5) "> 5" else Format.decimal(swr, 2)

    /** « État du poste remis » : ce qui a été relu, puis les écarts à corriger à la main (page : restoredLines). */
    fun restoredLines(result: SwrResult?): Pair<List<String>, List<String>> {
        val r = result?.restored
        val out = mutableListOf<String>()
        if (r != null) {
            (r["frequency_hz"] as? JsonPrimitive)?.longOrNull?.let {
                out += Tr.t("swrui.restored_frequency", "mhz" to Format.decimal(it / 1e6, 4))
            }
            r.text("mode").takeIf { it.isNotEmpty() }?.let { mode ->
                val pb = (r["passband_hz"] as? JsonPrimitive)?.longOrNull ?: 0
                out += if (pb > 0) Tr.t("swrui.restored_mode_passband", "mode" to Radio.modeLabel(mode), "hz" to pb)
                else Tr.t("swrui.restored_mode", "mode" to Radio.modeLabel(mode))
            }
            r.num("rfpower")?.let { out += Tr.t("swrui.restored_power", "pct" to Math.round(it * 100)) }
            (r["tuner"] as? JsonPrimitive)?.booleanOrNull?.let { out += Tr.t(if (it) "swrui.restored_tuner_on" else "swrui.restored_tuner_off") }
        }
        if (out.isEmpty()) out += Tr.t("swrui.not_restored")
        return out to result?.differences.orEmpty()
    }

    /** Pied de l'image exportée (ANONYME : ni indicatif ni station) ; page : legendLines. */
    fun legendLines(result: SwrResult?, name: String, `when`: String): List<String> {
        val lines = mutableListOf(name.trim().ifEmpty { Tr.t("swrui.legend_title") })
        val parts = mutableListOf<String>()
        if (`when`.isNotEmpty()) parts += `when`
        if (result != null) {
            val power = result.powerW?.let { w -> (if (w == Math.floor(w)) w.toLong().toString() else w.toString()) + " W" } ?: "${Math.round(result.powerPct)} %"
            parts += Tr.t("swrui.legend_power_mode", "power" to power, "mode" to Radio.modeLabel(result.fmMode))
            result.best?.swr?.let { parts += Tr.t("swrui.legend_best", "swr" to swrText(it), "mhz" to freqLabel(result.best.hz)) }
        }
        if (parts.isNotEmpty()) lines += parts.joinToString(" · ")
        return lines
    }

    /** Plan de la station : « ; 15 W en FM-D ; N point(s) hors des bandes de la station, sautés ; environ 30 s … » (page : swrPlanText). */
    fun planView(plan: JsonObject?): SwrPlanView? {
        if (plan == null) return null
        val skipped = (plan["points"] as? JsonArray).orEmpty().count { ((it as? JsonObject)?.get("status") as? JsonPrimitive)?.contentOrNull == "out_of_band" }
        val fm = (plan["fm_mode"] as? JsonPrimitive)?.contentOrNull
        val watts = plan.num("power_w")?.let { w -> (if (w == Math.floor(w)) w.toLong().toString() else w.toString()) + " W" }
        val mode = fm?.let { Radio.modeLabel(it) }
        val text = when {
            watts != null && mode != null -> " ; " + Tr.t("swrui.plan_power_mode", "power" to watts, "mode" to mode)
            watts != null -> " ; $watts"
            mode != null -> " " + Tr.t("swrui.plan_mode", "mode" to mode)
            else -> ""
        } +
            (if (skipped > 0) " ; " + Tr.t("swrui.plan_skipped", "n" to skipped) else "") +
            (plan.num("estimated_s")?.let { " ; " + Tr.t("swrui.plan_duration", "s" to Math.round(it)) } ?: "") +
            (if ((plan["calibration_needed"] as? JsonPrimitive)?.booleanOrNull == true) " " + Tr.t("swrui.plan_calibration") else "")
        return SwrPlanView(text, plan.num("max_power_pct") ?: 50.0)
    }

    /** Résumé sous le graphique (page : swrSummary). */
    fun summary(result: SwrResult?): String {
        val best = result?.best
        val head = if (best?.swr != null) Tr.t("swrui.summary_best", "swr" to swrText(best.swr), "mhz" to freqLabel(best.hz))
        else Tr.t("swrui.summary_none")
        val why = if (result != null && result.reason != "done") " " + Tr.t("swrui.summary_cut", "why" to Texts.cut(result.detail)) else ""
        val unstable = if (result?.warning == "swr_unstable") " " + Tr.t("swrui.summary_unstable") else ""
        return head + why + unstable
    }
}
