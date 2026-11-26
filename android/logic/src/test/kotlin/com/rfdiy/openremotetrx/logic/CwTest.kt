// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private class CwLink : SessionLink {
    val sent = mutableListOf<String>()
    val cw = mutableListOf<String>()
    var mic = false
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun sendCw(text: String): Boolean { cw += text; return true }
    override fun setMicOpen(open: Boolean) { mic = open }
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
    fun idOf(cmd: String): Int = Regex("\"cmd\":\"$cmd\",\"id\":(\\d+)").findAll(sent.joinToString("\n")).last().groupValues[1].toInt()
}

/** Manipulation CW de l'application (branche exp/cw) : manipulateur, paquets, décodage, session. */
class CwTest {
    private fun keyer(i: CwInterface, wpm: Int = 20) = CwKeyer(i, wpm)

    /** Fronts jusqu'à `until` pour une suite d'appuis (instant, palette, appuyée). */
    private fun run(k: CwKeyer, presses: List<Triple<Double, Paddle, Boolean>>, until: Double): List<KeyEdge> {
        val out = mutableListOf<KeyEdge>()
        for ((t, p, on) in presses) out += k.press(t, p, on)
        out += k.advance(until)
        return out
    }

    private fun pattern(edges: List<KeyEdge>, dot: Double): String =
        edges.zipWithNext().filter { (a, _) -> a.down }.joinToString("") { (a, b) -> if (b.at - a.at < 2 * dot) "." else "-" }

    @Test
    fun `pioche - le front suit le doigt, a la milliseconde`() {
        val k = keyer(CwInterface.STRAIGHT)
        val edges = run(k, listOf(Triple(10.0, Paddle.DOT, true), Triple(73.5, Paddle.DOT, false),
                                  Triple(80.0, Paddle.DASH, true)), 500.0)
        assertEquals(listOf(KeyEdge(10.0, true), KeyEdge(73.5, false)), edges)     // la palette DASH ne fait rien
    }

    @Test
    fun `iambique - elements exacts et alternance en serrant les deux palettes`() {
        val k = keyer(CwInterface.IAMBIC_A)                                          // point = 60 ms
        val edges = run(k, listOf(Triple(0.0, Paddle.DOT, true), Triple(10.0, Paddle.DASH, true),
                                  Triple(300.0, Paddle.DOT, false), Triple(300.0, Paddle.DASH, false)), 2000.0)
        assertEquals(KeyEdge(0.0, true), edges[0]); assertEquals(KeyEdge(60.0, false), edges[1])
        assertEquals(KeyEdge(120.0, true), edges[2]); assertEquals(KeyEdge(300.0, false), edges[3])   // trait de 3 points
        assertEquals(".-", pattern(edges, 60.0))
    }

    @Test
    fun `iambique B donne un element de plus que A quand on relache pendant l'element`() {
        // point appuyé, trait touché brièvement pendant le point puis tout relâché avant la fin du point
        val presses = listOf(Triple(0.0, Paddle.DOT, true), Triple(20.0, Paddle.DASH, true),
                             Triple(30.0, Paddle.DASH, false), Triple(40.0, Paddle.DOT, false))
        assertEquals(".", pattern(run(keyer(CwInterface.IAMBIC_A), presses, 2000.0), 60.0))
        assertEquals(".-", pattern(run(keyer(CwInterface.IAMBIC_B), presses, 2000.0), 60.0))
    }

    @Test
    fun `simple levier - la derniere palette l'emporte, jamais d'alternance`() {
        val k = keyer(CwInterface.SINGLE_LEVER)
        val edges = run(k, listOf(Triple(0.0, Paddle.DASH, true), Triple(100.0, Paddle.DOT, true),
                                  Triple(420.0, Paddle.DOT, false), Triple(420.0, Paddle.DASH, false)), 2000.0)
        assertEquals("-..", pattern(edges, 60.0))
    }

    @Test
    fun `inversion point et trait`() {
        val k = CwKeyer(CwInterface.IAMBIC_A, 20, reversed = true)
        assertEquals("-", pattern(run(k, listOf(Triple(0.0, Paddle.DOT, true), Triple(50.0, Paddle.DOT, false)), 2000.0), 60.0))
    }

