// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Sonde de qualité réseau : mêmes textes que la page (client.js), battement et résumés du téléphone. */
class NetUiTest {
    private val repo = System.getProperty("trx.repo") ?: "../.."
    private val page = File(repo, "trxstation/gateway/api/static/client.js").readText()
    private val messages = Json.parseToJsonElement(File(repo, "tests/protocol/messages.json").readText()).jsonObject

    private fun pageTable(name: String): Map<String, String> {
        val body = Regex("const $name = \\{(.*?)\\};", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        return Regex("([a-z_0-9]+|\"[a-z_0-9]+\"): \"([^\"]*)\"").findAll(body)
            .associate { it.groupValues[1].trim('"') to it.groupValues[2] }
    }

    @Test
    fun `textes communs avec la page`() {
        assertEquals(pageTable("NET_DIAGNOSES"), NetUi.DIAGNOSES)
        assertEquals(pageTable("NET_TYPES"), NetUi.TYPES)
        assertEquals(pageTable("NET_LEVELS"), NetUi.LEVELS)
    }

    @Test
    fun `state net d'exemple - meme vue que la page`() {
        val state = ServerMessages.decode(messages["state_net"].toString()) as State
        val v = assertNotNull(NetUi.view(state.net))
        assertEquals("orange", v.level); assertEquals(2, v.bars); assertEquals(false, v.weak)
        assertTrue(v.title.contains("liaison moyenne, aller-retour 180 ms, perte 3,3 %"), v.title)
        assertEquals("Perte (60 s / 10 s)" to "3,3 % / 0 %", v.rows[0])
        assertTrue(v.rows.last().second.contains("il y a 1 min 15 s — tronçon probable : téléphone, réseau mobile ou tunnel"))
        assertTrue(v.vpn[0].text.contains("(page Windows / android 0.53.0) arrivent en même temps par la même adresse 192.168.27.2"))
        assertTrue(v.thresholds.contains("orange à 250 ms ou 2 %, rouge à 600 ms ou 10 %"), v.thresholds)
        assertNull(NetUi.view(null))
        assertNull(NetUi.view((ServerMessages.decode("""{"type":"state","net":{"level":"violet"}}""") as State).net))
    }

    @Test
    fun `coupure en cours et sondes de la station`() {
        val s = ServerMessages.decode("""{"type":"state","net":{"level":"red","outage":true,"outage_s":7,
            "probes":{"lan":{"method":"icmp","ok":false,"loss_pct":50,"rtt_ms":null}}}}""") as State
        val v = assertNotNull(NetUi.view(s.net))
        assertTrue(v.weak); assertEquals("COUPURE EN COURS" to "depuis 7 s", v.rows[0])
        assertEquals("Box (ping)" to "NE RÉPOND PAS · perte 50 % · —", v.probes[0])
    }

    @Test
    fun `statistiques 30 jours`() {
        val stats = Json.parseToJsonElement("""{"days":30,"summary":{"outages":3,"outage_s":75,"longest_s":40,"connected_s":7200,"availability_pct":99,"loss_pct":0.4},
          "per_day":[{"date":"2026-11-08","outages":1,"outage_s":40,"hours":[0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]},
                     {"date":"2026-11-09","outages":2,"outage_s":35,"hours":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,0,0,0,0,0]}],
          "by_diagnosis":{"vpn_shared":2,"lan":1},"by_net_type":{"4g":{"windows":360,"outages":2,"loss_pct":0.5}},
          "thresholds":{"4g":{"in_force":{"rtt_warn":250,"rtt_alert":600,"loss_warn":2,"loss_alert":10},"chosen":false,"days":2,
                        "rtt_hist":[[10,0],[5,1]],"loss_hist":[[15,1]],"proposed":{"rtt":null,"loss":null}}},
          "edges":{"rtt_ms":[50],"loss_pct":[0.5]},
          "outages_list":[{"start_ms":1762700000000,"duration_ms":6000,"diagnosis":"vpn_shared","basis":["backlog","regular_pattern"],"agent":"android","net_type":"4g","kind":"in_session"}],
          "devices":[{"device":"aaaa","agent":"android","last_ms":1}]}""").jsonObject
        val m = assertNotNull(NetUi.stats(stats))
        assertEquals("Coupures" to "3", m.summary[0]); assertEquals("Durée cumulée" to "1 min 15 s", m.summary[1])
        assertEquals(1.0, m.days[1].fraction); assertEquals(0.5, m.days[0].fraction)
        assertEquals("vpn_shared", m.diagnoses[0].code)
        assertEquals("4G" to "1 h 00 mesurés · 2 coupure(s) · perte 0,5 %", m.types[0])
        assertEquals("mesures du client, coupures régulières", m.outages[0].basis)
        assertEquals(250.0, m.thresholds[0].inForce["rtt_warn"]); assertEquals(NetProbe.Bucket(5, 1), m.thresholds[0].rttHist[1])
        assertNull(NetUi.stats(null))
    }

    @Test
    fun `sonde du telephone - battements, echos, resume, remise apres coupure`() {
        val c = NetClient()
        c.start(0)
        for (i in 0 until 12) {
            val ping = assertNotNull(c.ping(i * 1000L, 1_762_700_000_000 + i * 1000L))
            if (i == 0) assertNotNull(ping.third) else assertNull(ping.third)              // heure du client : une fois par minute
            c.pong(ping.first, ping.second, ping.second + 40)
        }
        c.health(true); c.health(false)
        val r = assertNotNull(c.report(10_000, 1_762_700_010_000, "4g", null, true))
        assertEquals("0.0", r["loss_pct"].toString()); assertEquals("40.0", r["rtt_mean_ms"].toString())
        assertEquals("1", r["health_ok"].toString()); assertEquals("1", r["health_fail"].toString())
        assertNull(c.report(15_000, 1_762_700_015_000, "4g", null, true))                   // un résumé toutes les 10 s
        c.stop(1_762_700_020_000)
        c.offline(30_000, 1_762_700_030_000, "4g")
        val backlog = c.backlog()
        assertEquals(2, backlog.size)                                                        // celui d'avant la perte + hors ligne
        assertTrue(c.backlog().isEmpty())                                                    // remis une seule fois
    }

    @Test
    fun `radio du telephone dans le resume - valeurs hors bornes jetees, faits transmis`() {
        val c = NetClient()
        c.start(0)
        val radio = RadioSample("4g", rsrpDbm = -98, sinrDb = 12, level = 3, cellChanged = true, netSwitched = false)
        val r = assertNotNull(c.report(10_000, 1_762_700_010_000, "mobile", null, true, radio))
        assertEquals("-98", r["rsrp_dbm"].toString()); assertEquals("12", r["sinr_db"].toString())
        assertEquals("3", r["signal_level"].toString()); assertEquals("true", r["cell_changed"].toString())
        val odd = assertNotNull(c.report(20_000, 1_762_700_020_000, "5g", null, true, RadioSample("5g", rsrpDbm = 2147483647, sinrDb = -99, level = 7)))
        assertEquals("null", odd["rsrp_dbm"].toString()); assertEquals("null", odd["sinr_db"].toString()); assertEquals("null", odd["signal_level"].toString())
        assertEquals("4G · -98 dBm · S/B 12 dB · niveau 3/4", radio.text())
        assertEquals("—", RadioSample().text())
    }

    @Test
    fun `session - la radio fournit le type de reseau du resume`() {
        val link = object : SessionLink {
            val sent = mutableListOf<String>()
            override fun startAttempt() {}
            override fun send(text: String): Boolean { sent += text; return true }
            override fun setMicOpen(open: Boolean) {}
            override fun close() {}
            override fun alert(kind: LinkAlert) {}
        }
        var reads = 0
        val s = RigSession(link, netType = { "mobile" }, radio = { reads++; RadioSample("5g", -90, 15, 4) }) { 1_762_700_000_000L }
        s.begin(0, 30); s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","features":["netprobe"]}""")
        for (i in 1..22) { s.onMessage(i * 500L, """{"type":"state","ptt":{"state":"RX"}}"""); s.tick(i * 500L, true) }
        val report = link.sent.first { it.contains("\"cmd\":\"net_report\"") }
        assertTrue(report.contains("\"net_type\":\"5g\"") && report.contains("\"rsrp_dbm\":-90"), report)
        assertEquals(1, reads)                                                               // lue une fois par résumé
    }

