// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.io.File
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AudioWaterfallTest {
    private val page = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/waterfall.js").readText()

    private fun pageInts(name: String) =
        Regex("const $name = \\[([^\\]]+)\\]").find(page)!!.groupValues[1].split(",").map { it.trim().toInt() }

    @Test
    fun `memes listes et memes bornes que la page`() {
        assertEquals(pageInts("SPEEDS"), AudioWaterfall.SPEEDS)
        assertEquals(pageInts("WIDTHS"), AudioWaterfall.WIDTHS)
        assertEquals(pageInts("GAINS"), AudioWaterfall.GAINS)
        assertTrue(page.contains("FLOOR_DB = -85, RANGE_DB = 55"))
        assertEquals("LARG 2.5k", AudioWaterfall.widthLabel(2500))
        assertEquals("PIC MAX", AudioWaterfall.peakLabel(Double.POSITIVE_INFINITY))
        assertEquals("PIC 0.5s", AudioWaterfall.peakLabel(0.5))
        assertEquals(WaterfallSettings(12, 5000, 0, 2.0), AudioWaterfall.normalize(7, 4000, 3, 9))
    }

    @Test
    fun `un sinus de 1 kHz a pleine echelle - bonne raie, environ -13,5 dBFS comme Web Audio`() {
        val rate = 48_000
        val analyser = SpectrumAnalyser()
        val samples = FloatArray(analyser.fftSize) { n -> sin(2 * PI * 1000 * n / rate).toFloat() }
        var db = FloatArray(0)
        repeat(20) { analyser.push(samples); db = analyser.analyse() }      // lissage établi
        val values = AudioWaterfall.resample(db, rate, analyser.fftSize, 5000, 500)
        val peak = AudioWaterfall.strongest(values, 5000)!!
        assertTrue(abs(peak.hz - 1000) <= 15, "pic à ${peak.hz} Hz")
        assertTrue(peak.db in -15f..-12.5f, "niveau ${peak.db} dBFS")
        assertTrue(values[300] < -80f, "loin du signal : bruit de fond")           // 3 kHz
    }

    @Test
    fun `silence - aucun pic, noir`() {
        val analyser = SpectrumAnalyser()
        val values = AudioWaterfall.resample(analyser.analyse(), 48_000, analyser.fftSize, 5000, 100)
        assertNull(AudioWaterfall.strongest(values, 5000))
        assertEquals(0f, AudioWaterfall.levelToT(values[10], 0))
        assertEquals(1f, AudioWaterfall.levelToT(-30f, 0))
        assertEquals(0.5f, AudioWaterfall.levelToT(-69.5f, 12), 0.001f)
    }

    @Test
    fun `pics - maintien puis decroissance, desactives a 0`() {
        val tracker = PeakTracker()
        assertNull(tracker.update(floatArrayOf(-40f), 0.1, 0.0))
        tracker.update(floatArrayOf(-40f), 0.1, 2.0)
        val after = tracker.update(floatArrayOf(-80f), 1.0, 2.0)!!
        assertEquals(-67.5f, after[0], 0.01f)                                   // 55 dB / 2 s pendant 1 s
        assertEquals(-40f, PeakTracker().also { it.update(floatArrayOf(-40f), 0.0, Double.POSITIVE_INFINITY) }
            .update(floatArrayOf(-90f), 10.0, Double.POSITIVE_INFINITY)!![0])
        assertEquals(listOf("0", "0.5", "1"), AudioWaterfall.axisTicks(1000).map { it.label })
    }
}
