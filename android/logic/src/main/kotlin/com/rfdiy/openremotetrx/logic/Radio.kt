// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Memory
import kotlin.math.roundToLong

/** Bande de la page (client.js, BANDS) : bornes, point de départ et mode usuel. RadioTest vérifie l'égalité. */
data class Band(val key: String, val lo: Long, val hi: Long, val start: Long, val mode: String)

/** Dernière fréquence et dernier mode utilisés sur une bande. */
data class BandSpot(val hz: Long, val mode: String)

/** Règles de la page pour la fréquence, les bandes et les modes (client.js), en Kotlin pur. */
object Radio {
    const val MIN_HZ = 1_000L
    const val MAX_HZ = 6_000_000_000L

    val STEPS_HZ = listOf(10L, 100L, 500L, 1000L, 5000L, 9000L, 10_000L, 12_500L, 25_000L)

    val BANDS = listOf(
        Band("160", 1_800_000, 2_000_000, 1_850_000, "LSB"),
        Band("85", 3_300_000, 3_499_999, 3_450_000, "PKTLSB"),       // écoute (demande de l'utilisateur)
        Band("80", 3_500_000, 4_000_000, 3_700_000, "LSB"),
        Band("60", 5_250_000, 5_450_000, 5_358_500, "USB"),
        Band("45", 6_500_000, 6_999_999, 6_660_000, "PKTLSB"),       // écoute (demande de l'utilisateur)
        Band("40", 7_000_000, 7_300_000, 7_100_000, "LSB"),
        Band("30", 10_100_000, 10_150_000, 10_130_000, "USB"),
        Band("20", 14_000_000, 14_350_000, 14_200_000, "USB"),
        Band("17", 18_068_000, 18_168_000, 18_130_000, "USB"),
        Band("15", 21_000_000, 21_450_000, 21_300_000, "USB"),
        Band("12", 24_890_000, 24_990_000, 24_950_000, "USB"),
        Band("11", 25_615_000, 27_995_000, 27_430_000, "USB"),
        Band("10", 28_000_000, 29_700_000, 28_400_000, "USB"),
        Band("6", 50_000_000, 54_000_000, 50_150_000, "USB"),
    )

    private val DATA_MODES = mapOf(
        "USB" to listOf("PKTUSB"), "LSB" to listOf("PKTLSB"), "FM" to listOf("PKTFM", "FM-D"), "AM" to listOf("PKTAM", "AM-D"),
    )
    private val MODE_LABELS = mapOf(
        "PKTUSB" to "USB-D", "PKTLSB" to "LSB-D", "PKTFM" to "FM-D", "PKTAM" to "AM-D", "FM-D" to "FM-D", "AM-D" to "AM-D",
    )

    /** Ordre d'affichage des modes (décision de l'utilisateur) : modes données d'abord, puis CW, puis les autres. */
    private val MODE_ORDER = listOf(
        "PKTUSB", "PKTLSB", "PKTAM", "AM-D", "PKTFM", "FM-D", "CW", "CWR", "USB", "LSB", "AM", "FM", "RTTY", "RTTYR",
    )

    /** Modes du poste dans l'ordre USB-D, LSB-D, AM-D, FM-D, CW… ; un mode inconnu de la liste garde son rang, à la fin. */
    fun orderModes(modes: List<String>): List<String> =
        modes.distinct().sortedBy { MODE_ORDER.indexOf(it).let { i -> if (i < 0) MODE_ORDER.size else i } }

    fun bandOf(hz: Long?): Band? = hz?.let { f -> BANDS.firstOrNull { f in it.lo..it.hi } }

    /** Libellé court d'un mode (PKTUSB -> USB-D). */
    fun modeLabel(mode: String?): String = mode?.let { MODE_LABELS[it] ?: it } ?: "—"

    private fun dataModeFor(mode: String, available: List<String>): String? {
        val names = DATA_MODES[mode] ?: return null
        if (available.isEmpty()) return names.firstOrNull()
        return names.firstOrNull { it in available }
    }

    /** Mode à utiliser pour un rappel : respecte les modes d'émission (USB -> USB-D) ; null si le poste ne l'a pas. */
    fun adaptMode(mode: String, txModes: List<String>, modes: List<String>): String? {
        var chosen = mode
        if (txModes.isNotEmpty() && chosen !in txModes) {
            val data = dataModeFor(chosen, txModes)
            if (data != null && data in txModes) chosen = data
        }
        if (modes.isNotEmpty() && chosen !in modes) return null
        return chosen
    }

    /** Dernière fréquence et dernier mode de la bande, sinon son point de départ usuel. */
    fun bandTarget(memory: Map<String, BandSpot>, key: String, txModes: List<String>, modes: List<String>): Pair<Long, String?>? {
        val band = BANDS.firstOrNull { it.key == key } ?: return null
        val base = memory[key] ?: BandSpot(band.start, band.mode)
        return base.hz to adaptMode(base.mode, txModes, modes)
    }

