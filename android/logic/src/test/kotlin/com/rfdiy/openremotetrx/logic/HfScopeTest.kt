// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.SpectrumFrame
import com.rfdiy.openremotetrx.protocol.State
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class HfScopeTest {
    private val static = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static")

    private fun frame(points: List<Int>, low: Long = 14_175_000, high: Long = 14_225_000) =
        SpectrumFrame(0, false, 1, low, high, points.map { it.toByte() }.toByteArray())

    private fun pageList(file: String, name: String): List<String> =
        Regex("const $name = \\[([^\\]]+)\\]").find(File(static, file).readText())!!.groupValues[1].split(",").map { it.trim() }

    @Test
    fun `memes listes que la page (hfscope_js, waterfall_js)`() {
        assertEquals(pageList("hfscope.js", "GAINS").map { it.toInt() }, HfScope.GAINS)
        assertEquals(pageList("hfscope.js", "RANGES_DB").map { it.toInt() }, HfScope.RANGES_DB)
        assertEquals(pageList("hfscope.js", "SPANS_HZ").map { it.toLong() }, HfScope.SPANS_HZ)
        assertEquals(pageList("waterfall.js", "DEFAULT_GRADIENT").map { it.trim('"') }, Palette.DEFAULT_GRADIENT)
        assertEquals(0xFF06080C.toInt(), Palette.LUT[0])
        assertEquals(-1, Palette.LUT[255])
    }

    @Test
    fun `fenetre de couleurs - plancher de bruit, pleine echelle a 80 dB`() {
        val f = frame(listOf(20, 22, 21, 100, 20, 23, 22))
        assertEquals(22, HfScope.noiseFloor(f))
        assertEquals(ColorWindow(0.0, 160.0, null), HfScope.colorWindow(f, 160, 80, null))
        val w = HfScope.colorWindow(f, 160, 40, null)
        assertEquals(ColorWindow(18.0, 80.0, 22.0), w)
        assertEquals(1f, HfScope.windowT(100.0, w, 0))
        assertEquals(0f, HfScope.windowT(10.0, w, 0))
        assertEquals(26.0, HfScope.colorWindow(frame(listOf(42)), 160, 40, 22.0).floor!!, 1e-9)   // lissage 20 %
    }

    @Test
    fun `graduations, repere et accord au doigt`() {
        val ticks = HfScope.ticks(14_175_000, 14_225_000)
        assertEquals(listOf("14.18", "14.19", "14.20"), ticks.take(3).map { it.label })          // pas de 10 kHz, comme la page
        assertEquals(0.5f, HfScope.markerFraction(14_200_000, 14_175_000, 14_225_000))
        assertNull(HfScope.markerFraction(7_000_000, 14_175_000, 14_225_000))
        assertEquals(100, HfScope.tuneStep(50_000))
        assertEquals(10, HfScope.tuneStep(5_000))
        assertEquals(-10, HfScope.dragSteps(100f, 1000f, 10_000, 100))           // vers la droite : fréquence plus basse
        assertEquals(14_200_000, HfScope.frequencyAt(0.5f, 14_175_000, 14_225_000))
        assertEquals("50 kHz", HfScope.spanLabel(14_175_000, 14_225_000))
    }

    @Test
    fun `zoom a deux doigts - un cran par doublement, borne a la liste`() {
        assertEquals(10_000, HfScope.zoomSpan(25_000, 2f))              // écarter : plus étroit
        assertEquals(5_000, HfScope.zoomSpan(25_000, 4f))
        assertEquals(50_000, HfScope.zoomSpan(25_000, 0.5f))            // pincer : plus large
        assertEquals(10_000, HfScope.zoomSpan(25_000, 1.4f))            // petit geste franc : un cran
        assertNull(HfScope.zoomSpan(25_000, 1.1f))                      // trop petit
        assertNull(HfScope.zoomSpan(2_500, 3f))                         // déjà au plus étroit
        assertNull(HfScope.zoomSpan(null, 2f))
        assertEquals(2_500, HfScope.zoomSpan(500_000, 1000f))
    }

    @Test
    fun `reglages du poste - libelles et cycles comme la page`() {
        assertEquals("±2,5k", HfScope.spanSettingLabel(2500))
        assertEquals("±25k", HfScope.spanSettingLabel(25_000))
        assertEquals(50_000, HfScope.nextSpan(25_000))
        assertEquals(2500, HfScope.nextSpan(500_000))
        assertEquals("fixed", HfScope.nextMode("center"))
        assertEquals("center", HfScope.nextMode("scroll_fixed"))
        assertEquals("mid", HfScope.nextSpeed("fast"))
        assertEquals("REF -10,5", HfScope.refLabel(-10.5))
        assertEquals(20.0, HfScope.stepRef(19.6, 1.0))
        assertNull(HfScope.stepRef(null, 1.0))
        val state = ServerMessages.decode(
            """{"type":"state","spectrum":{"state":"ok","settings":{"mode":"center","span":25000,"speed":"fast","ref":-10.0,"filter":2}}}"""
        ) as State
        assertEquals(ScopeSettings("center", 25_000, "fast", -10.0, 2), HfScope.settings(state))
        assertEquals("En attente du spectre du poste…", HfScope.waitText(state))
    }
}
