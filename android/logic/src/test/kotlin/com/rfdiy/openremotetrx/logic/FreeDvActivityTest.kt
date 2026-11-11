// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.FreedvActivity
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class FdvaLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
    fun idOf(cmd: String): Int = Regex("\"cmd\":\"$cmd\",\"id\":(\\d+)").find(sent.last { it.contains("\"$cmd\"") })!!.groupValues[1].toInt()
}

class FreeDvActivityTest {
    private val repo = System.getProperty("trx.repo") ?: "../.."
    private val page = File(repo, "trxstation/gateway/api/static/client.js").readText()
    private val example: JsonObject = Json.parseToJsonElement(File(repo, "tests/protocol/messages.json").readText())
        .jsonObject["module_freedv_activity"]!!.jsonObject

    private fun act(json: String) = FreedvActivity.of(Json.parseToJsonElement(json))

    @Test
    fun `memes textes que la page`() {
        val fn = Regex("function freedvActivityView\\(a, rigHz, nowS\\) \\{(.*?)\\n  \\}", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        for (t in listOf(FreeDvActivities.STALE_TEXT, FreeDvActivities.CONNECTING_TEXT, FreeDvActivities.DEFAULT_ERROR,
                         FreeDvActivities.NO_LOCATOR, " connectée", " à FreeDV Reporter", " min", " km", " dB")) {
            assertTrue(fn.contains("\"$t\""), t)
        }
        assertTrue(fn.contains("\" ÉMET\""), "ÉMET")
        assertTrue(page.contains("const FREEDV_ACTIVITY_STALE_S = 60;"))
        assertTrue(page.contains("return rigMode === \"USB\" || rigMode === \"PKTUSB\" ? null : \"USB\";"))
        val ui = File(repo, "trxstation/gateway/api/static/ui.js").readText()
        for (t in listOf("\"QSY FreeDV : \"", "\" ◀ poste\"", "\"aucune activité HF\"")) assertTrue(ui.contains(t), t)
    }

    @Test
    fun `vue - memes cas que la page`() {
        assertNull(FreeDvActivities.view(null, null, null))
        assertNull(act("""{"kind":"spots"}"""))
        val msg = act("""{"kind":"freedv_activity","status":"ok","total":1,"locator":false,"t":1000,"freqs":[
            {"f":14236000,"note":2,"tx":[{"c":"W6GOK","km":null,"on":true,"min":null,"m":"RADE"}],"rx":[{"c":"K1ABC","km":null,"snr":-2,"m":"RADEV1"}]},
            {"f":"x"},null]}""")!!
        val v = FreeDvActivities.view(msg, 14236400, 1010.0)!!
        assertEquals("1 station connectée à FreeDV Reporter · distances absentes ([freedv] locator)", v.text)
        assertEquals(1, v.rows.size); assertEquals("14236,0 kHz", v.rows[0].freqText); assertTrue(v.rows[0].here)
        assertEquals(listOf(FreeDvActivityView.Tx("W6GOK ÉMET RADE", true)), v.rows[0].tx)
        assertEquals(listOf("K1ABC -2 dB"), v.rows[0].rx)
        assertFalse(FreeDvActivities.view(msg, 7_000_000, 1010.0)!!.rows[0].here)
        val stale = FreeDvActivities.view(msg, 0, 1100.0)!!                  // plus de 60 s : périmée, vide
        assertEquals("erreur", stale.status); assertTrue(stale.rows.isEmpty()); assertTrue(stale.text.contains("périmée"))
        assertTrue(FreeDvActivities.view(msg.copy(status = "connexion"), 0, 1010.0)!!.text.startsWith("Connexion"))
        assertEquals("injoignable", FreeDvActivities.view(msg.copy(status = "erreur", message = "injoignable"), 0, 1010.0)!!.text)
        assertNull(FreeDvActivities.qsyMode("USB")); assertNull(FreeDvActivities.qsyMode("PKTUSB"))
        assertEquals("USB", FreeDvActivities.qsyMode("LSB")); assertEquals("USB", FreeDvActivities.qsyMode(null))
        // exemple partagé (même attente que client_test.js)
        val ex = FreedvActivity.of(example["data"])!!
        val shared = FreeDvActivities.view(ex, 7196200, ex.t!! + 5)!!
        assertEquals("61 stations connectées à FreeDV Reporter", shared.text); assertEquals(2, shared.rows.size)
        assertTrue(shared.rows[0].here); assertEquals("DL2BHM 1012 km (1 min)", shared.rows[0].tx[1].text)
        assertEquals("28", shared.rows[0].noteText); assertEquals("1,6", shared.rows[1].noteText)
    }

    private fun session(role: String = "operator", mode: String = "LSB", ptt: String = "RX"): Pair<RigSession, FdvaLink> {
        val link = FdvaLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":["ptt","freedv"]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"$ptt","owner":null},"rig":{"connected":true,"frequency_hz":7196000,"mode":"$mode"}}""")
        return s to link
    }

    private fun RigSession.receive(now: Long) = onMessage(now, example.toString())

    @Test
    fun `QSY immediat - USB si besoin puis la frequence, refus montre dans la fenetre`() {
        val (s, link) = session(mode = "LSB")
        assertNull(s.snapshot.freedvActivity)                                    // section absente sans message
        s.freedvActivityQsy(1, 14236000)
        assertFalse(link.sent.any { it.contains("set_frequency") })              // pas de liste : rien
        s.receive(1)
        assertEquals(2, s.snapshot.freedvActivity!!.rows.size)
        s.freedvActivityQsy(2, 14236000)
        val sentNow = link.sent.takeLast(2)
        assertTrue(sentNow[0].contains("\"cmd\":\"set_mode\"") && sentNow[0].contains("\"mode\":\"USB\""))
        assertTrue(sentNow[1].contains("\"cmd\":\"set_frequency\"") && sentNow[1].contains("14236000"))
        s.onMessage(3, """{"type":"result","id":${link.idOf("set_frequency")},"ok":false,"reason":"out_of_band","detail":""}""")
        assertEquals(Texts.refusal("out_of_band"), s.snapshot.freedvActivityNotice)
        val (usb, usbLink) = session(mode = "USB")
        usb.receive(1)
        usb.freedvActivityQsy(2, 7196000)
        assertFalse(usbLink.sent.any { it.contains("set_mode") })                // poste déjà en USB : mode gardé
        usb.onMessage(3, """{"type":"result","id":${usbLink.idOf("set_frequency")},"ok":true}""")
        assertEquals("QSY FreeDV : 7196,0 kHz.", usb.snapshot.log.last().text)
        assertEquals("", usb.snapshot.freedvActivityNotice)
    }

    @Test
    fun `refuse en emission, visiteur sans commande mais avec la liste`() {
        val (tx, txLink) = session(ptt = "TX")
        tx.receive(1)
        tx.freedvActivityQsy(2, 14236000)
        assertFalse(txLink.sent.any { it.contains("set_frequency") || it.contains("set_mode") })
        assertEquals(Texts.refusal("tx_active"), tx.snapshot.freedvActivityNotice)
        val (visitor, vLink) = session(role = "listener")
        visitor.receive(1)
        assertEquals(2, visitor.snapshot.freedvActivity!!.rows.size)
        val before = vLink.sent.size
        visitor.freedvActivityQsy(2, 14236000)
        assertEquals(before, vLink.sent.size)
    }
}
