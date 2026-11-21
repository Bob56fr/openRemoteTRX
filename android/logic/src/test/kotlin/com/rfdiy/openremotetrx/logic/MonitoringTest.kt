// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.util.Base64
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class MoLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
    fun last(cmd: String): JsonObject = Json.parseToJsonElement(sent.last { it.contains("\"cmd\":\"$cmd\"") }).jsonObject
    fun count(cmd: String, action: String? = null) = sent.count {
        it.contains("\"cmd\":\"$cmd\"") && (action == null || it.contains("\"action\":\"$action\""))
    }
}

/** Monitoring inter-stations : mêmes règles et mêmes textes que la page (monitoring.js) et la station. */
class MonitoringTest {
    private val repo = System.getProperty("trx.repo") ?: "../.."
    private val vectors = Json.parseToJsonElement(File(repo, "tests/protocol/monlink_vectors.json").readText()).jsonObject
    private val page = File(repo, "trxstation/gateway/api/static/monitoring.js").readText()
    private fun obj(text: String) = Json.parseToJsonElement(text).jsonObject

    @Test
    fun `code tape - meme tolerance que la station et la page`() {
        val invite = vectors["invite"]!!.jsonObject
        val code = invite["code"]!!.jsonPrimitive.content
        for (typed in invite["typed_variants"]!!.jsonArray) {
            assertEquals(code.take(5) + "-" + code.drop(5), Monitoring.normalizeCode(typed.jsonPrimitive.content))
        }
        assertEquals("01110-ABCDE", Monitoring.normalizeCode("o1il0-abcde"))
        for (bad in listOf("ABCDE-FGHJ", "ABCDE-FGHJKM", "ABCDE-FGHJU", "x".repeat(50))) assertNull(Monitoring.normalizeCode(bad))
    }

    @Test
    fun `memes textes que la page`() = PageI18n.assertSameTexts("monitoring.js", "Monitoring.kt", "monitoring.role_",
        "monitoring.state_", "monitoring.profile_", "monitoring.report_pending", "monitoring.assist_pending",
        "monitoring.silent", "monitoring.no_news_received")

    @Test
    fun `liaison - boutons selon le role et l etat, jamais de commande vers l autre station`() {
        assertEquals(listOf("fingerprint", "end"), Monitoring.actions(obj("""{"role":"receiver","state":"confirm"}""")))
        assertEquals(listOf("assist", "report", "download", "end"), Monitoring.actions(obj("""{"role":"receiver","state":"active","reports":2}""")))
        assertEquals(listOf("answer", "send_report", "profile", "pause", "end"),
                     Monitoring.actions(obj("""{"role":"emitter","state":"active","request":{"assist":3600}}""")))
        assertEquals(listOf("resume", "end"), Monitoring.actions(obj("""{"role":"emitter","state":"paused","request":null}""")))
        val l = Monitoring.link(obj("""{"peer":"a","pseudo":"F4XYZ","role":"receiver","state":"active","last_rx_age":125,"silent":true,"reports":1,
            "last_hb":{"v":"0.166.0","gateway":"ok","safe":null},"last_st":{"system":{"cpu":7,"mem":30,"disk":20,"temp":null},"rig":{"cat":true,"tx":"RX","clients":1}}}"""))
        assertEquals("F4XYZ : vous aidez cette station, active", l.title)
        assertEquals(listOf("dernières nouvelles il y a 2 min", "SANS NOUVELLES (alerte envoyée)", "1 rapport(s) reçu(s)"), l.details)
        assertEquals("warn", l.level)
        assertEquals(listOf("Station : version 0.166.0, passerelle ok, mode sûr : non",
                            "Machine : processeur 7 %, mémoire 30 %, disque 20 %, température --",
                            "Poste : CAT OK, émission RX, 1 connexion(s)"), l.stationLines)
        assertEquals("""{"rig":true,"events_min":"avertissement","freq_mode":false}""", Monitoring.profile("diagnostic", false).toString())
        assertEquals("2026-11-21 10:00 ORT-2104 erreur CAT lent",
                     Monitoring.eventLine(obj("""{"content":{"ts":"2026-11-21T10:00:00.000Z","code":"ORT-2104","gravite":"erreur","titre":"CAT lent"}}""")))
        assertEquals("2026-11-21 07:58 ORT-8008 critique Mode sûr — trop de redémarrages (×7 depuis 2026-11-21 06:58)",
                     Monitoring.eventLine(obj("""{"content":{"ts":"2026-11-21T07:58:00.000Z","code":"ORT-8008","gravite":"critique","titre":"Mode sûr"},"text":"trop de redémarrages","count":7,"first":"2026-11-21T06:58:00.000Z"}""")))
    }

    @Test
    fun `refus avec le code du catalogue entre crochets`() {
        assertEquals("Refusé [ORT-5116]", Texts.withCode("Refusé", "ORT-5116"))
        assertEquals("Refusé", Texts.withCode("Refusé", "<b>ORT</b>"))
        assertEquals("Refusé", Texts.withCode("Refusé", null))
    }

    @Test
    fun `session - offert aux operateurs, vue relue, refus avec son code, rapport recolle`() {
        val link = MoLink()
        val s = RigSession(link) { 0L }
        var report: Pair<String, ByteArray>? = null
        s.onMonitoringReport = { name, bytes -> report = name to bytes }
        s.begin(0, 30); s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"listener","features":["ptt","monitoring"]}""")
        assertNull(s.snapshot.monitoring); assertEquals(0, link.count("monitoring"))
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","features":["ptt","monitoring"]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true}}""")
        assertEquals(1, link.count("monitoring", "view"))
        val id = { link.last("monitoring")["id"]!!.jsonPrimitive.content }
        s.onMessage(1, """{"type":"result","id":${id()},"ok":true,"action":"view","data":{"pseudo":"Dev 56","registered":true,"links":[]}}""")
        assertEquals("Pseudo Dev 56 · station enregistrée auprès du relais", Monitoring.status(s.snapshot.monitoring!!.data))
        s.monitoringAction(2, "confirm", obj("""{"peer":"${"0".repeat(32)}"}"""))
        s.onMessage(3, """{"type":"result","id":${id()},"ok":false,"reason":"profile","detail":"profil obligatoire","ort":"ORT-4014"}""")
        assertEquals("profil obligatoire [ORT-4014]", s.snapshot.monitoring!!.notice)
        s.monitoringAction(4, "invite")
        s.onMessage(5, """{"type":"result","id":${id()},"ok":true,"action":"invite","data":{"code":"B8Y9W-0FJFD","expires":1}}""")
        assertEquals("B8Y9W-0FJFD", s.snapshot.monitoring!!.code)
        // rapport par morceaux : demandés l'un après l'autre, recollés à l'identique
        val data = ByteArray(70_000) { (it % 251).toByte() }
        val parts = listOf(data.copyOfRange(0, 30720), data.copyOfRange(30720, 61440), data.copyOfRange(61440, data.size))
            .map { Base64.getUrlEncoder().withoutPadding().encodeToString(it) }
        s.monitoringReport(6, "a".repeat(32))
        for ((i, p) in parts.withIndex()) {
            assertEquals(i.toLong(), link.last("monitoring")["args"]!!.jsonObject["part"]!!.jsonPrimitive.content.toLong())
            s.onMessage(7L + i, """{"type":"result","id":${id()},"ok":true,"action":"report_part","data":{"name":"rapport-F4XYZ.zip","size":70000,"parts":3,"part":$i,"data":"$p"}}""")
        }
        assertEquals("rapport-F4XYZ.zip", report!!.first)
        assertContentEquals(data, report!!.second)
    }
}
