// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.BreizhStatus
import java.io.File
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class BzhLink : SessionLink {
    val sent = mutableListOf<String>()
    val alerts = mutableListOf<LinkAlert>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) { alerts += kind }
    fun cmds(): List<String> = sent.map { Regex("\"cmd\":\"([a-z_]+)\"").find(it)!!.groupValues[1] }
    fun idOf(cmd: String): Int = Regex("\"cmd\":\"$cmd\",\"id\":(\\d+)").find(sent.last { it.contains("\"$cmd\"") })!!.groupValues[1].toInt()
}

class BreizhTest {
    private val page = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/client.js").readText()

    private fun bzhState(breizh: String, ptt: String = "RX", owner: String? = null) =
        """{"type":"state","ptt":{"state":"$ptt","owner":${owner?.let { "\"$it\"" } ?: "null"}},"rig":{"connected":true},"breizh":$breizh}"""

    private fun session(features: String = "\"ptt\",\"breizh\"", role: String = "operator"): Pair<RigSession, BzhLink> {
        val link = BzhLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features]}""")
        return s to link
    }

    @Test
    fun `memes textes d'etat que la page`() {
        val body = Regex("const BREIZH_STATES = \\{(.*?)\\n  \\};", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        val pageStates = Regex("^\\s*([a-z_]+): \"(.*)\",?\\s*$", RegexOption.MULTILINE).findAll(body)
            .associate { it.groupValues[1] to it.groupValues[2] }
        assertEquals(pageStates, Breizhs.STATES.toMap())
    }

    @Test
    fun `vue de state breizh - memes cas que la page`() {
        assertNull(Breizhs.view(null))
        val ready = Breizhs.view(BreizhStatus("ready", "breizh", false, -3.5, 4, 0, 0, "Breizh 0.10.0", null))!!
        assertEquals(BreizhLevel.OK, ready.level); assertTrue(ready.effectsOff); assertFalse(ready.canReactivate)
        assertEquals("−3,5 dB", ready.returnGainText); assertEquals("Breizh 0.10.0 · aller-retour 4 ms", ready.details)
        val fallback = Breizhs.view(BreizhStatus("fallback", "direct", false, 6.0, null, 3, 1, "", 12))!!
        assertEquals(BreizhLevel.WARN, fallback.level); assertFalse(fallback.effectsOff); assertTrue(fallback.canReactivate)
        assertEquals("+6 dB", fallback.returnGainText)
        assertEquals("3 bloc(s) partis sans traitement · retour de Breizh dans 12 s", fallback.details)
        val direct = Breizhs.view(BreizhStatus("ready", "direct", bypass = true))!!
        assertEquals(BreizhLevel.OFF, direct.level); assertFalse(direct.effectsOff); assertTrue(direct.text.startsWith("« Direct » choisi"))
        assertEquals(Breizhs.STATES["connecting"], Breizhs.view(BreizhStatus("inconnu", "x"))!!.text)
        assertTrue(Breizhs.view(BreizhStatus("refused", "direct"))!!.canReactivate)
        assertEquals("0 dB", Breizhs.gainText(0.0))
        assertEquals(-20.0, Breizhs.snapGain(-25.0)); assertEquals(-3.5, Breizhs.snapGain(-3.4)); assertEquals(6.0, Breizhs.snapGain(9.0))
        assertEquals("2026-11-04 10:00:00 UTC : joint", BreizhEntry("2026-11-04T10:00:00Z", "connected", "joint").line)
    }

    @Test
    fun `session - journal relu a la connexion, evenements, alerte du repli pendant MON emission, commandes`() {
        val (s, link) = session()
        assertEquals("breizh_log", link.cmds().last())
        s.onMessage(1, """{"type":"result","id":${link.idOf("breizh_log")},"ok":true,"entries":[{"t":"2026-11-04T10:00:00Z","event":"connected","detail":"joint"}]}""")
        assertEquals(listOf("connected"), s.snapshot.breizhEvents.map { it.event })
        s.onMessage(2, bzhState("""{"state":"ready","route":"breizh","bypass":false,"return_gain_db":0}"""))
        assertTrue(s.snapshot.breizh!!.effectsOff)
        s.onMessage(3, """{"type":"breizh_event","t":"x","event":"lost","detail":"Breizh ne répond plus"}""")
        assertTrue(link.alerts.isEmpty())                                      // pas en émission : pas d'alerte
        assertEquals(LogLevel.WARN, s.snapshot.log.last().level)
        s.onMessage(4, bzhState("""{"state":"active","route":"breizh"}""", "TX", "phone"))
        s.onMessage(5, """{"type":"breizh_event","t":"y","event":"fallback","detail":"repli"}""")
        assertEquals(listOf(LinkAlert.BREIZH_FALLBACK), link.alerts)
        assertEquals(LogLevel.BAD, s.snapshot.log.last().level)
        assertEquals(3, s.snapshot.breizhEvents.size)
        s.breizhSet(6, returnGainDb = -3.4)
        assertTrue(link.sent.last().contains("\"return_gain_db\":-3.5"))
        s.breizhSet(7)                                                         // rien à changer : rien n'est envoyé
        assertEquals("breizh_set", link.cmds().last())
        s.breizhReactivate(8)
        s.onMessage(9, """{"type":"result","id":${link.idOf("breizh_reactivate")},"ok":true,"pending":true}""")
        assertTrue(s.snapshot.log.last().text.startsWith("Breizh sera repris"))
    }

    @Test
    fun `station sans Breizh ou visiteur - rien`() {
        val (s, link) = session("\"ptt\"")
        assertTrue(link.cmds().none { it.startsWith("breizh") })
        s.breizhSet(1, bypass = true); s.breizhReactivate(1)
        assertTrue(link.cmds().none { it.startsWith("breizh") })
        val (v, vlink) = session(role = "listener")
        v.onMessage(1, bzhState("""{"state":"ready","route":"breizh"}"""))
        assertNull(v.snapshot.breizh)
        assertTrue(vlink.cmds().none { it.startsWith("breizh") })
    }

    @Test
    fun `voix par Breizh - egaliseur et effets contournes, limiteur garde`() {
        val settings = VoiceSettings(enabled = true, highpassHz = 1000.0)       // coupe-bas fort : le grave disparaît
        fun lowTone() = FloatArray(4800) { i -> (0.3 * sin(2 * PI * 150.0 * i / 48000)).toFloat() }
        fun peak(b: FloatArray) = b.drop(2400).maxOf { abs(it) }
        val processed = VoiceDsp(48000).apply { apply(settings) }
        val p = lowTone().also { processed.process(it) }
        val breizh = VoiceDsp(48000).apply { apply(settings); external = true }
        val b = lowTone().also { breizh.process(it) }
        assertTrue(peak(p) < 0.1, "égaliseur en service : ${peak(p)}")
        assertTrue(peak(b) > 0.25, "contourné : ${peak(b)}")
        val loud = FloatArray(4800) { i -> (1.5 * sin(2 * PI * 300.0 * i / 48000)).toFloat() }.also { breizh.process(it) }
        assertTrue(peak(loud) < 1.0, "limiteur gardé : ${peak(loud)}")
    }
}
