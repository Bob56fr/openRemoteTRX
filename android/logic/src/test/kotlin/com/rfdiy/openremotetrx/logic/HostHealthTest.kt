// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Host
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Santé de la machine de la station (state.host) et synthèse host_info, comme la page (client.js : hostView). */
class HostHealthTest {
    private class Link : SessionLink {
        val sent = mutableListOf<String>()
        override fun startAttempt() {}
        override fun send(text: String): Boolean { sent += text; return true }
        override fun setMicOpen(open: Boolean) {}
        override fun close() {}
        override fun alert(kind: LinkAlert) {}
    }

    private fun session(role: String): Pair<RigSession, Link> {
        val link = Link()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":["host"]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true},
            "host":{"cpu_pct":12,"mem_pct":41,"disk_pct":37,"temp_c":46,"throttled":null,"load":0.487,"level":"ok","worst":"temp"}}""")
        return s to link
    }

    @Test
    fun `bargraph comme la page`() {
        val h = HostHealth.of(Host(cpuPct = 12, memPct = 41, diskPct = 37, tempC = 46, load = 0.487, level = "ok"), false)!!
        assertEquals(0.487f, h.fraction, 0.0001f)
        assertEquals("processeur 12 %, mémoire 41 %, disque 37 %, 46 °C", h.summary)
        assertEquals(1f, HostHealth.of(Host(load = 1.4, level = "bad", throttled = true), false)!!.fraction)
        assertTrue(HostHealth.of(Host(load = 1.0, level = "bad", throttled = true), false)!!.summary.contains("Pi RALENTI"))
        assertEquals("ok", HostHealth.of(Host(load = 0.2, level = "rouge"), false)!!.level)
        assertNull(HostHealth.of(Host(cpuPct = 3), false))                       // pas de « load » : station plus ancienne
        assertNull(HostHealth.of(Host(load = 0.5), true))                        // visiteur : jamais
        assertNull(HostHealth.of(null, false))
    }

    @Test
    fun `synthese demandee par l'operateur, affichee telle quelle`() {
        val (s, link) = session("operator")
        assertEquals(0.487f, s.snapshot.host!!.fraction, 0.0001f)
        s.hostInfo(1)
        assertTrue(link.sent.last().contains("\"cmd\":\"host_info\""))
        assertNull(s.snapshot.hostSections)                                       // en cours
        val id = Regex("\"id\":([0-9]+)").find(link.sent.last())!!.groupValues[1]
        s.onMessage(2, """{"type":"result","id":$id,"ok":true,"sections":[{"title":"Machine","rows":[["Système","Debian 13"],["mal formée"]]}]}""")
        assertEquals(listOf(HostSection("Machine", listOf("Système" to "Debian 13"))), s.snapshot.hostSections)
        s.hostInfo(3)
        val again = Regex("\"id\":([0-9]+)").find(link.sent.last())!!.groupValues[1]
        s.onMessage(4, """{"type":"result","id":$again,"ok":false,"reason":"unknown_command"}""")
        assertEquals(emptyList(), s.snapshot.hostSections)                       // station plus ancienne : indisponible
    }

    @Test
    fun `un visiteur ne demande jamais la synthese`() {
        val (s, link) = session("listener")
        val before = link.sent.size
        s.hostInfo(1)
        assertEquals(before, link.sent.size)
        assertNull(s.snapshot.host)
    }
}
