// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private class NoticeLink : SessionLink {
    val alerts = mutableListOf<LinkAlert>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean = true
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) { alerts += kind }
}

/** Avis de la station sur le poste (rig_notice : VOX coupé, coupleur, TOS élevé), comme la page (étapes 268 à 272). */
class RigNoticeTest {
    private fun session(): Pair<RigSession, NoticeLink> {
        val link = NoticeLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"operator","features":["ptt"]}""")
        return s to link
    }

    @Test
    fun `avis du VOX coupe - bandeau orange, journal, code, sans bip`() {
        val (s, link) = session()
        s.onMessage(1, """{"type":"rig_notice","event":"vox_off","detail":"Le VOX du poste était en marche : coupé","ort":"ORT-5034"}""")
        assertEquals("Le VOX du poste était en marche : coupé [ORT-5034]", s.snapshot.rigNotice)
        assertFalse(s.snapshot.rigNoticeBad)
        assertEquals(LogLevel.WARN, s.snapshot.log.last().level)
        assertTrue(link.alerts.isEmpty())
        s.dismissRigNotice(2)
        assertEquals("", s.snapshot.rigNotice)
    }

    @Test
    fun `TOS eleve - bandeau rouge et bip triple, message vide ignore`() {
        val (s, link) = session()
        s.onMessage(1, """{"type":"rig_notice","event":"swr_high","detail":"TOS 2.7 sur 24.9500 MHz","ort":"ORT-5039","swr":2.7}""")
        assertTrue(s.snapshot.rigNoticeBad && s.snapshot.rigNotice.startsWith("TOS 2.7"))
        assertEquals(listOf(LinkAlert.SWR_HIGH), link.alerts)
        assertEquals(LogLevel.BAD, s.snapshot.log.last().level)
        s.onMessage(2, """{"type":"rig_notice","event":"","detail":""}""")
        assertTrue(s.snapshot.rigNotice.startsWith("TOS 2.7"))
    }
}
