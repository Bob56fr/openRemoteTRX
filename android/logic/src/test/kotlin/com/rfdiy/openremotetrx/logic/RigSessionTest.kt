// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Liaison factice : enregistre ce que la session demande (rien ne part sur le réseau). */
private class FakeLink : SessionLink {
    val sent = mutableListOf<String>()
    val alerts = mutableListOf<LinkAlert>()
    var attempts = 0
    var closes = 0
    var mic = false
    override fun startAttempt() { attempts += 1 }
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) { mic = open }
    override fun close() { closes += 1 }
    override fun alert(kind: LinkAlert) { alerts += kind }

    fun cmds(): List<String> = sent.map { Regex("\"cmd\":\"([a-z_]+)\"").find(it)!!.groupValues[1] }
    fun idOf(cmd: String): Int = Regex("\"cmd\":\"$cmd\",\"id\":(\\d+)").find(sent.last { it.contains("\"$cmd\"") })!!.groupValues[1].toInt()
}

private const val ME = "phone"

private fun hello(protocol: Int = 1) = """{"type":"hello","protocol":$protocol,"client_id":"$ME","version":"0.52.0"}"""
private fun state(ptt: String, owner: String? = null) =
    """{"type":"state","ptt":{"state":"$ptt","owner":${owner?.let { "\"$it\"" } ?: "null"}},"rig":{"connected":true}}"""

/** Session connectée à t = 0 (fenêtre de reconnexion de 30 s). */
private fun connected(windowS: Int = 30): Pair<RigSession, FakeLink> {
    val link = FakeLink()
    val s = RigSession(link) { 0L }
    s.begin(0, windowS)
    s.answered(0)
    s.onMessage(0, hello())
    s.onMessage(0, state("RX"))
    return s to link
}

/** Émission de ce téléphone confirmée par la station à t = 100. */
private fun transmitting(): Pair<RigSession, FakeLink> {
    val (s, link) = connected()
    s.setArmed(0, true)
    s.pressPtt(0)
    s.onMessage(100, state("TX", ME))
    return s to link
}

class RigSessionTest {
    @Test
    fun `connexion - desarme, reception, micro ferme`() {
        val (s, link) = connected()
        assertEquals(LinkStatus.CONNECTED, s.snapshot.status)
        assertFalse(s.snapshot.armed)
        assertFalse(link.mic)
        assertEquals("RÉCEPTION", s.snapshot.ptt!!.label)
    }

    @Test
    fun `PTT refuse sans armement, et quand un autre emet - seul STOP part`() {
        val (s, link) = connected()
        s.pressPtt(10)
        assertFalse("toggle" in link.cmds())
        s.setArmed(10, true)
        s.onMessage(20, state("TX", "pc"))
        s.pressPtt(30)
        assertFalse("toggle" in link.cmds())
        s.stop(40)
        assertTrue("stop" in link.cmds())
    }

    @Test
    fun `battements des le toggle, micro ouvert seulement en TX confirme`() {
        val (s, link) = connected()
        s.setArmed(0, true)
        s.pressPtt(0)
        assertFalse(link.mic)                                       // pas encore confirmé
        s.onMessage(50, state("KEYING", ME))
        assertFalse(link.mic)
        s.tick(400, true)
        assertTrue("heartbeat" in link.cmds())
        s.onMessage(100, state("TX", ME))
        assertTrue(link.mic)
        assertTrue(s.snapshot.ptt!!.mine)
    }

    @Test
    fun `toggle refuse par la station - plus de battements, motif affiche`() {
        val (s, link) = connected()
        s.setArmed(0, true)
        s.pressPtt(0)
        s.onMessage(50, """{"type":"result","id":${link.idOf("toggle")},"ok":false,"reason":"out_of_band"}""")
        link.sent.clear()
        s.onMessage(400, state("RX"))
        s.tick(400, true)
        assertFalse("heartbeat" in link.cmds())
        assertEquals("Fréquence hors des bandes d'émission autorisées.", s.snapshot.log.last().text)
    }

    @Test
    fun `fin d'emission - micro ferme et battements arretes`() {
        val (s, link) = transmitting()
        s.pressPtt(1000)
        s.onMessage(1100, state("RX"))
        assertFalse(link.mic)
        link.sent.clear()
        s.tick(4500, true)
        assertFalse("heartbeat" in link.cmds())
        assertTrue(s.snapshot.armed)                                // reste armé après une fin normale
    }

