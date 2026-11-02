// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Host
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Santé de la machine de la station (`state.host`, opérateurs seulement) : petit bargraph à gauche de « Muet », comme
 * la page (client.js : hostView). Rouge à 90 % de la barre (station : hostinfo.py).
 */
data class HostHealth(val fraction: Float, val level: String, val summary: String) {
    companion object {
        private val LEVELS = setOf("ok", "warn", "bad")

        fun of(host: Host?, listener: Boolean): HostHealth? {
            val load = host?.load ?: return null
            if (listener) return null
            val parts = listOfNotNull(
                host.cpuPct?.let { "processeur $it %" }, host.memPct?.let { "mémoire $it %" },
                host.diskPct?.let { "disque $it %" }, host.tempC?.let { "$it °C" },
                if (host.throttled == true) "Pi RALENTI (alimentation ou chaleur)" else null,
            )
            return HostHealth(load.coerceIn(0.0, 1.0).toFloat(), if (host.level in LEVELS) host.level else "ok",
                parts.joinToString(", ").ifEmpty { "mesures indisponibles" })
        }
    }
}

/** Rubrique de la synthèse du matériel (réponse à host_info), rédigée par la station : affichée telle quelle. */
data class HostSection(val title: String, val rows: List<Pair<String, String>>) {
    companion object {
        /** `sections` de la réponse ; null si absent ou illisible. Lignes mal formées ignorées. */
        fun parse(raw: JsonElement?): List<HostSection>? {
            val list = raw as? JsonArray ?: return null
            return list.mapNotNull { item ->
                val obj = item as? JsonObject ?: return@mapNotNull null
                val title = (obj["title"] as? JsonPrimitive)?.contentOrNull ?: return@mapNotNull null
                val rows = (obj["rows"] as? JsonArray).orEmpty().mapNotNull { row ->
                    val cells = (row as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                    if (cells != null && cells.size >= 2) cells[0] to cells[1] else null
                }
                HostSection(title, rows)
            }
        }
    }
}
