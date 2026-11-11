// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.FreedvCall
import com.rfdiy.openremotetrx.protocol.FreedvSequence
import com.rfdiy.openremotetrx.protocol.FreedvStatus
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class FdvLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
    fun idOf(cmd: String): Int = Regex("\"cmd\":\"$cmd\",\"id\":(\\d+)").find(sent.last { it.contains("\"$cmd\"") })!!.groupValues[1].toInt()
}

class FreeDvTest {
    private val page = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/client.js").readText()

    private fun session(features: String = "\"ptt\",\"freedv\"", role: String = "operator", freedv: String = ""): Pair<RigSession, FdvLink> {
        val link = FdvLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features]$freedv}""")
        return s to link
    }

    private fun fdvState(freedv: String) = """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true},"freedv":$freedv}"""

    @Test
    fun `memes textes que la page`() {
        val body = Regex("const FREEDV_ENGINE = \\{(.*?)\\n  \\};", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        val pageEngine = Regex("^\\s*([a-z_]+): \"(.*)\",?\\s*$", RegexOption.MULTILINE).findAll(body)
            .associate { it.groupValues[1] to it.groupValues[2] }
        assertEquals(pageEngine, FreeDvs.ENGINE.toMap())
        val fn = Regex("function freedvView\\(f, nowS\\) \\{(.*?)\\n  \\}", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        for (t in listOf("FreeDV abandonné : ", " (son du poste remis)", "Son du poste : mode FreeDV non choisi", "FreeDV : ",
                         "Voix FreeDV", " · SNR ", "FreeDV : recherche d'un signal…", "il y a ")) {
            assertTrue(fn.contains("\"$t\""), t)
        }
        val ui = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/ui.js").readText()
        for (t in listOf("Mode FreeDV : voix décodée par la station.", "Mode FreeDV quitté : son du poste.")) assertTrue(ui.contains(t), t)
        assertTrue(page.contains("\" décodé\""), "journal de l'indicatif")
        assertTrue(page.contains("\". Son du poste remis.\""), "journal de l'abandon")
    }

    @Test
    fun `vue de state freedv - memes cas que la page`() {
        assertNull(FreeDvs.view(null, 0.0))
        assertNull(FreeDvs.view(FreedvStatus(on = null), 0.0))                         // objet illisible
        val off = FreeDvs.view(FreedvStatus(on = false), 0.0)!!
        assertEquals(FreeDvLevel.OFF, off.level); assertEquals("Son du poste : mode FreeDV non choisi", off.text)
        assertNull(FreeDvs.carPart(off))
        val fault = FreeDvs.view(FreedvStatus(on = false, fault = "radae_rx gelé"), 0.0)!!
        assertEquals(FreeDvLevel.BAD, fault.level); assertEquals("FreeDV abandonné : radae_rx gelé (son du poste remis)", fault.text)
        assertEquals("FDV PANNE", FreeDvs.carPart(fault))
        val start = FreeDvs.view(FreedvStatus(on = true, engine = "demarrage"), 0.0)!!
        assertEquals(FreeDvLevel.WARN, start.level); assertEquals("FreeDV : démarrage des décodeurs…", start.text)
        assertEquals("FDV …", FreeDvs.carPart(start))
        val search = FreeDvs.view(FreedvStatus(on = true, engine = "ecoute", sync = "candidate", snrDb = 1.0), 0.0)!!
        assertEquals("FreeDV : recherche d'un signal…", search.text); assertFalse(search.confirmed)
        val unknown = FreeDvs.view(FreedvStatus(on = true, engine = "inconnu", confirmed = true), 0.0)!!
        assertEquals("arret", unknown.engine); assertEquals("Voix FreeDV", unknown.text)          // comme la page
        val now = 1794338400.0
        val voice = FreeDvs.view(FreedvStatus(on = true, engine = "ecoute", sync = "sync", confirmed = true, snrDb = 7.46,
            restarts = 2, cause = "freedv-ka9q arrêté",
            calls = listOf(FreedvCall("W6GOK", 9.0, 1794338361.6), FreedvCall(null, 3.0, 0.0), FreedvCall("N4WVE-TOOLONGCALL", 2.5, null)),
            sequences = listOf(FreedvSequence(1794338352.0, 6.7, 4.6, "SNR médian +12.2 dB", listOf("W6GOK")),
                               FreedvSequence(null, 2.0, null, "sans note"))), now)!!
        assertEquals(FreeDvLevel.OK, voice.level); assertEquals("Voix FreeDV · SNR +7,5 dB", voice.text); assertEquals("FDV", FreeDvs.carPart(voice))
        assertEquals(listOf("W6GOK", "N4WVE-TOOLON"), voice.calls.map { it.callsign })
        assertEquals("9 dB", voice.calls[0].snrText); assertEquals("2.5 dB", voice.calls[1].snrText)
        assertEquals("il y a 38 s", voice.calls[0].whenText); assertEquals("", voice.calls[1].whenText)
        val seq = voice.sequences.single()
        assertEquals(5, seq.note); assertEquals("★★★★★", seq.stars); assertEquals("7 s", seq.duration); assertEquals("W6GOK", seq.callsigns)
        assertEquals("il y a 41 s", seq.whenText)
        assertEquals("Dernier indicatif : W6GOK (9 dB), il y a 38 s · 2 relance(s) des décodeurs · dernière panne : freedv-ka9q arrêté", voice.details)
        assertEquals("★★☆☆☆", FreeDvs.stars(2.0)); assertEquals("☆☆☆☆☆", FreeDvs.stars(null)); assertEquals("★★★★★", FreeDvs.stars(9.0))
        assertEquals("−3,0 dB", FreeDvs.db(-3.0)); assertEquals("0,0 dB", FreeDvs.db(0.0))
        assertEquals("", FreeDvs.view(FreedvStatus(on = false, snrDb = 5.0, cause = "x"), now)!!.snrText + FreeDvs.view(FreedvStatus(on = false, cause = "x"), now)!!.cause)
    }

    @Test
    fun `session - etat pour tous, commande de l'operateur, refus visible, journal des evenements`() {
        val (s, link) = session(freedv = ",\"freedv\":{\"on\":false,\"engine\":\"arret\"}")
        assertEquals(FreeDvLevel.OFF, s.snapshot.freedv!!.level)                         // hello.freedv avant le premier state
        s.onMessage(1, fdvState("""{"on":true,"engine":"ecoute","sync":"sync","confirmed":true,"snr_db":6}"""))
        assertEquals(FreeDvLevel.OK, s.snapshot.freedv!!.level)
        s.freedvSet(2, true)
        assertTrue(link.sent.last().contains("\"cmd\":\"freedv_set\"") && link.sent.last().contains("\"on\":true"))
        s.onMessage(3, """{"type":"result","id":${link.idOf("freedv_set")},"ok":false,"reason":"freedv_tx","detail":"x"}""")
        assertEquals(Texts.refusal("freedv_tx"), s.snapshot.freedvNotice)
        s.freedvSet(4, false)
        assertEquals("", s.snapshot.freedvNotice)
        s.onMessage(5, """{"type":"result","id":${link.idOf("freedv_set")},"ok":true,"freedv":{"on":false}}""")
        assertEquals("Mode FreeDV quitté : son du poste.", s.snapshot.log.last().text)
        s.onMessage(6, """{"type":"freedv_event","kind":"callsign","callsign":"W6GOK","snr_db":9,"t":1}""")
        assertEquals("FreeDV : indicatif W6GOK décodé (SNR 9 dB).", s.snapshot.log.last().text)
        s.onMessage(7, """{"type":"freedv_event","kind":"fault","cause":"radae_rx gelé"}""")
        assertEquals("FreeDV abandonné : radae_rx gelé. Son du poste remis.", s.snapshot.log.last().text)
        assertEquals(LogLevel.WARN, s.snapshot.log.last().level)
    }

    @Test
    fun `visiteur - etat affiche, aucune commande, station sans la fonction - rien`() {
        val (s, link) = session(role = "listener")
        s.onMessage(1, fdvState("""{"on":true,"engine":"ecoute","confirmed":true}"""))
        assertEquals(FreeDvLevel.OK, s.snapshot.freedv!!.level)
        val before = link.sent.size
        s.freedvSet(2, false)
        assertEquals(before, link.sent.size)
        val (old, oldLink) = session(features = "\"ptt\"")
        old.onMessage(1, fdvState("""{"on":true}"""))
        assertNull(old.snapshot.freedv)
        old.freedvSet(2, true)
        assertFalse(oldLink.sent.any { it.contains("freedv_set") })
    }
}
