// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Memory
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RadioTest {
    private val page = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/client.js").readText()

    @Test
    fun `memes bandes et memes pas que la page`() {
        val body = Regex("const BANDS = \\[(.*?)\\n  \\];", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        val pageBands = Regex("""key: "(\w+)".*?lo: (\d+), hi: (\d+), start: (\d+), mode: "(\w+)"""").findAll(body)
            .map { m -> m.groupValues.let { Band(it[1], it[2].toLong(), it[3].toLong(), it[4].toLong(), it[5]) } }.toList()
        assertEquals(pageBands, Radio.BANDS)
        val steps = Regex("const STEPS_HZ = \\[([\\d, ]+)\\]").find(page)!!.groupValues[1].split(",").map { it.trim().toLong() }
        assertEquals(steps, Radio.STEPS_HZ)
    }

    @Test
    fun `saisie de frequence comme la page`() {
        assertEquals(7_074_000, Radio.parseFrequencyEntry("7074"))
        assertEquals(7_074_500, Radio.parseFrequencyEntry("7 074,5"))
        assertEquals(14_205_000, Radio.parseFrequencyEntry("14.205"))
        assertEquals(7_074_000, Radio.parseFrequencyEntry("7,074"))
        assertEquals(7_074_000, Radio.parseFrequencyEntry("7.074.00"))
        assertEquals(3_822_500, Radio.parseFrequencyEntry("3.822.5"))
        assertNull(Radio.parseFrequencyEntry(""))
        assertNull(Radio.parseFrequencyEntry("abc"))
        assertNull(Radio.parseFrequencyEntry("0"))
        assertEquals("3.822.50", Radio.formatIcom(3_822_500))
        assertEquals("14.074.00", Radio.formatIcom(14_074_000))
        assertEquals(Radio.MIN_HZ, Radio.nudge(1500, 1000, -5))
    }

    @Test
    fun `modes donnees quand l'emission l'exige, bande memorisee sinon depart`() {
        val tx = listOf("PKTUSB", "PKTLSB")
        val modes = listOf("USB", "LSB", "PKTUSB", "PKTLSB", "CW")
        assertEquals("PKTUSB", Radio.adaptMode("USB", tx, modes))
        assertEquals("CW", Radio.adaptMode("CW", tx, modes))
        assertNull(Radio.adaptMode("FM", emptyList(), modes))
        assertEquals(14_200_000L to "PKTUSB", Radio.bandTarget(emptyMap(), "20", tx, modes))
        assertEquals(14_074_000L to "PKTUSB", Radio.bandTarget(mapOf("20" to BandSpot(14_074_000, "PKTUSB")), "20", tx, modes))
        assertNull(Radio.bandTarget(emptyMap(), "2", tx, modes))
        assertEquals("USB-D", Radio.modeLabel("PKTUSB"))
    }

    @Test
    fun `memoire des bandes - 1,5 s de stabilite, bornes respectees`() {
        val memory = BandMemory(mapOf("20" to BandSpot(7_000_000, "USB")))         // incohérente : ignorée
        assertTrue(memory.spots.isEmpty())
        assertFalse(memory.observe(0, 14_074_000, "USB"))
        assertFalse(memory.observe(1000, 14_074_000, "USB"))
        assertTrue(memory.observe(1600, 14_074_000, "USB"))
        assertEquals(BandSpot(14_074_000, "USB"), memory.spots["20"])
        assertFalse(memory.observe(4000, 14_074_000, "USB"))                           // déjà connue
        assertFalse(memory.observe(5000, 4_500_000, "USB"))
        assertFalse(memory.observe(7000, 4_500_000, "USB"))                            // hors bande
    }

    @Test
    fun `memoires - favorites d'abord, puis frequence`() {
        val list = listOf(Memory("a", "B", 14_000_000, "USB"), Memory("b", "A", 7_000_000, "LSB"), Memory("c", "Z", 28_000_000, "USB", favorite = true))
        assertEquals(listOf("c", "b", "a"), Radio.sortMemories(list).map { it.id })
        assertEquals(0.5f, Radio.sMeterFraction(3.0), 0.001f)
    }
}
