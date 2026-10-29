// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToLong
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** Spot du Cluster DX (module « cluster » de la station), nettoyé comme la page (spots.js : cleanSpot). */
data class Spot(
    val id: Long,
    val khz: Double,
    val hz: Long,
    val dx: String,
    val de: String,
    val mode: String,
    val modeGuessed: Boolean,
    val kind: String,
    val time: String,
    val count: Int,
    val comment: String,
    val country: String,
    val continent: String,
    val qsyMode: String,
    /** Âge à la réception (s) et instant de réception (ms) : l'âge courant en découle. */
    val age0: Double,
    val receivedMs: Long,
)

/** Étiquette d'un ou plusieurs spots sur le spectre : position (px), rangée, texte, identifiants, regroupement. */
data class SpotLabel(val x: Float, val row: Int, val text: String, val ids: List<Long>, val group: Boolean)

/** Carnet des spots reçus (page : SpotBook) ; Kotlin pur. */
class SpotBook {
    private val map = LinkedHashMap<Long, Spot>()

    fun clear() = map.clear()

    /** Message `module` du cluster (`data`) : instantané ou changements ; vrai si quelque chose a changé. */
    fun apply(data: JsonElement, nowMs: Long): Boolean {
        val obj = data as? JsonObject ?: return false
        if (obj.text("kind") != "spots") return false
        val spots = obj["spots"] as? JsonArray ?: return false
        when (obj.text("op")) {
            "snapshot" -> map.clear()
            "delta" -> Unit
            else -> return false
        }
        for (raw in spots.take(500)) Spots.clean(raw, nowMs)?.let { map[it.id] = it }
        (obj["removed"] as? JsonArray)?.forEach { id -> (id as? JsonPrimitive)?.longOrNull?.let { map.remove(it) } }
        return true
    }

    fun all(): List<Spot> = map.values.toList()

    fun get(id: Long): Spot? = map[id]

    fun visible(lowHz: Long, highHz: Long): List<Spot> = map.values.filter { it.hz in lowHz..highHz }.sortedBy { it.hz }

    private fun JsonObject.text(key: String) = (this[key] as? JsonPrimitive)?.contentOrNull
}

object Spots {
    const val FRESH_S = 120
    private const val FADE_TO = 0.35
    private const val DEFAULT_TTL_S = 900
    val KINDS = mapOf("cluster" to "DX", "rbn" to "RBN", "cb" to "CB")
    private val MODE_NAMES = mapOf("SSB" to "BLU", "AM" to "AM", "FM" to "FM", "FREEDV" to "FreeDV", "CW" to "CW")
    private val CONTROL = Regex("[\\u0000-\\u001f\\u007f\\u202a-\\u202e\\u2066-\\u2069]")

