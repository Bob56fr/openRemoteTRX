// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull

/**
 * Activité FreeDV (station 0.125.0+, module « freedv_activity », docs/protocole.md § 17) : `data` du message de module
 * `kind: "freedv_activity"`, envoyé toutes les 10 s à TOUS les clients. Lu champ par champ : une entrée illisible est
 * ignorée (comme la page), jamais une erreur. `null` dans un nombre = absent ou mal formé.
 */
data class FreedvActivity(
    val status: String,
    val message: String,
    val total: Int?,
    val locator: Boolean,
    val t: Double?,
    val freqs: List<Freq>,
) {
    /** `f` en Hz (entier > 0 : sinon la ligne est absente de `freqs`). */
    data class Freq(val f: Long, val note: Double?, val tx: List<Tx>, val rx: List<Rx>)
    data class Tx(val c: String?, val km: Int?, val on: Boolean, val min: Int?, val m: String?)
    data class Rx(val c: String?, val km: Int?, val snr: Double?, val m: String?)

    companion object {
        const val KIND = "freedv_activity"

        /** `data` d'un message de module -> activité ; null si ce n'est pas une activité FreeDV. */
        fun of(data: JsonElement?): FreedvActivity? {
            val o = data as? JsonObject ?: return null
            if (o.str("kind") != KIND) return null
            val freqs = (o["freqs"] as? JsonArray).orEmpty().mapNotNull { item ->
                val g = item as? JsonObject ?: return@mapNotNull null
                val f = g.integer("f")?.takeIf { it > 0 } ?: return@mapNotNull null
                Freq(
                    f = f,
                    note = g.finite("note"),
                    tx = (g["tx"] as? JsonArray).orEmpty().mapNotNull { e ->
                        val x = e as? JsonObject ?: return@mapNotNull null
                        Tx(x.str("c"), x.integer("km")?.toInt(), (x["on"] as? JsonPrimitive)?.booleanOrNull == true,
                           x.integer("min")?.toInt(), x.str("m"))
                    },
                    rx = (g["rx"] as? JsonArray).orEmpty().mapNotNull { e ->
                        val x = e as? JsonObject ?: return@mapNotNull null
                        Rx(x.str("c"), x.integer("km")?.toInt(), x.finite("snr"), x.str("m"))
                    },
                )
            }
            return FreedvActivity(
                status = o.str("status").orEmpty(),
                message = o.str("message").orEmpty(),
                total = o.integer("total")?.toInt(),
                locator = (o["locator"] as? JsonPrimitive)?.booleanOrNull == true,
                t = o.finite("t"),
                freqs = freqs,
            )
        }

        private fun JsonObject.str(key: String): String? =
            (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull

        private fun JsonObject.finite(key: String): Double? =
            (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull?.takeIf { it.isFinite() }

        /** Nombre entier (comme Number.isInteger de JavaScript : 4.0 compte, 4.5 non). */
        private fun JsonObject.integer(key: String): Long? =
            finite(key)?.takeIf { it == Math.floor(it) && Math.abs(it) < 9e15 }?.toLong()
    }
}
