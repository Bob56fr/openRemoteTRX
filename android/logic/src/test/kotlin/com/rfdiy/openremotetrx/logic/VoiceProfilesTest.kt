// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Profils d'égaliseur de l'opérateur rangés sur la station (étape 102), comme la page (ui.js : voiceProfilesSync). */
class VoiceProfilesTest {
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

    private fun session(role: String, features: String): Pair<RigSession, Link> {
        val link = Link()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true}}""")
        return s to link
    }

    @Test
    fun `liste relue a la connexion, enregistrement, suppression`() {
        val (s, link) = session("operator", "\"voice_profiles\"")
        assertEquals("voice_profiles", link.cmds().last())
        assertNull(s.snapshot.voiceProfiles)                                        // en cours
        s.onMessage(1, """{"type":"result","id":${link.lastId()},"ok":true,"profiles":[{"name":"Mon DX","settings":{"highpassHz":250}}]}""")
        assertEquals(listOf("Mon DX"), s.snapshot.voiceProfiles!!.map { it.name })
        assertEquals(JsonPrimitive(250), s.snapshot.voiceProfiles!![0].settings["highpassHz"])
        s.saveVoiceProfile(2, " Soirée ", VoiceEq.toJson(VoiceSettings(enabled = true)))
        assertTrue(link.sent.last().contains("\"name\":\"Soirée\"") && link.sent.last().length < 2048)
        s.onMessage(3, """{"type":"result","id":${link.lastId()},"ok":true,"profiles":[{"name":"Mon DX","settings":{}},{"name":"Soirée","settings":{}}]}""")
        assertEquals(listOf("Mon DX", "Soirée"), s.snapshot.voiceProfiles!!.map { it.name })
        s.deleteVoiceProfile(4, "Mon DX")
        s.onMessage(5, """{"type":"result","id":${link.lastId()},"ok":false,"reason":"voice_profile_refused","detail":"profil inconnu"}""")
        assertEquals(2, s.snapshot.voiceProfiles!!.size)                            // refus : liste inchangée, message au journal
        assertTrue(s.snapshot.log.any { it.text.contains("profil inconnu") })
    }

    @Test
    fun `station sans profils ou visiteur, rien n'est demande`() {
        val (s, link) = session("operator", "\"ptt\"")
        assertTrue("voice_profiles" !in link.cmds())
        s.saveVoiceProfile(1, "x", VoiceEq.toJson(VoiceSettings()))
        assertTrue("voice_profile_save" !in link.cmds())
        val (v, vlink) = session("listener", "\"voice_profiles\"")
        assertTrue(vlink.cmds().none { it.startsWith("voice_profile") })
        assertNull(v.snapshot.voiceProfiles)
    }
}
