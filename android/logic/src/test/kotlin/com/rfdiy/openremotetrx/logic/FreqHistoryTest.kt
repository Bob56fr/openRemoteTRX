// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals

class FreqHistoryTest {
    @Test
    fun `ajout en tete, doublon a 50 Hz pres remonte, dix au plus`() {
        var list = emptyList<RecentFreq>()
        for (i in 1..12) list = FreqHistory.add(list, 7_000_000L + i * 1000, "USB")
        assertEquals(10, list.size)
        assertEquals(7_012_000L, list.first().hz)
        list = FreqHistory.add(list, 7_005_030L, "LSB")
        assertEquals(RecentFreq(7_005_030L, "LSB"), list.first())
        assertEquals(1, list.count { kotlin.math.abs(it.hz - 7_005_000L) <= 50 })
        assertEquals(10, list.size)
        assertEquals(list, FreqHistory.add(list, 0L, "USB"))           // hors plage : ignorée
    }

    @Test
    fun `codage aller-retour et entree abimee ignoree`() {
        val list = listOf(RecentFreq(14_205_000, "USB"), RecentFreq(7_074_000, "PKTUSB"))
        assertEquals(list, FreqHistory.decode(FreqHistory.encode(list)))
        assertEquals(listOf(RecentFreq(7_074_000, "USB")), FreqHistory.decode("x:USB;7074000:USB;;12:;abc"))
        assertEquals(emptyList(), FreqHistory.decode(null))
    }

    @Test
    fun `clavier - chiffres, point, effacement`() {
        var t = ""
        for (k in listOf("1", "4", ".", "2", "0", "5")) t = FreqHistory.key(t, k)
        assertEquals("14.205", t)
        assertEquals(14_205_000L, Radio.parseFrequencyEntry(t))
        assertEquals("14.20", FreqHistory.key(t, "⌫"))
        assertEquals("", FreqHistory.key(t, "C"))
        assertEquals("0.", FreqHistory.key("", "."))
        assertEquals("7.074.00", FreqHistory.key("7.074.00", "."))     // pas de troisième point
        assertEquals("123456789012", FreqHistory.key("123456789012", "3"))
    }

    @Test
    fun `etiquettes des spots - indicatif, pays, les deux`() {
        val s = Spots.clean(kotlinx.serialization.json.Json.parseToJsonElement(
            """{"id":1,"f":14205.0,"dx":"EA8ABC","co":"Canary Islands"}"""), 0L)!!
        assertEquals("EA8ABC", Spots.labelText(s, Spots.LABEL_CALL))
        assertEquals("Canary Islands", Spots.labelText(s, Spots.LABEL_COUNTRY))
        assertEquals("EA8ABC Canary Islands", Spots.labelText(s, Spots.LABEL_BOTH))
        val long = s.copy(country = "European Russia Far")
        assertEquals("European Russ…", Spots.labelText(long, Spots.LABEL_COUNTRY))
        assertEquals("EA8ABC", Spots.labelText(s.copy(country = ""), Spots.LABEL_COUNTRY))
        assertEquals(listOf(1, 2, 0), listOf(0, 1, 2).map { Spots.nextLabelView(it) })
    }
}
