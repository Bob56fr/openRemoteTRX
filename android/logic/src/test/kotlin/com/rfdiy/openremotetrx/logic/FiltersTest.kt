// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Command
import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

/** Largeur des filtres (étape 395), comme client.js : paliers du FTDX10, appui bref 1.8 à 4.0 k, trois curseurs Icom. */
class FiltersTest {
    private val ssb = "[300,400,600,850,1100,1200,1500,1650,1800,1950,2100,2250,2400,2450,2500,2600,2700,2800,2900,3000,3200,3500,4000]"
    private val yaesu = ServerMessages.decode(
        """{"type":"hello","protocol":1,"client_id":"phone","capabilities":{"modes":["USB","CW"],"filters":{"USB":[3000,2400]}},
           "rig_spec":{"model":1042,"filters":{"kind":"steps","steps":{"USB":$ssb,"CW":[50,100,500,1200,2400,4000]},
           "quick":[1800,2400,2800,3000,3500,4000]}}}"""
    ) as Hello
    private val icom = ServerMessages.decode(
        """{"type":"hello","protocol":1,"client_id":"phone","spectrum":{"source":"civ_port"},
           "rig_spec":{"model":3094,"filters":{"kind":"presets","presets":3}}}"""
    ) as Hello

    private fun state(mode: String, passband: Int, spectrum: String = "{}", ptt: String = "RX") = ServerMessages.decode(
        """{"type":"state","ptt":{"state":"$ptt"},"spectrum":$spectrum,
           "rig":{"connected":true,"mode":"$mode","passband_hz":$passband,"levels":{},"functions":{}}}"""
    ) as State

    @Test
    fun `fonctions pures comme la page`() {
        assertEquals(listOf(1800, 2400, 2800, 3000, 3500, 4000), Filters.quick(yaesu.rigSpec, "USB"))
        assertNull(Filters.quick(yaesu.rigSpec, "CW"))                          // le CW n'a pas tous ces paliers
        assertNull(Filters.steps(yaesu.rigSpec, "FM"))
        assertEquals(4000, Filters.next(listOf(1800, 2400, 4000), 2400))
        assertEquals(1800, Filters.next(listOf(1800, 2400, 4000), 4000))
        assertEquals(2400, Filters.next(listOf(1800, 2400, 4000), 2000))
        assertEquals(1800, Filters.next(listOf(1800, 2400), null))
        assertEquals(2450, Filters.nearest(Filters.steps(yaesu.rigSpec, "USB")!!, 2440))
    }

    @Test
    fun `paliers imposes - largeur relue, appui bref sur la liste courte, fenetre dans les autres modes`() {
        val usb = state("USB", 2400)
        assertEquals("FIL 2.4k", Controls.chips(yaesu, usb).single { it.key == "FIL" }.label)
        assertEquals(listOf<Command>(Command.SetMode("USB", 2800)), Controls.press("FIL", yaesu, usb))
        assertFalse(Controls.filterOpensDialog(yaesu, usb))
        val cw = state("CW", 500)
        assertEquals(emptyList(), Controls.press("FIL", yaesu, cw))
        assertTrue(Controls.filterOpensDialog(yaesu, cw))
        val view = Filters.dialog(yaesu, usb, locked = false)
        assertEquals("steps", view.kind); assertEquals(2400, view.hz); assertTrue(view.quick)
    }

    @Test
    fun `Icom - trois curseurs sur les largeurs relues par la station`() {
        val s = state("USB", 2400, """{"state":"ok","settings":{"filter":2,"filter_widths":[3000,2400,1800],"filter_steps":[50,100,1800,2400,3000]}}""")
        val view = Filters.dialog(icom, s, locked = false)
        assertEquals("presets", view.kind); assertTrue(view.known); assertEquals(2, view.current)
        assertEquals(listOf(3000, 2400, 1800), view.rows.map { it.hz })
        val unknown = Filters.dialog(icom, state("USB", 2400, """{"state":"ok","settings":{"filter":2}}"""), locked = false)
        assertFalse(unknown.known)
        assertFalse(Controls.filterOpensDialog(icom, s))                        // appui bref : FIL1 -> 2 -> 3 comme avant
        assertEquals(listOf<Command>(Command.SpectrumSet("filter", JsonPrimitive(3))), Controls.press("FIL", icom, s))
    }

    @Test
    fun `commandes envoyees par la fenetre`() {
        val json = Command.SpectrumSet("filter_widths", JsonNull).toJson(1)
        assertEquals(JsonPrimitive("filter_widths"), json["name"]); assertEquals(JsonNull, json["value"])
    }
}
