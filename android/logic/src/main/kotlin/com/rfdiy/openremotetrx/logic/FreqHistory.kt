// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.abs

/** Fréquence où le poste est resté (fenêtre de saisie de la fréquence, étape 410). */
data class RecentFreq(val hz: Long, val mode: String)

/**
 * Dix dernières fréquences « utilisées » : le poste y est resté au moins [DWELL_MS] avec le même mode, quelle que soit
 * l'origine du changement (application, page, bouton du poste). Gardées sur le téléphone, une liste par station.
 * Kotlin pur (compilé aussi par openRemoteTRX Lite).
 */
object FreqHistory {
    const val MAX = 10
    const val DWELL_MS = 10_000L
    /** Deux fréquences à moins de 50 Hz l'une de l'autre = la même (la plus récente remplace l'ancienne). */
    const val SAME_HZ = 50L

    /** Ajoute en tête ; un doublon (même fréquence à 50 Hz près) est retiré ; [MAX] au plus. */
    fun add(list: List<RecentFreq>, hz: Long, mode: String): List<RecentFreq> {
        if (hz !in Radio.MIN_HZ..Radio.MAX_HZ) return list
        val entry = RecentFreq(hz, mode.take(12))
        return (listOf(entry) + list.filterNot { abs(it.hz - hz) <= SAME_HZ }).take(MAX)
    }

    /** « 7074000:USB;14205000:USB » (préférences du téléphone). */
    fun encode(list: List<RecentFreq>): String = list.joinToString(";") { "${it.hz}:${it.mode}" }

    /** Inverse de [encode] ; entrée abîmée = ignorée. */
    fun decode(text: String?): List<RecentFreq> =
        text.orEmpty().split(";").mapNotNull { part ->
            val i = part.indexOf(':')
            if (i <= 0) return@mapNotNull null
            val hz = part.substring(0, i).toLongOrNull()?.takeIf { it in Radio.MIN_HZ..Radio.MAX_HZ } ?: return@mapNotNull null
            val mode = part.substring(i + 1).filter { it.isLetterOrDigit() || it == '-' }.take(12)
            RecentFreq(hz, mode)
        }.take(MAX)

    /** Clé des préférences pour une station. */
    fun prefKey(stationId: String?): String = "recent_freqs_" + (stationId ?: "").filter { it.isLetterOrDigit() || it == '-' }

    /**
     * Touche du clavier de saisie : chiffres, « . », « ⌫ » (effacer un caractère), « C » (tout effacer). 12 caractères
     * au plus, deux points au plus (format du poste 7.074.00).
     */
    fun key(text: String, key: String): String = when (key) {
        "⌫" -> text.dropLast(1)
        "C" -> ""
        "." -> if (text.count { it == '.' } >= 2 || text.length >= 12) text else (if (text.isEmpty()) "0." else "$text.")
        else -> if (key.length == 1 && key[0].isDigit() && text.length < 12) text + key else text
    }
}
