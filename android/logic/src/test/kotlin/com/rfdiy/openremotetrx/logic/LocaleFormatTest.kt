// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.time.ZoneOffset
import java.util.Locale
import kotlin.test.Test
import kotlin.test.assertEquals

/** Formats de la langue CHOISIE (cahier de la traduction § 3.5, lot T7) : séparateur décimal, dates, fréquences. */
class LocaleFormatTest {
    private val nov20 = 1_795_183_385_000L   // 2026-11-20 14:03:05 UTC

    private fun <T> inLang(lang: String, block: () -> T): T {
        Tr.lang = lang
        try { return block() } finally { Tr.lang = "fr" }
    }

    @Test
    fun `decimal - virgule en francais, allemand, espagnol, point en anglais`() {
        assertEquals("3,46", inLang("fr") { Format.decimal(3.456, 2) })
        assertEquals("3.46", inLang("en") { Format.decimal(3.456, 2) })
        assertEquals("3,46", inLang("de") { Format.decimal(3.456, 2) })
        assertEquals("3,46", inLang("es") { Format.decimal(3.456, 2) })
        assertEquals("-2.5", inLang("en") { Format.decimal(-2.5) })
        assertEquals("-2,5", inLang("de") { Format.decimal(-2.5) })
        assertEquals("6", inLang("de") { Format.decimal(6.0) })
        assertEquals("4,4", inLang("fr") { Format.localize("4.4") })
    }

    @Test
    fun `decimal - le telephone n'y change rien`() {
        val before = Locale.getDefault()
        try {
            Locale.setDefault(Locale.GERMANY)
            assertEquals("1.50", inLang("en") { Format.decimal(1.5, 2) })
            Locale.setDefault(Locale.US)
            assertEquals("1,50", inLang("fr") { Format.decimal(1.5, 2) })
        } finally { Locale.setDefault(before) }
    }

    @Test
    fun `textes affiches - TOS, dB, kHz suivent la langue`() {
        assertEquals("1,35", SwrUi.swrText(1.35))
        assertEquals("1.35", inLang("en") { SwrUi.swrText(1.35) })
        assertEquals("+7,5 dB", FreeDvs.db(7.5))
        assertEquals("+7.5 dB", inLang("en") { FreeDvs.db(7.5) })
        assertEquals("14236,0 kHz", FreeDvActivities.freqText(14_236_000))
        assertEquals("14236.0 kHz", inLang("en") { FreeDvActivities.freqText(14_236_000) })
        assertEquals("REF +2,5", inLang("de") { HfScope.refLabel(2.5) })
        assertEquals("REF +2.5", inLang("en") { HfScope.refLabel(2.5) })
        assertEquals("14 074,00 kHz", Car.frequency(14_074_000))
        assertEquals("14 074.00 kHz", inLang("en") { Car.frequency(14_074_000) })
    }

    @Test
    fun `frequences au format radio - inchangees dans toutes les langues`() {
        for (lang in Tr.LANGS) inLang(lang) {
            assertEquals("14 074 000 Hz", Format.frequency(14_074_000))
            assertEquals("27.430.00", Car.carFrequency(27_430_000))
        }
    }

    @Test
    fun `dates - format de la langue choisie`() {
        assertEquals("20/11/2026 14:03:05", inLang("fr") { Format.dateTime(nov20, ZoneOffset.UTC) })
        assertEquals("20/11/2026 14:03:05", inLang("en") { Format.dateTime(nov20, ZoneOffset.UTC) })
        assertEquals("20.11.2026 14:03:05", inLang("de") { Format.dateTime(nov20, ZoneOffset.UTC) })
        assertEquals("20/11 14:03:05", inLang("es") { Format.dayTime(nov20, ZoneOffset.UTC) })
        assertEquals("20.11. 14:03:05", inLang("de") { Format.dayTime(nov20, ZoneOffset.UTC) })
        assertEquals(Locale.GERMANY, inLang("de") { Tr.locale })
        assertEquals(Locale.UK, inLang("en") { Tr.locale })
        assertEquals(Locale.FRANCE, inLang(Tr.PSEUDO) { Tr.locale })
    }
}
