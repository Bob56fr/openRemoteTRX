// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Presence
import com.rfdiy.openremotetrx.protocol.PresenceConnection
import com.rfdiy.openremotetrx.protocol.PresencePerson
import com.rfdiy.openremotetrx.protocol.PresenceSuspended
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Visiteurs, lot 4 : un compte visiteur n'envoie rien d'autre que get_state et spectrum_watch ; « bye » et accès refusé
 * ne relancent jamais de reconnexion ; présence comme la page (client.js : presenceView). */
class ListenerTest {
    private class Link : SessionLink {
        val sent = mutableListOf<String>()
        var mic = false
        val alerts = mutableListOf<LinkAlert>()
        override fun startAttempt() {}
        override fun send(text: String): Boolean { sent += text; return true }
        override fun setMicOpen(open: Boolean) { mic = open }
        override fun close() {}
        override fun alert(kind: LinkAlert) { alerts += kind }
        fun cmds() = sent.map { Regex("\"cmd\":\"([a-z_]+)\"").find(it)!!.groupValues[1] }
    }

    private fun session(role: String): Pair<RigSession, Link> {
        val link = Link()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"club1","role":"$role","pseudo":"Club","spectrum":{"source":"civ_port","level_max":160,"max_fps":5}}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"TX","owner":"Kriss"},"rig":{"connected":true}}""")
        return s to link
    }

    @Test
    fun `un visiteur n'envoie aucune commande vers la station`() {
        val (s, link) = session("listener")
        assertTrue(s.snapshot.listener)
        s.setArmed(0, true)
        assertFalse(s.snapshot.armed)                                    // jamais armé
        s.pressPtt(0); s.stop(0); s.setFrequency(0, 7_100_000); s.recallMemory(0, "a1b2c3"); s.releaseLocal(0)
        s.selcallSend(0); s.setListenersOpen(0, false); s.kickListener(0, "club2"); s.reopenListeners(0)
        s.tick(500, true); s.tick(900, true)
        s.watchSpectrum(1000, true)
        assertTrue(link.cmds().all { it in setOf("get_state", "spectrum_watch") }, link.cmds().toString())
        assertTrue("spectrum_watch" in link.cmds())
        assertFalse(link.mic)                                            // micro jamais ouvert
        assertTrue(s.snapshot.log.any { it.text.contains("réception seule") })
    }

    @Test
    fun `un operateur envoie le commutateur, la deconnexion et la reouverture`() {
        val (s, link) = session("operator")
        s.setListenersOpen(0, true); s.kickListener(0, "club2"); s.reopenListeners(0)
        assertEquals(listOf("listeners_open", "listener_kick", "listeners_reopen"), link.cmds().filter { it.startsWith("listener") })
        assertTrue(link.sent.any { it.contains("\"account\":\"club2\"") } && link.sent.any { it.contains("\"on\":true") })
    }

    @Test
    fun `bye puis fermeture = pas de reconnexion, acces refuse = abandon de la reconnexion`() {
        val (s, link) = session("listener")
        s.onMessage(10, """{"type":"bye","reason":"operator_absent","message":"L'opérateur n'est pas connecté."}""")
        s.onLinkClosed(20, "datachannel_closed")
        assertEquals(LinkStatus.DISCONNECTED, s.snapshot.status)
        assertNull(s.snapshot.reconnect)
        assertTrue(s.snapshot.log.any { it.text.contains("L'opérateur n'est pas connecté.") })
        val (r, _) = session("listener")
        r.onLinkClosed(10, "datachannel_closed")                         // micro-coupure : reconnexion...
        assertEquals(LinkStatus.RECONNECTING, r.snapshot.status)
        r.tick(500, true)
        r.attemptFailed(600, "refused", "Nombre maximal de visiteurs atteint.")
        assertEquals(LinkStatus.DISCONNECTED, r.snapshot.status)         // ... abandonnée dès le premier refus d'accès
        assertTrue(r.snapshot.log.any { it.text.contains("accès refusé") })
        assertTrue(link.alerts.contains(LinkAlert.FAILED))
    }

    @Test
    fun `presence comme la page`() {
        val p = Presence(operators = 1, listeners = 3, maxListeners = 5, open = true,
            people = listOf(PresencePerson("Kriss", "operator", 4000), PresencePerson("Club", "listener", 125, 2)),
            connections = listOf(PresenceConnection("club1", "Club", "listener", "198.51.100.7", 125)))
        val op = PresenceUi.of(p, listener = false)!!
        assertEquals("🎧 3", op.label)
        assertEquals(listOf("Kriss", "Club ×2"), op.people.map { it.text })
        assertEquals(listOf("1 h 06", "2 min"), op.people.map { it.since })
        assertEquals(listOf("club1"), op.kick.map { it.account })
        assertTrue(op.switchShown && op.switchOn && op.switchAvailable)
        val vis = PresenceUi.of(p, listener = true)!!
        assertTrue(vis.kick.isEmpty() && !vis.switchShown && !vis.canReopen)
        assertEquals("", PresenceUi.of(p.copy(listeners = 0), false)!!.label)
        assertTrue(PresenceUi.of(p.copy(graceRemainingS = 42.4), true)!!.grace.contains("dans 42 s"))
        val hot = PresenceUi.of(p.copy(suspended = PresenceSuspended(message = "Station surchargée (processeur à 87 °C)")), false)!!
        assertTrue(hot.suspended.contains("87 °C") && hot.canReopen)
        val closed = PresenceUi.of(p.copy(maxListeners = 0, open = false), false)!!
        assertFalse(closed.switchAvailable); assertTrue(closed.switchNote.contains("menu 20"))
        assertFalse(PresenceUi.of(p.copy(open = null), false)!!.switchShown)    // station sans commutateur
        assertNull(PresenceUi.of(null, false))
    }
}
