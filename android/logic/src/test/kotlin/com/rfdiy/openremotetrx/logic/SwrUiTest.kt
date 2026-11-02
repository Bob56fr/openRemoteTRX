// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Mesure de TOS dans l'application : messages « swr », réponses, textes (mêmes attendus que la page, swr_test.js). */
class SwrUiTest {
    private class Link : SessionLink {
        val sent = mutableListOf<String>()
        override fun startAttempt() {}
        override fun send(text: String): Boolean { sent += text; return true }
        override fun setMicOpen(open: Boolean) {}
        override fun close() {}
        override fun alert(kind: LinkAlert) {}
        fun cmds() = sent.map { Regex("\"cmd\":\"([a-z_]+)\"").find(it)!!.groupValues[1] }
        fun lastId() = Regex("\"id\":([0-9]+)").find(sent.last())!!.groupValues[1]
    }

    private val result = """{"points":[{"hz":14000000,"status":"measured","swr":1.3,"power_w":15},{"hz":14150000,"status":"measured","swr":1.18,"power_w":15}],
        "best":{"hz":14150000,"status":"measured","swr":1.18,"power_w":15},"reason":"done","detail":"","warning":"","power_w":15,"power_pct":15,
        "fm_mode":"FM-D","restored":{"frequency_hz":14074000,"mode":"PKTUSB","passband_hz":3000,"rfpower":1,"tuner":true},
        "differences":["coupleur : non remis en service, à rallumer à la main"],"at":1700000000}"""

    @Test
    fun `textes comme la page`() {
        assertEquals("14.050", SwrUi.freqLabel(14_050_000)); assertEquals("5.3575", SwrUi.freqLabel(5_357_500))
        assertEquals("1,23", SwrUi.swrText(1.234)); assertEquals("> 5", SwrUi.swrText(7.0))
        val r = SwrUi.result(kotlinx.serialization.json.Json.parseToJsonElement(result))!!
        val (lines, diffs) = SwrUi.restoredLines(r)
        assertEquals(listOf("Fréquence : 14,0740 MHz", "Mode : USB-D (3000 Hz)", "Puissance : 100 %", "Coupleur : en service"), lines)
        assertEquals(listOf("coupleur : non remis en service, à rallumer à la main"), diffs)
        assertTrue(SwrUi.restoredLines(null).first.single().contains("non relu"))
        assertEquals(listOf("Dipôle 20 m", "02/11/2026 · 15 W en FM-D · meilleur TOS 1,18 à 14.150 MHz"),
            SwrUi.legendLines(r, " Dipôle 20 m ", "02/11/2026"))
        assertEquals("Mesure de TOS", SwrUi.legendLines(null, "", "").first())
        assertEquals("Meilleur TOS : 1,18 à 14.150 MHz.", SwrUi.summary(r))
        val plan = SwrUi.planView(kotlinx.serialization.json.Json.parseToJsonElement(
            """{"points":[{"hz":14300000,"status":"pending"},{"hz":14400000,"status":"out_of_band"}],"fm_mode":"PKTFM","power_w":15.0,
                "max_power_pct":40,"estimated_s":12.4,"calibration_needed":true}""").let { it as kotlinx.serialization.json.JsonObject })!!
        assertEquals(" ; 15 W en FM-D ; 1 point(s) hors des bandes de la station, sautés ; environ 12 s (étalonnage du poste compris)", plan.text)
        assertEquals(40.0, plan.maxPowerPct)
    }

    @Test
    fun `operateur, plan, lancement, progression, derniere mesure`() {
        val link = Link()
        val s = RigSession(link) { 0L }
        s.begin(0, 30); s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"operator","features":["ptt","swr"]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true}}""")
        s.swrLast(1)
        s.onMessage(2, """{"type":"result","id":${link.lastId()},"ok":true,"last":$result,"choices":{"power_pct":20,"points":8}}""")
        assertEquals(20.0 to 8, s.snapshot.swrChoices)
        assertEquals(1.18, s.snapshot.swrLast!!.best!!.swr)
        s.swrStart(3, 14_000_000, 14_350_000, 8, 20.0)
        assertTrue("swr_start" !in link.cmds())                                         // pas armé : rien n'est envoyé
        s.setArmed(4, true)
        s.swrStart(5, 14_000_000, 14_350_000, 8, 20.0)
        assertEquals("swr_start", link.cmds().last())
        s.onMessage(6, """{"type":"swr","state":"measuring","index":0,"total":2,"points":[{"hz":14000000,"status":"measured","swr":1.3,"power_w":15}]}""")
        assertTrue(s.snapshot.swr!!.running && s.snapshot.swr!!.points.single().swr == 1.3)
        s.onMessage(7, """{"type":"swr","state":"done","index":null,"total":2,"points":[],"result":$result}""")
        assertTrue(!s.snapshot.swr!!.running && s.snapshot.swr!!.result!!.best!!.hz == 14_150_000L)
        s.swrCancel(8)
        assertEquals("swr_cancel", link.cmds().last())
    }

    @Test
    fun `visiteur ou station sans mesure, rien n'est envoye`() {
        val link = Link()
        val s = RigSession(link) { 0L }
        s.begin(0, 30); s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"club1","role":"listener","features":["ptt","swr"]}""")
        s.swrLast(1); s.swrPlan(1, 14_000_000, 14_350_000, 8, 20.0); s.swrStart(1, 14_000_000, 14_350_000, 8, 20.0)
        assertTrue(link.cmds().none { it.startsWith("swr_") })
        assertNull(s.snapshot.swr)
    }
}
