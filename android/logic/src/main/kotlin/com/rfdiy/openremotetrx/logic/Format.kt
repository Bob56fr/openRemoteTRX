// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Affichages repris de la page (client.js : formatFrequency, sMeterText).
 *
 * Formats (cahier docs/application-traduction-cahier-des-charges.md § 3.5) : les FRÉQUENCES gardent le format radio
 * dans toutes les langues ; les nombres décimaux affichés prennent le séparateur de la langue CHOISIE ([decimal],
 * comme TrxI18n.decimal de la page) et les dates son format ([dateTime], [dayTime]), jamais ceux du téléphone. Un
 * nombre qui part vers la station ou le protocole n'est jamais localisé.
 */
object Format {
    /** 14074000 -> « 14 074 000 Hz » ; null -> « — ». */
    fun frequency(hz: Long?): String {
        if (hz == null) return "—"
        return hz.toString().reversed().chunked(3).joinToString(" ").reversed() + " Hz"
    }

    /** dB relatifs à S9 (S9 = 0 ; un point S = 6 dB) -> « S7 », « S9 », « S9+20 dB ». */
    fun sMeter(db: Double?): String {
        if (db == null) return "—"
        if (db >= 0) return if (db == 0.0) "S9" else "S9+${db.roundToInt()} dB"
        return "S${max(0, (9 + db / 6).roundToInt())}"
    }

    /** Secondes -> « 1:05 ». */
    fun duration(seconds: Int): String = "%d:%02d".format(Locale.ROOT, seconds / 60, seconds % 60)

    /** Séparateur décimal de la langue choisie : point en anglais, virgule en français, allemand, espagnol. */
    val separator: Char get() = if (Tr.lang == "en") '.' else ','

    /**
     * Nombre déjà écrit avec un point (« 3.5 », « -2.25 ») -> séparateur de la langue. SEULE fonction de
     * l'application qui choisit le séparateur ([decimal] passe par elle).
     */
    fun localize(text: String): String = if (separator == '.') text else text.replace('.', separator)

    /** 3.456, 2 -> « 3,46 » (fr, de, es) ou « 3.46 » (en). */
    fun decimal(value: Double, digits: Int): String = localize(String.format(Locale.ROOT, "%.${digits}f", value))

    /** Nombre écrit comme JavaScript le ferait (« 6 », « -2 », « 4,4 ») avec le séparateur de la langue. */
    fun decimal(value: Double): String =
        localize(if (value == Math.floor(value) && kotlin.math.abs(value) < 1e15) value.toLong().toString() else value.toString())

    private fun pattern(withYear: Boolean): String = when (Tr.lang) {
        "de" -> if (withYear) "dd.MM.yyyy HH:mm:ss" else "dd.MM. HH:mm:ss"   // i18n-ok : motifs de date
        else -> if (withYear) "dd/MM/yyyy HH:mm:ss" else "dd/MM HH:mm:ss"   // i18n-ok : motifs de date
    }

    /** Date et heure de la langue choisie : « 20/11/2026 14:03:05 » (fr, en-GB, es), « 20.11.2026 14:03:05 » (de). */
    fun dateTime(ms: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        DateTimeFormatter.ofPattern(pattern(true), Tr.locale).format(Instant.ofEpochMilli(ms).atZone(zone))

    /** Jour et heure sans l'année : « 20/11 14:03:05 » (fr, en-GB, es), « 20.11. 14:03:05 » (de). */
    fun dayTime(ms: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        DateTimeFormatter.ofPattern(pattern(false), Tr.locale).format(Instant.ofEpochMilli(ms).atZone(zone))
}
