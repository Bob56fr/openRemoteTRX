// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.io.File
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** « Signaler un problème » (lot A3) : même texte que la page (formatProblemReport de client.js), envoi après relecture. */
class ProblemReportTest {
    private class Link : SessionLink {
        val sent = mutableListOf<String>()
        override fun startAttempt() {}
        override fun send(text: String): Boolean { sent += text; return true }
        override fun setMicOpen(open: Boolean) {}
        override fun close() {}
        override fun alert(kind: LinkAlert) {}
    }

    private val page = File(System.getProperty("trx.repo") ?: "../..", "trxstation/gateway/api/static/client.js").readText()

    private fun session(features: String = "\"bug_report\"", role: String = "operator"): Pair<RigSession, Link> {
        val link = Link()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","version":"0.114.0","features":[$features]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true,"frequency_hz":7074000,"mode":"PKTUSB"}}""")
        return s to link
    }

    @Test
    fun `memes rubriques que la page`() {
        for (label in listOf("=== Rapport de problème TRX distant ===", "\"Date : \"", "Ce qui s'est passé :", "(non décrit)",
            "\"Station : \"", "\"version inconnue\"", "\", protocole \"", "\", compte \"", "\", connecté\"", "\", NON connecté\"",
            "\"Appareil : \"", "\"Écran : \"", "\"Poste : \"", "\", liaison CAT \"", "\"PERDUE\"", "\", PTT \"",
            "\", poste utilisé sur place\"", "\"Spectre HF : \"", "\"Dernier temps de réponse : \"")) {
            assertTrue(page.contains(label.trim('"')), label)
        }
        assertTrue(page.contains("const MAX_REPORT_CHARS = ${ProblemReport.MAX_CHARS};"))
        assertTrue(page.contains(".slice(0, ${ProblemReport.DESCRIPTION_MAX})"))
    }

    @Test
    fun `rapport complet, sans secret, borne`() {
        val (s, _) = session()
        s.note(1_000, "Connexion établie.")
        val text = s.problemReport(1_793_000_000_000, "  Le son a coupé.  ", "samsung SM-S931B, Android 15", "412×915 dp, portrait")
        val zone = ZoneId.systemDefault()
        val expected = ProblemReport.format(ProblemReport.Input(1_793_000_000_000, "  Le son a coupé.  ", null, null, true, "", "", null,
            emptyList(), zone))
        assertTrue(expected.startsWith("=== Rapport de problème TRX distant ===\nDate : "))
        assertTrue(text.contains("Ce qui s'est passé :\nLe son a coupé.\n"))
        assertTrue(text.contains("Station : v0.114.0, protocole 1, compte phone, connecté"))
        assertTrue(text.contains("Appareil : samsung SM-S931B, Android 15\nÉcran : 412×915 dp, portrait"))
        assertTrue(text.contains("Poste : 7 074 000 Hz PKTUSB, liaison CAT active, PTT RX"))
        assertTrue(text.contains("Journal de l'application (dernières lignes) :") && text.contains("  Connexion établie."))
        assertFalse(text.contains("password") || text.contains("fingerprint"))
        assertTrue(s.problemReport(0, "", "", "").contains("Ce qui s'est passé :\n(non décrit)"))
        assertTrue(s.problemReport(0, "x".repeat(50_000), "", "").length <= ProblemReport.MAX_CHARS)
        assertEquals("—", ProblemReport.frequency(null))
        assertEquals("145 600 000 Hz", ProblemReport.frequency(145_600_000))
    }

    @Test
    fun `envoi seulement si la station l'annonce, resultat dans le journal`() {
        val (s, link) = session()
        s.sendProblemReport(1, "texte relu")
        assertTrue(link.sent.last().contains("\"cmd\":\"bug_report\"") && link.sent.last().contains("texte relu"))
        val id = Regex("\"id\":([0-9]+)").find(link.sent.last())!!.groupValues[1]
        s.onMessage(2, """{"type":"result","id":$id,"ok":true,"name":"2026-11-09_235959.txt"}""")
        assertTrue(s.snapshot.log.last().text.startsWith("Rapport envoyé à la station (2026-11-09_235959.txt)"))
        s.sendProblemReport(3, "encore")
        val again = Regex("\"id\":([0-9]+)").find(link.sent.last())!!.groupValues[1]
        s.onMessage(4, """{"type":"result","id":$again,"ok":false,"reason":"rate_limited"}""")
        assertTrue(s.snapshot.log.last().text.startsWith("Rapport non envoyé : "))
        val (old, oldLink) = session(features = "")
        val before = oldLink.sent.size
        old.sendProblemReport(1, "rien")                                              // station plus ancienne
        assertEquals(before, oldLink.sent.size)
    }
}