    @Test
    fun `panne - silence de la station pendant mon emission - alerte puis coupure et reconnexion en RX`() {
        val (s, link) = transmitting()
        s.tick(1700, true)                                          // 1,6 s sans message
        assertEquals(listOf(LinkAlert.LOST), link.alerts)
        s.tick(5200, true)                                          // 5,1 s : liaison perdue
        assertFalse(link.mic)
        assertEquals(LinkStatus.RECONNECTING, s.snapshot.status)
        assertTrue(link.closes >= 1)
        link.sent.clear()
        s.tick(5600, true)                                          // premier essai à +400 ms
        assertEquals(2, link.attempts)
        assertTrue(link.sent.isEmpty())                             // plus aucun battement ni commande
        s.answered(5700)
        s.onMessage(5800, hello())
        s.onMessage(5800, state("RX"))
        assertEquals(LinkStatus.CONNECTED, s.snapshot.status)
        assertFalse(s.snapshot.armed)                               // réarmement obligatoire
        assertFalse(link.mic)
        assertEquals(LinkAlert.RESTORED, link.alerts.last())
        assertFalse("toggle" in link.cmds())                        // jamais de reprise d'émission automatique
    }

    @Test
    fun `panne - canal ferme pendant l'emission - micro ferme tout de suite`() {
        val (s, link) = transmitting()
        assertTrue(link.mic)
        s.onLinkClosed(200, "datachannel_closed")
        assertFalse(link.mic)
        assertFalse(s.connected)
        assertTrue(s.snapshot.log.last().text.contains("Ton émission est coupée par la station"))
    }

    @Test
    fun `panne - sans fenetre de reconnexion - perdue pour de bon`() {
        val (s, link) = connected(windowS = 0)
        s.onLinkClosed(10, "ice_failed")
        assertEquals(LinkStatus.DISCONNECTED, s.snapshot.status)
        assertEquals(listOf(LinkAlert.FAILED), link.alerts)
        s.tick(5000, true)
        assertEquals(1, link.attempts)
    }

    @Test
    fun `reconnexion - identifiants refuses - abandon immediat`() {
        val (s, link) = connected()
        s.onLinkClosed(0, "connection_failed")
        s.tick(400, true)
        s.attemptFailed(500, "auth")
        assertEquals(LinkStatus.DISCONNECTED, s.snapshot.status)
        assertEquals(LinkAlert.FAILED, link.alerts.last())
        s.tick(10_000, true)
        assertEquals(2, link.attempts)
    }

    @Test
    fun `reconnexion - pas de reseau, puis fenetre ecoulee`() {
        val (s, link) = connected(windowS = 5)
        s.onLinkClosed(0, "connection_failed")
        s.tick(400, online = false)
        assertEquals(1, link.attempts)                              // sans réseau : on attend
        s.tick(800, online = true)
        assertEquals(2, link.attempts)
        s.tick(900, true)
        s.answered(1000)
        s.tick(7100, true)                                          // canal jamais ouvert en 6 s
        s.tick(7200, true)                                          // fenêtre de 5 s écoulée
        assertEquals(LinkStatus.DISCONNECTED, s.snapshot.status)
        assertEquals(LinkAlert.FAILED, link.alerts.last())
    }

    @Test
    fun `canal jamais ouvert en connexion manuelle`() {
        val link = FakeLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(100)
        s.tick(15_000, true)
        assertEquals(LinkStatus.CONNECTING, s.snapshot.status)
        s.tick(15_200, true)
        assertEquals(LinkStatus.DISCONNECTED, s.snapshot.status)
        assertTrue(s.snapshot.log.last().text.startsWith("Connexion impossible : Canal de contrôle jamais ouvert"))
    }

    @Test
    fun `protocole inconnu - reception et STOP seulement`() {
        val link = FakeLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.onMessage(0, hello(protocol = 2))
        s.setArmed(0, true)
        s.pressPtt(0)
        assertFalse("toggle" in link.cmds())
        assertFalse(s.snapshot.protocolOk)
        s.stop(10)
        assertTrue("stop" in link.cmds())
    }

    @Test
    fun `deconnexion voulue - jamais de reconnexion, micro ferme`() {
        val (s, link) = transmitting()
        s.disconnect(500)
        assertFalse(link.mic)
        s.tick(5000, true)
        assertEquals(1, link.attempts)
        assertEquals(LinkStatus.DISCONNECTED, s.snapshot.status)
    }

    @Test
    fun `sondage get_state - temps de reponse, sans message au journal`() {
        val (s, link) = connected()
        s.tick(2000, true)
        s.onMessage(2040, """{"type":"result","id":${link.idOf("get_state")},"ok":true}""")
        assertEquals(40, s.snapshot.rttMs)
    }

    @Test
    fun `messages illisibles ou inconnus ignores`() {
        val (s, _) = connected()
        s.onMessage(10, "pas du json")
        s.onMessage(10, """{"type":"futur","x":1}""")
        assertEquals(LinkStatus.CONNECTED, s.snapshot.status)
    }
}
