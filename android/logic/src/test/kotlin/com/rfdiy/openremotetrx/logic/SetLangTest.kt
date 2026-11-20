// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private class LangLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
}

/** Réglages > Langue : la nouvelle langue annoncée à la station sans reconnexion (`set_lang`, station 0.243.0+). */
class SetLangTest {
    private fun session(features: String, role: String = "operator"): Pair<RigSession, LangLink> {
        val link = LangLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features]}""")
        return s to link
    }

    @Test
    fun `station 0_243_0 et plus - langue annoncee aussitot, visiteur compris`() {
        for (role in listOf("operator", "listener")) {
            val (s, link) = session("\"ptt\",\"i18n\",\"set_lang\"", role)
            assertTrue(s.stationSetsLang)
            assertTrue(s.setLang(1, "de"))
            assertTrue(link.sent.last().contains("\"cmd\":\"set_lang\"") && link.sent.last().contains("\"lang\":\"de\""), link.sent.last())
        }
    }

    @Test
    fun `station plus ancienne - rien n'est envoye, la langue passe a la connexion suivante`() {
        val (s, link) = session("\"ptt\",\"i18n\"")
        val before = link.sent.size
        assertFalse(s.stationSetsLang)
        assertFalse(s.setLang(1, "de"))
        assertEquals(before, link.sent.size)
    }
}