    @Test
    fun `paquets - memes paquets que le banc de la station (vecteurs partages)`() {
        val file = File(System.getProperty("trx.repo") ?: "../..", "tests/protocol/cw_vectors.json")
        val vectors = Json.parseToJsonElement(file.readText(Charsets.UTF_8)).jsonObject
        assertEquals(CwPacketizer.SEQ_GAP_MS, vectors["seq_gap_ms"]!!.jsonPrimitive.double)
        assertEquals(CwPacketizer.MAX_WINDOW, vectors["max_window"]!!.jsonPrimitive.int)
        for (case in vectors["cases"]!!.jsonArray.map { it.jsonObject }) {
            val name = case["name"]!!.jsonPrimitive.content
            val edges = case["edges"]!!.jsonArray.map { e -> e.jsonArray.let { KeyEdge(it[0].jsonPrimitive.double, it[1].jsonPrimitive.int == 1) } }
            val until = case["until_ms"]!!.jsonPrimitive.double
            val expected = case["packets"]!!.jsonArray.map { it.jsonObject }
            // d'un seul coup, puis en temps réel (rappel toutes les 5 ms) : mêmes paquets
            for (step in listOf(0.0, 5.0)) {
                val p = CwPacketizer()
                val got = mutableListOf<CwPacketizer.Packet>()
                if (step == 0.0) {
                    got += p.advance(until, edges)
                } else {
                    var t = 0.0
                    var i = 0
                    while (t <= until) {
                        val due = mutableListOf<KeyEdge>()
                        while (i < edges.size && edges[i].at <= t) due += edges[i++]
                        got += p.advance(t, due)
                        t += step
                    }
                    got += p.advance(until)
                }
                assertEquals(expected.size, got.size, "$name, pas $step : nombre de paquets")
                for ((e, g) in expected.zip(got)) {
                    assertEquals(e["at"]!!.jsonPrimitive.double, g.at, "$name : instant")
                    assertSamePacket(e["msg"]!!.jsonObject, g.json, name)
                }
            }
        }
    }

    private fun assertSamePacket(e: JsonObject, g: JsonObject, name: String) {
        assertEquals(e["seq"]!!.jsonPrimitive.int, g["seq"]!!.jsonPrimitive.int, name)
        assertEquals(e["lease"]!!.jsonPrimitive.double, g["lease"]!!.jsonPrimitive.double, name)
        val ee = e["edges"]!!.jsonArray.map { it.jsonArray.map { x -> x.jsonPrimitive.double } }
        val ge = g["edges"]!!.jsonArray.map { it.jsonArray.map { x -> x.jsonPrimitive.double } }
        assertEquals(ee, ge, "$name : fenêtre à ${g["lease"]}")
        assertEquals("cw", g["type"]!!.jsonPrimitive.content)
    }

    @Test
    fun `paquets - fenetre limitee a 32 fronts`() {
        val p = CwPacketizer()
        val edges = (0 until 40).map { KeyEdge(it * 10.0, it % 2 == 0) }
        val last = p.advance(400.0, edges).last()
        assertEquals(32, last.json["edges"]!!.jsonArray.size)
    }

    @Test
    fun `decodage de sa propre manipulation`() {
        val d = CwDecoder(20)
        val k = keyer(CwInterface.STRAIGHT)
        var t = 0.0
        fun mark(len: Double) { k.press(t, Paddle.DOT, true).forEach(d::edge); t += len; k.press(t, Paddle.DOT, false).forEach(d::edge) }
        // C : -.-.  puis Q : --.-
        for (s in "-.-.") { mark(if (s == '-') 180.0 else 60.0); t += 60.0 }
        t += 120.0; d.poll(t)
        for (s in "--.-") { mark(if (s == '-') 180.0 else 60.0); t += 60.0 }
        t += 400.0; d.poll(t)
        assertEquals("CQ ", d.shown)
    }

