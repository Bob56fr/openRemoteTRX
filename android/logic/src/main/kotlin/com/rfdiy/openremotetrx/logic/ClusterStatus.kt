// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull

/** Ligne d'une source du Cluster DX : pastille (« green », « orange », « red » ou vide) et texte. */
data class ClusterLine(val dot: String, val text: String)

/** Ce que montre la rubrique « Cluster DX » (page : clusterStatusView). */
data class ClusterView(val health: String, val title: String, val lines: List<ClusterLine>, val stale: Boolean, val staleText: String)

/** Pastille d'un bouton de bande : nombre de spots actifs et niveau 1 (gris), 2 (orange), 3 (rouge). */
data class BandDot(val count: Int, val level: Int)

/**
 * État des flux du Cluster DX (message `module` du cluster, `kind` « cluster_status », toutes les 15 s environ) et
 * pastilles des boutons de bande, repris de la page (client.js : clusterStatusView, bandSpotLevels).
 */
object ClusterStatus {
    /** Santés connues (titre : clé `clusterstatus.title_<santé>`). */
    private val HEALTHS = setOf("green", "orange", "red", "off")
    /** Types de flux (libellé : clé `clusterstatus.type_<type>`). */
    private val TYPES = setOf("rbn", "telnet", "web")
    /** Verdicts du protocole -> pastille (libellé : clé `clusterstatus.verdict_<verdict>`). */
    private val VERDICTS = mapOf("ok" to "green", "calme" to "orange", "reserve" to "", "echec" to "red", "attente" to "orange")
    const val STALE_S = 45
    private val DOT_STEPS = listOf(15 to 3, 5 to 2, 1 to 1)      // >= 15 spots : rouge ; >= 5 : orange ; >= 1 : gris

    fun shortAge(seconds: Double?): String? {
        if (seconds == null || !seconds.isFinite()) return null
        val s = max(0, seconds.roundToInt())
        return when {
            s < 90 -> "$s s" // i18n-ok
            s < 5400 -> "${(s / 60.0).roundToInt()} min" // i18n-ok
            else -> "${(s / 3600.0).roundToInt()} h" // i18n-ok
        }
    }

    private fun JsonObject.text(key: String) = (this[key] as? JsonPrimitive)?.contentOrNull
    private fun JsonObject.number(key: String) = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull

    /** `elapsedS` : secondes depuis la réception du message (les âges s'y ajoutent). */
    fun view(data: JsonObject, elapsedS: Double): ClusterView {
        val elapsed = max(0.0, elapsedS)
        val health = data.text("health").takeIf { it in HEALTHS } ?: "red"
        val lines = ((data["sources"] as? JsonArray) ?: JsonArray(emptyList())).take(12).mapNotNull { it as? JsonObject }.map { s ->
            val verdict = s.text("verdict").orEmpty()
            val dot = VERDICTS[verdict] ?: ""
            val word = if (verdict in VERDICTS) Tr.t("clusterstatus.verdict_$verdict") else verdict.ifEmpty { "?" }
            val n = s.number("last_10min")?.roundToInt() ?: 0
            val rate = if (n >= 10) Tr.t("clusterstatus.rate_per_min", "n" to (n / 10.0).roundToInt())
            else Tr.plural("clusterstatus.rate_10min", n)
            val age = shortAge(s.number("last_spot_age_s")?.plus(elapsed))
            val parts = mutableListOf(word)
            if (verdict == "ok" || verdict == "calme") parts += listOf(rate, age?.let { Tr.t("clusterstatus.last_ago", "age" to it) } ?: Tr.t("clusterstatus.no_spot"))
            val retry = s.number("retry_in_s")
            if (verdict == "attente" && retry != null && retry > 0) parts += Tr.t("clusterstatus.retry_in", "age" to shortAge(retry))
            if (verdict == "echec") s.text("code")?.takeIf { it.isNotEmpty() }?.let { parts += Tr.t("clusterstatus.failed_code", "code" to it.take(40)) }
            val type = s.text("type")?.takeIf { it in TYPES }?.let { Tr.t("clusterstatus.type_$it") } ?: Tr.t("clusterstatus.type_other")
            ClusterLine(dot, Tr.t("clusterstatus.line", "name" to (s.text("name") ?: "?").take(40), "type" to type, "parts" to parts.joinToString(" · ")))
        }
        val stale = elapsed > STALE_S
        return ClusterView(
            health, Tr.t("clusterstatus.title_$health"), lines, stale,
            if (stale) Tr.t("clusterstatus.stale", "age" to shortAge(elapsed)) else "",
        )
    }

    /** Pastilles des boutons de bande : `bands` du message (« 20m » -> bouton « 20 »). */
    fun bandDots(data: JsonObject): Map<String, BandDot> {
        val bands = data["bands"] as? JsonObject ?: return emptyMap()
        val out = mutableMapOf<String, BandDot>()
        for (band in Radio.BANDS) {
            val count = bands.number(band.key + "m") ?: continue
            if (!count.isFinite() || count < 1) continue
            val n = min(count.roundToInt(), 999)
            out[band.key] = BandDot(n, DOT_STEPS.first { n >= it.first }.second)
        }
        return out
    }
}

/** Rubrique « Cluster DX » à l'instant `nowMs` (horloge murale), ou null si le module n'a rien dit. */
fun RigState.clusterView(nowMs: Long): ClusterView? =
    clusterStatus?.let { ClusterStatus.view(it, (nowMs - clusterStatusAtMs) / 1000.0) }

/** Pastilles des boutons de bande ; aucune si l'état du cluster est trop ancien (page : idem). */
fun RigState.bandDots(nowMs: Long): Map<String, BandDot> {
    val data = clusterStatus ?: return emptyMap()
    return if ((nowMs - clusterStatusAtMs) / 1000.0 > ClusterStatus.STALE_S) emptyMap() else ClusterStatus.bandDots(data)
}
