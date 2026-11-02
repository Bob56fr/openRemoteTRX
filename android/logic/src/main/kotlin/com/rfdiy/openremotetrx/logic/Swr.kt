// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.roundToLong

/**
 * Mesure de TOS (docs/tos-cahier-des-charges.md) : calculs purs de l'application, MÊMES résultats que la station
 * (trxstation/swr/plan.py) et la page (swr.js) ; exemples partagés tests/protocol/swr_plans.json.
 * La table des bandes propose la plage par défaut et avertit hors radioamateur ; elle n'autorise JAMAIS une émission.
 */
object Swr {
    data class TableBand(val name: String, val kind: String, val lowHz: Long, val highHz: Long)

    /** Points d'une mesure ; `error` = motif du protocole (swr_bad_range, swr_too_many_points), sinon null. */
    data class Plan(val lowHz: Long, val highHz: Long, val stepHz: Long, val freqs: List<Long>, val amateurOnly: Boolean, val error: String? = null)

    val NICE_STEPS_HZ = listOf(1_000L, 2_000L, 5_000L, 10_000L, 25_000L, 50_000L, 75_000L, 100_000L, 150_000L, 200_000L, 250_000L, 500_000L, 1_000_000L)
    const val MAX_POINTS = 50
    private const val SCALE_KNEE = 0.7
    private const val SCALE_MAX = 5.0
    val GRID = listOf(1.2, 1.3, 1.4, 1.5, 1.8, 2.0)

    val BANDS = listOf(
        TableBand("160m", "amateur", 1_810_000, 2_000_000), TableBand("80m", "amateur", 3_500_000, 3_800_000),
        TableBand("60m", "amateur", 5_351_500, 5_366_500), TableBand("40m", "amateur", 7_000_000, 7_200_000),
        TableBand("30m", "amateur", 10_100_000, 10_150_000), TableBand("20m", "amateur", 14_000_000, 14_350_000),
        TableBand("17m", "amateur", 18_068_000, 18_168_000), TableBand("15m", "amateur", 21_000_000, 21_450_000),
        TableBand("12m", "amateur", 24_890_000, 24_990_000), TableBand("10m", "amateur", 28_000_000, 29_700_000),
        TableBand("6m", "amateur", 50_000_000, 52_000_000), TableBand("2m", "amateur", 144_000_000, 146_000_000),
        TableBand("70cm", "amateur", 430_000_000, 440_000_000),
        TableBand("CB", "cb", 26_000_000, 28_000_000),
        TableBand("45m", "45m", 6_620_000, 6_700_000), TableBand("85m", "45m", 3_410_000, 3_490_000),
        TableBand("marine 4 MHz", "marine", 4_063_000, 4_438_000), TableBand("marine 6 MHz", "marine", 6_200_000, 6_525_000),
        TableBand("marine 8 MHz", "marine", 8_195_000, 8_815_000), TableBand("marine 12 MHz", "marine", 12_230_000, 13_200_000),
        TableBand("marine 16 MHz", "marine", 16_360_000, 17_410_000), TableBand("marine 18 MHz", "marine", 18_780_000, 18_900_000),
        TableBand("marine 19 MHz", "marine", 19_680_000, 19_800_000), TableBand("marine 22 MHz", "marine", 22_000_000, 22_855_000),
        TableBand("marine 25 MHz", "marine", 25_070_000, 25_210_000), TableBand("marine 26 MHz", "marine", 26_100_000, 26_175_000),
    )

    /** Bande de la table qui contient `hz` (radioamateur d'abord), ou null. */
    fun bandAt(hz: Long): TableBand? = BANDS.firstOrNull { hz in it.lowHz..it.highHz }

    fun isAmateur(hz: Long): Boolean = BANDS.any { it.kind == "amateur" && hz in it.lowHz..it.highHz }

    /** FreqBasse et FreqHaute d'une fréquence centrale et d'une largeur ; null si impossible. */
    fun rangeFromCenter(centerHz: Long, widthHz: Long): Pair<Long, Long>? {
        if (centerHz <= 0 || widthHz <= 0) return null
        val half = widthHz / 2
        return (centerHz - half) to (centerHz + (widthHz - half))
    }

    /** Valeur lisible la plus proche du pas brut (à égalité, la plus petite). */
    fun niceStep(rawHz: Double): Long = NICE_STEPS_HZ.minWith(compareBy<Long>({ abs(it - rawHz) }, { it }))

    fun plan(lowHz: Long, highHz: Long, points: Int, maxPoints: Int = MAX_POINTS): Plan {
        fun refused(code: String) = Plan(lowHz, highHz, 0, emptyList(), false, code)
        if (points < 2 || lowHz <= 0 || highHz <= lowHz) return refused("swr_bad_range")
        var step = niceStep((highHz - lowHz).toDouble() / (points - 1))
        var index = NICE_STEPS_HZ.indexOf(step)
        var freqs: List<Long>
        while (true) {
            val first = ceil(lowHz.toDouble() / step).roundToLong() * step
            freqs = generateSequence(first) { it + step }.takeWhile { it <= highHz }.toList()
            if (freqs.size <= maxPoints) break
            if (index + 1 >= NICE_STEPS_HZ.size) return refused("swr_too_many_points")
            step = NICE_STEPS_HZ[++index]
        }
        if (freqs.size < 2) return refused("swr_bad_range")
        return Plan(lowHz, highHz, step, freqs, freqs.all { isAmateur(it) })
    }

    /** Hauteur (0 à 1) d'un TOS sur l'axe non linéaire : 1 à 2 sur 70 % de la hauteur, 2 à 5 sur 30 %, plafond 5. */
    fun scaleY(swr: Double): Double {
        if (!swr.isFinite() || swr <= 1) return 0.0
        if (swr <= 2) return Math.round(SCALE_KNEE * (swr - 1) * 1e6) / 1e6
        return Math.round(minOf(1.0, SCALE_KNEE + (1 - SCALE_KNEE) * (swr - 2) / (SCALE_MAX - 2)) * 1e6) / 1e6
    }

    /** good jusqu'à 1,5 (vert), fair jusqu'à 2 (orange), bad au-dessus de 2 (rouge). */
    fun level(swr: Double): String = if (swr <= 1.5) "good" else if (swr <= 2) "fair" else "bad"
}