    // ------------------------------------------------------------------ session
    private fun session(features: String = "\"ptt\",\"cw\"", role: String = "operator"): Pair<RigSession, CwLink> {
        val link = CwLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true}}""")
        return s to link
    }

    private fun armed(): Pair<RigSession, CwLink> {
        val (s, link) = session()
        s.setArmed(5, true)                                   // « Émission autorisée »
        s.cwArm(10)
        s.onMessage(20, """{"type":"result","id":${link.idOf("cw_arm")},"ok":true,"cw":{"carrier_hz":7030700,"delay_ms":300},"ptt":{"state":"TX","owner":"phone"}}""")
        s.onMessage(25, """{"type":"state","ptt":{"state":"TX","owner":"phone"},"rig":{"connected":true}}""")
        s.onMessage(30, """{"type":"cw_state","state":"armed","seq":null,"buffer_ms":0,"late":0,"lease_cuts":0,"carrier_hz":7030700}""")
        return s to link
    }

    @Test
    fun `onglet CW seulement si la station l'annonce, jamais pour un visiteur`() {
        assertTrue(session().first.snapshot.cw.offered)
        assertFalse(session("\"ptt\"").first.snapshot.cw.offered)
        val (visitor, link) = session(role = "listener")
        assertFalse(visitor.snapshot.cw.offered)
        visitor.cwArm(10)
        assertTrue(link.sent.none { "cw_arm" in it })
    }

    @Test
    fun `armement - commande envoyee, micro jamais ouvert, battements, paquets apres l'accord seulement`() {
        val (s, link) = session()
        s.cwSettings(1, CwSettings(CwInterface.STRAIGHT, wpm = 18, toneHz = 650))
        s.cwPress(2, 2.0, Paddle.DOT, true)
        assertTrue(link.cw.isEmpty())                                         // pas armée : rien ne part
        s.setArmed(5, true)                                   // « Émission autorisée »
        s.cwArm(10)
        val arm = Json.parseToJsonElement(link.sent.last { "cw_arm" in it }).jsonObject
        assertEquals("straight", arm["interface"]!!.jsonPrimitive.content)
        assertEquals(18, arm["wpm"]!!.jsonPrimitive.int); assertEquals(650, arm["tone_hz"]!!.jsonPrimitive.int)
        assertTrue(s.snapshot.cw.requested && !s.snapshot.cw.armed)
        s.onMessage(20, """{"type":"result","id":${link.idOf("cw_arm")},"ok":true,"cw":{"carrier_hz":7030650,"delay_ms":300}}""")
        s.onMessage(25, """{"type":"state","ptt":{"state":"TX","owner":"phone"},"rig":{"connected":true}}""")
        assertFalse(link.mic, "micro : jamais pendant la CW")
        assertEquals(7030650L, s.snapshot.cw.carrierHz)
        s.tick(400, true)
        assertTrue(link.sent.any { "heartbeat" in it })
        s.cwPress(500, 500.0, Paddle.DOT, true)
        s.cwPoll(520, 520.0)
        s.cwPress(560, 560.0, Paddle.DOT, false)
        assertTrue(link.cw.size >= 3)
        val first = Json.parseToJsonElement(link.cw.first()).jsonObject
        assertEquals(0, first["seq"]!!.jsonPrimitive.int)
    }

    @Test
    fun `refus de la station - desarmee avec le motif dans la langue de l'application`() {
        val (s, link) = session()
        s.setArmed(5, true)                                   // « Émission autorisée »
        s.cwArm(10)
        s.onMessage(20, """{"type":"result","id":${link.idOf("cw_arm")},"ok":false,"reason":"cw_mode","detail":"poste en USB"}""")
        assertFalse(s.snapshot.cw.armed || s.snapshot.cw.requested)
        assertEquals(Texts.refusal("cw_mode", "poste en USB"), s.snapshot.cw.notice.substringBefore(" [ORT"))
        s.cwPress(30, 30.0, Paddle.DOT, true)
        assertTrue(link.cw.isEmpty())
    }

    @Test
    fun `coupure de la station - cw_state idle desarme, plus aucun paquet`() {
        val (s, link) = armed()
        s.onMessage(40, """{"type":"cw_state","state":"idle","reason":"stop"}""")
        assertFalse(s.snapshot.cw.armed)
        assertTrue(s.snapshot.cw.notice.contains(Texts.cut("stop")))
        val before = link.cw.size
        s.cwPress(50, 50.0, Paddle.DOT, true); s.cwPoll(80, 80.0)
        assertEquals(before, link.cw.size)
    }

    @Test
    fun `desarmer, liaison perdue - plus rien ne part`() {
        val (s, link) = armed()
        s.cwDisarm(40)
        assertTrue(link.sent.last().contains("cw_disarm"))
        assertFalse(s.snapshot.cw.armed)
        val (s2, link2) = armed()
        s2.onLinkClosed(50, "silence")
        assertFalse(s2.snapshot.cw.armed || s2.snapshot.cw.offered)
        s2.cwPress(60, 60.0, Paddle.DOT, true)
        assertTrue(link2.cw.none { it.contains("\"lease\":60") })
    }

    @Test
    fun `defaut de bail - montre a l'operateur`() {
        val (s, _) = armed()
        s.onMessage(40, """{"type":"cw_fault","seq":0,"reason":"lease_expired"}""")
        assertTrue(s.snapshot.cw.notice.contains(Texts.cut("cw_lease_expired")))
        assertTrue(Tr.has("coupure.cw_lease_expired"))
    }

    @Test
    fun `fin de la CW - cause propre a la CW dite une seule fois, autre cause precedee de CW desarmee`() {
        val (s, _) = armed()
        s.onMessage(40, """{"type":"cw_state","state":"idle","reason":"cw_idle"}""")
        assertEquals(Texts.cut("cw_idle").replaceFirstChar { it.uppercase() } + ".", s.snapshot.cw.notice)
        val (s2, _) = armed()
        s2.onMessage(40, """{"type":"cw_state","state":"idle","reason":"heartbeat"}""")
        assertEquals(Tr.t("cw.ended", "reason" to Texts.cut("heartbeat")), s2.snapshot.cw.notice)
    }

    @Test
    fun `armer la CW exige Emission autorisee, comme le PTT`() {
        val (s, link) = session()
        s.cwArm(10)
        assertTrue(link.sent.none { "cw_arm" in it })
        assertFalse(s.snapshot.cw.requested || s.snapshot.cw.armed)
        assertEquals(Tr.t("cw.arm_first"), s.snapshot.cw.notice)
        s.setArmed(20, true)
        s.cwArm(30)
        assertTrue(link.sent.any { "cw_arm" in it })
    }

    @Test
    fun `Emission autorisee retiree pendant la CW armee - desarmee`() {
        val (s, link) = armed()
        s.setArmed(40, false)
        assertTrue(link.sent.last().contains("cw_disarm"))
        assertFalse(s.snapshot.cw.armed)
    }
}