    @Test
    fun `session - net_ping, net_pong, resumes et remise a la reconnexion`() {
        val link = object : SessionLink {
            val sent = mutableListOf<String>()
            override fun startAttempt() {}
            override fun send(text: String): Boolean { sent += text; return true }
            override fun setMicOpen(open: Boolean) {}
            override fun close() {}
            override fun alert(kind: LinkAlert) {}
        }
        var wall = 1_762_700_000_000L
        val s = RigSession(link, netType = { "wifi" }) { wall }
        s.begin(0, 30); s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","features":["ptt","netprobe"]}""")
        for (i in 1..22) { wall += 500; s.onMessage(i * 500L, """{"type":"state","ptt":{"state":"RX"}}"""); s.tick(i * 500L, true) }
        assertTrue(link.sent.count { it.contains("\"cmd\":\"net_ping\"") } >= 10)
        assertTrue(link.sent.any { it.contains("\"cmd\":\"net_report\"") && it.contains("\"net_type\":\"wifi\"") })
        s.onMessage(11_100, """{"type":"net_ping","seq":5,"t":777}""")
        assertTrue(link.sent.last().startsWith("""{"cmd":"net_pong","seq":5,"t":777,"tr":11100"""))
        assertTrue(s.netProbing)
        s.onLinkClosed(12_000, "datachannel_closed")
        assertTrue(s.netProbing)                                                             // /health continue pendant la reconnexion
        s.tick(12_400, true); s.answered(12_500)
        s.onMessage(12_600, """{"type":"hello","protocol":1,"client_id":"phone","features":["netprobe"]}""")
        assertTrue(link.sent.any { it.startsWith("""{"cmd":"net_backlog"""") })
        s.disconnect(13_000)
        assertEquals(false, s.netProbing)
    }
}
