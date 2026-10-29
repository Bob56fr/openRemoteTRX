// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Command
import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ControlsTest {
    private val hello = ServerMessages.decode(
        """{"type":"hello","protocol":1,"client_id":"phone","max_power_w":100,
           "capabilities":{"modes":["USB","LSB"],"preamps":[10,20],"attenuators":[20],"filters":{"USB":[1800,2400,3000]}}}"""
    ) as Hello

    private fun state(levels: String, functions: String = "{}", passband: Int = 2400, ptt: String = "RX", spectrum: String = "{}") =
        ServerMessages.decode(
            """{"type":"state","ptt":{"state":"$ptt"},"spectrum":$spectrum,
               "rig":{"connected":true,"mode":"USB","passband_hz":$passband,"levels":$levels,"functions":$functions}}"""
        ) as State

    @Test
    fun `boutons comme la page, dans le meme ordre`() {
        val s = state("""{"PREAMP":10,"ATT":0,"AGC":2,"RFPOWER":0.25}""", """{"NR":true,"NB":false,"ANF":false,"MN":true,"COMP":false,"TUNER":true}""")
        val chips = Controls.chips(hello, s)
        assertEquals(listOf("NR", "NB", "PREAMP", "ATT", "NOTCH", "AGC", "COMP", "FIL", "TUNER", "PWR"), chips.map { it.key })
        assertEquals(listOf("NR", "NB", "P.AMP 10", "ATT", "NOTCH M", "AGC-F", "COMP", "FIL 2.4k", "TUNER", "PWR 25W"), chips.map { it.label })
        assertEquals(listOf(true, false, true, false, true, true, false, true, true, true), chips.map { it.on })
    }

    @Test
    fun `appuis - paliers qui bouclent, notch eteint avant d'allumer`() {
        val s = state("""{"PREAMP":20,"ATT":0,"AGC":3,"RFPOWER":1.0}""", """{"NR":false,"ANF":true,"MN":false}""", passband = 3000)
        assertEquals(listOf<Command>(Command.SetLevel("PREAMP", 0)), Controls.press("PREAMP", hello, s))
        assertEquals(listOf<Command>(Command.SetLevel("ATT", 20)), Controls.press("ATT", hello, s))
        assertEquals(listOf<Command>(Command.SetLevel("AGC", 2)), Controls.press("AGC", hello, s))
        assertEquals(listOf<Command>(Command.SetLevel("RFPOWER", 0.05)), Controls.press("PWR", hello, s))
        assertEquals(listOf<Command>(Command.SetFunction("NR", true)), Controls.press("NR", hello, s))
        assertEquals(listOf<Command>(Command.SetFunction("ANF", false), Command.SetFunction("MN", true)), Controls.press("NOTCH", hello, s))
        assertEquals(listOf<Command>(Command.SetMode("USB", 1800)), Controls.press("FIL", hello, s))
        assertEquals(emptyList(), Controls.press("INCONNU", hello, s))
    }

    @Test
    fun `filtres par le port B - FIL1 FIL2 FIL3, jamais de largeur Hamlib`() {
        val icom = ServerMessages.decode("""{"type":"hello","protocol":1,"client_id":"phone","spectrum":{"source":"civ_port"},
            "capabilities":{"filters":{"USB":[1800,2400,3000]}}}""") as Hello
        val withPreset = state("{}", spectrum = """{"settings":{"filter":3}}""")
        assertEquals("FIL3 2.4k", Controls.chips(icom, withPreset).single { it.key == "FIL" }.label)
        assertEquals("""{"cmd":"spectrum_set","name":"filter","value":1}""", Controls.press("FIL", icom, withPreset).single().encode())
        assertTrue(Controls.chips(icom, state("{}")).none { it.key == "FIL" })          // port B muet : pas de bouton
        assertEquals(emptyList(), Controls.press("FIL", icom, state("{}")))
    }

    @Test
    fun `indicateurs d'emission`() {
        val meters = Controls.meters(state("""{"RFPOWER_METER":0.5,"SWR":1.5,"ALC":0.3,"VD_METER":13.8,"TEMP_METER":31}"""))
        assertEquals(listOf("Po 50 %", "SWR 1.5", "ALC 30 %", "Vd 13.8 V", "Temp 31 °C"), meters.map { "${it.label} ${it.text}" })
        assertEquals(0.25f, meters[1].fraction, 0.001f)
    }

    @Test
    fun `memes paliers de puissance et memes cycles que la page`() {
        val page = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/client.js").readText()
        val power = Regex("const POWER_STEPS = \\[([\\d., ]+)\\]").find(page)!!.groupValues[1].split(",").map { it.trim().toDouble() }
        assertEquals(power, Controls.POWER_STEPS)
        val agc = Regex("const AGC_CYCLE = \\[([\\d, ]+)\\]").find(page)!!.groupValues[1].split(",").map { it.trim().toInt() }
        assertEquals(agc, Controls.AGC_CYCLE)
    }
}

class IndicatorsTest {
    private fun state(ptt: String, functions: String, levels: String) = com.rfdiy.openremotetrx.protocol.ServerMessages.decode(
        """{"type":"state","ptt":{"state":"$ptt"},"rig":{"connected":true,"functions":$functions,"levels":$levels}}"""
    ) as com.rfdiy.openremotetrx.protocol.State

    @Test
    fun `voyants - NB NR selon le poste, POWER SWR ALC seulement en emission mesuree`() {
        val rx = Indicators.of(state("RX", """{"NB":true,"NR":false}""", """{"RFPOWER_METER":0.0,"SWR":1.0,"ALC":0.0}"""))
        assertEquals(listOf("NB" to true, "NR" to false, "POWER" to false, "SWR" to false, "ALC" to false), rx.map { it.label to it.on })
        val tx = Indicators.of(state("TX", "{}", """{"RFPOWER_METER":0.5,"SWR":1.3,"ALC":0.0}"""))
        assertEquals(listOf("POWER" to true, "SWR" to true, "ALC" to false), tx.map { it.label to it.on })
        assertTrue(Indicators.of(null).isEmpty())
        val bare = Indicators.of(state("RX", "{}", "{}"))                       // mesures absentes en réception : gris
        assertEquals(listOf("POWER" to false, "SWR" to false, "ALC" to false), bare.map { it.label to it.on })
    }
}