    /**
     * Saisie au clavier (comme la page) : « 7074 » ou « 7 074,5 » = kHz ; « 14.205 » ou « 7,074 » = MHz (moins de
     * 1000) ; « 7.074.00 » = format du poste. null si invalide ou hors de 1 kHz .. 6 GHz.
     */
    fun parseFrequencyEntry(text: String): Long? {
        val raw = text.filterNot { it.isWhitespace() }.replace(',', '.')
        if (raw.isEmpty()) return null
        val icom = Regex("""^(\d{1,4})\.(\d{3})\.(\d{1,2})$""").find(raw)
        val hz: Double = when {
            icom != null -> {
                val (m, k, t) = icom.destructured
                m.toDouble() * 1e6 + k.toDouble() * 1e3 + t.padEnd(2, '0').toDouble() * 10
            }
            Regex("""^\d*\.?\d*$""").matches(raw) && raw.any { it.isDigit() } -> {
                val n = raw.toDouble()
                if (n < 1000) n * 1e6 else n * 1e3
            }
            else -> return null
        }
        val rounded = hz.roundToLong()
        return rounded.takeIf { it in MIN_HZ..MAX_HZ }
    }

    /** 3 822 500 Hz -> « 3.822.50 » (MHz.kHz.10 Hz), comme l'afficheur d'un poste. */
    fun formatIcom(hz: Long?): String {
        if (hz == null) return "—"
        val mhz = hz / 1_000_000
        val rest = hz % 1_000_000
        return "%d.%03d.%02d".format(mhz, rest / 1000, (rest % 1000) / 10)
    }

    fun nudge(hz: Long, step: Long, steps: Int): Long = (hz + step * steps).coerceIn(MIN_HZ, MAX_HZ)

    /**
     * Repère du squelch sur l'échelle du S-mètre (page : squelchMarkerFraction) : le squelch (0 à 1) correspond à
     * l'échelle 0-255 du poste, qui est aussi celle du S-mètre (120 = S9, 241 = S9+60 dB). 0 = ouvert : null. INDICATIF.
     */
    fun squelchMarkerFraction(sql: Double?): Float? {
        if (sql == null || sql <= 0) return null
        val raw = minOf(1.0, sql) * 255
        return sMeterFraction(if (raw <= 120) -54 + raw * 54 / 120 else (raw - 120) * 60 / 121)
    }

    /** Squelch ouvert (le son passe) : réglé à 0, ou signal au-dessus du repère. Estimation, la station ne donne pas le DCD. */
    fun squelchOpen(sql: Double?, strengthDb: Double?): Boolean {
        val mark = squelchMarkerFraction(sql) ?: return sql != null
        return sMeterFraction(strengthDb) >= mark
    }

    /**
     * Bandes préférées (réglage de l'application) : clés dans l'ordre choisi, séparées par des virgules ; clés
     * inconnues et doublons ignorés ; vide ou illisible = toutes les bandes, dans l'ordre des fréquences.
     */
    fun favoriteBands(saved: String?): List<Band> {
        val keys = saved.orEmpty().split(',').map { it.trim() }.filter { it.isNotEmpty() }.distinct()
        val bands = keys.mapNotNull { k -> BANDS.firstOrNull { it.key == k } }
        return bands.ifEmpty { BANDS }
    }

    fun favoriteBandsText(bands: List<Band>): String = bands.joinToString(",") { it.key }

    /** Part de la barre du S-mètre : S0 (-54 dB) .. S9+60. */
    fun sMeterFraction(db: Double?): Float = if (db == null) 0f else ((db + 54) / 114).toFloat().coerceIn(0f, 1f)

    /** Favorites d'abord, puis par fréquence croissante, puis par nom (même règle que la station et la page). */
    fun sortMemories(list: List<Memory>): List<Memory> =
        list.sortedWith(compareBy<Memory>({ !it.favorite }, { it.hz }, { it.name }))
}

/**
 * Mémoire des bandes (page : rememberBand, BAND_STABLE_MS) : une fréquence restée 1,5 s sur une bande devient sa
 * « dernière fréquence ». Kotlin pur ; l'application la garde dans ses préférences.
 */
class BandMemory(initial: Map<String, BandSpot> = emptyMap(), private val stableMs: Long = 1500) {
    var spots: Map<String, BandSpot> = initial.filter { (key, spot) ->
        Radio.BANDS.firstOrNull { it.key == key }?.let { spot.hz in it.lo..it.hi } == true
    }
        private set
    private var seen: BandSpot? = null
    private var since = 0L

    /** Renvoie vrai si la mémoire a changé (à enregistrer). */
    fun observe(now: Long, hz: Long?, mode: String?): Boolean {
        if (hz == null || mode.isNullOrEmpty()) return false
        val spot = BandSpot(hz, mode)
        if (spot != seen) {
            seen = spot
            since = now
            return false
        }
        if (now - since < stableMs) return false
        val band = Radio.bandOf(hz) ?: return false
        if (spots[band.key] == spot) return false
        spots = spots + (band.key to spot)
        return true
    }
}