    private fun text(obj: JsonObject, key: String, maxLen: Int): String =
        ((obj[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: "").replace(CONTROL, "").take(maxLen)

    /** Spot reçu (clés courtes) -> Spot sûr ; null s'il est inutilisable. */
    fun clean(raw: JsonElement, nowMs: Long): Spot? {
        val o = raw as? JsonObject ?: return null
        val id = (o["id"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: return null
        val f = (o["f"] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull?.takeIf { it.isFinite() && it > 0 } ?: return null
        val dx = text(o, "dx", 20).ifEmpty { return null }
        val kind = text(o, "k", 10).takeIf { it in KINDS } ?: "cluster"
        val count = (o["n"] as? JsonPrimitive)?.intOrNull?.takeIf { it > 0 } ?: 1
        val age = (o["age"] as? JsonPrimitive)?.doubleOrNull?.takeIf { it.isFinite() && it >= 0 } ?: 0.0
        return Spot(
            id = id, khz = f, hz = (f * 1000).roundToLong(), dx = dx, de = text(o, "de", 20), mode = text(o, "m", 10),
            modeGuessed = (o["mg"] as? JsonPrimitive)?.booleanOrNull == true || (o["mg"] as? JsonPrimitive)?.intOrNull == 1,
            kind = kind, time = text(o, "t", 4), count = count, comment = text(o, "c", 80), country = text(o, "co", 40),
            continent = text(o, "ct", 2), qsyMode = text(o, "q", 10), age0 = age, receivedMs = nowMs,
        )
    }

    /** Heure d'arrivée du spot (ms, horloge murale) : sa réception moins l'âge qu'il avait alors. */
    fun arrivalMs(spot: Spot): Long = spot.receivedMs - (spot.age0 * 1000).roundToLong()

    /** Message « recent » du cluster (station 0.56.0+) : derniers spots toutes bandes, le plus récent en tête ; null si autre message. */
    fun recentOf(data: JsonElement, nowMs: Long): List<Spot>? {
        val obj = data as? JsonObject ?: return null
        if ((obj["kind"] as? JsonPrimitive)?.contentOrNull != "recent") return null
        val spots = obj["spots"] as? JsonArray ?: return emptyList()
        return recent(spots.take(60).mapNotNull { clean(it, nowMs) })
    }

    /** « Tout afficher » de la rubrique Cluster DX : les `n` derniers spots, le plus récent en tête. */
    fun recent(spots: List<Spot>, n: Int = 30): List<Spot> = spots.sortedByDescending { arrivalMs(it) }.take(n)

    /** Source d'un spot : type (DX, RBN, CB…) et indicatif de celui qui l'a signalé. */
    fun sourceLabel(spot: Spot): String = kindLabel(spot.kind) + if (spot.de.isNotEmpty()) " de ${spot.de}" else ""

    fun ageSeconds(spot: Spot, nowMs: Long): Double = spot.age0 + max(0.0, (nowMs - spot.receivedMs) / 1000.0)

    /** Opacité : 1 les 2 premières minutes, puis estompage jusqu'à 0,35 en fin de vie. */
    fun opacity(ageS: Double, ttlS: Int = DEFAULT_TTL_S): Float {
        val ttl = if (ttlS > FRESH_S) ttlS else DEFAULT_TTL_S
        if (ageS <= FRESH_S) return 1f
        val t = min(1.0, (ageS - FRESH_S) / (ttl - FRESH_S))
        return (Math.round((1 - t * (1 - FADE_TO)) * 100) / 100.0).toFloat()
    }

    fun ageLabel(ageS: Double): String {
        if (ageS < 60) return "à l'instant"
        val min = (ageS / 60).toInt()
        return if (min < 60) "il y a $min min" else "il y a ${min / 60} h ${"%02d".format(min % 60)}"
    }

    fun modeLabel(spot: Spot): String {
        val name = MODE_NAMES[spot.mode] ?: spot.mode.ifEmpty { "?" }
        return if (spot.modeGuessed) "$name (supposé)" else name
    }

    fun kindLabel(kind: String): String = KINDS[kind] ?: "DX"

    /** Liste des spots : par fréquence, ou par âge (les plus récents d'abord) comme la page. */
    fun sortList(spots: List<Spot>, byAge: Boolean, nowMs: Long): List<Spot> =
        if (byAge) spots.sortedWith(compareBy<Spot>({ ageSeconds(it, nowMs) }, { it.hz })) else spots.sortedBy { it.hz }

    /** Texte de la santé des sources (page : healthLabel). */
    fun healthLabel(state: String?): String = when (state) {
        "green" -> "Cluster DX : toutes les sources connectées"
        "orange" -> "Cluster DX : sources en partie connectées"
        "red" -> "Cluster DX : aucune source connectée"
        "off" -> "Cluster DX désactivé"
        else -> ""
    }

    /** Fréquence et mode du QSY ; `adapt` = mode utilisable par ce poste (Radio.adaptMode) ou null. */
    fun qsyTarget(spot: Spot, adapt: (String) -> String?): Pair<Long, String?> =
        spot.hz to spot.qsyMode.takeIf { it.isNotEmpty() }?.let(adapt)

    /**
     * Étiquettes rangées l'une sous l'autre quand elles se chevauchent (3 rangées), puis regroupées en « +N » sur une
     * rangée de plus (page : layoutLabels). `spots` triés par fréquence.
     */
    fun layoutLabels(
        spots: List<Spot>, lowHz: Long, highHz: Long, widthPx: Float,
        rows: Int = 3, charPx: Float = 7f, padPx: Float = 10f, gapPx: Float = 4f,
    ): List<SpotLabel> {
        val span = (highHz - lowHz).toDouble()
        if (span <= 0 || widthPx <= 0) return emptyList()
        fun width(text: String) = text.length * charPx + padPx
        val right = FloatArray(rows) { Float.NEGATIVE_INFINITY }
        val placed = mutableListOf<SpotLabel>()
        val left = mutableListOf<Pair<Spot, Float>>()
        for (s in spots) {
            val x = ((s.hz - lowHz) / span * widthPx).toFloat()
            val w = width(s.dx)
            val row = (0 until rows).firstOrNull { x - w / 2 >= right[it] + gapPx }
            if (row == null) { left += s to x; continue }
            right[row] = x + w / 2
            placed += SpotLabel(x, row, s.dx, listOf(s.id), false)
        }
        class Group(val x0: Float, var x1: Float, val ids: MutableList<Long>)
        val groups = mutableListOf<Group>()
        for ((spot, x) in left) {
            val last = groups.lastOrNull()
            if (last != null && x - last.x1 <= width("+99")) { last.ids += spot.id; last.x1 = x } else groups += Group(x, x, mutableListOf(spot.id))
        }
        var groupRight = Float.NEGATIVE_INFINITY
        for (g in groups) {
            val x = (g.x0 + g.x1) / 2
            val text = "+${g.ids.size}"
            val w = width(text)
            val prev = placed.lastOrNull()
            if (x - w / 2 < groupRight + gapPx && prev != null && prev.group) {
                val ids = prev.ids + g.ids
                placed[placed.size - 1] = prev.copy(ids = ids, text = "+${ids.size}")
                continue
            }
            groupRight = x + w / 2
            placed += SpotLabel(x, rows, text, g.ids.toList(), true)
        }
        return placed
    }
}
