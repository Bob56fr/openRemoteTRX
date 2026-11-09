// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** Sonde de qualité réseau : mêmes calculs que la station et la page (tests/protocol/netprobe_vectors.json). */
class NetProbeTest {
    private val shared: JsonObject =
        Json.parseToJsonElement(File(System.getProperty("trx.repo"), "tests/protocol/netprobe_vectors.json").readText()).jsonObject

    private fun JsonObject.cases(key: String) = getValue(key).jsonArray.map { it.jsonObject }
    private fun JsonObject.name() = getValue("name").jsonPrimitive.content
    private fun JsonElement?.d(): Double? = this?.jsonPrimitive?.doubleOrNull
    private fun JsonElement?.l(): Long? = this?.jsonPrimitive?.longOrNull
    private fun edges(metric: String) = if (metric == "rtt") NetProbe.RTT_EDGES_MS else NetProbe.LOSS_EDGES_PCT
    private fun hist(c: JsonObject) = c.getValue("hist").jsonArray.map {
        NetProbe.Bucket(it.jsonObject.getValue("n").jsonPrimitive.int, it.jsonObject.getValue("degraded").jsonPrimitive.int)
    }

    @Test
    fun `constantes, celles de la station`() {
        val k = shared.getValue("constants").jsonObject
        assertEquals(NetProbe.LATE_MS, k.getValue("late_ms").jsonPrimitive.long)
        assertEquals(NetProbe.WINDOWS_MS, k.getValue("windows_ms").jsonArray.map { it.jsonPrimitive.long })
        assertEquals(NetProbe.MIN_MEASURED_MS, k.getValue("min_measured_ms").jsonPrimitive.long)
        assertEquals(NetProbe.RECENT_OUTAGE_MS, k.getValue("recent_outage_ms").jsonPrimitive.long)
        assertEquals(NetProbe.DIAGNOSES, k.getValue("diagnoses").jsonArray.map { it.jsonPrimitive.content })
        val b = shared.getValue("buckets").jsonObject
        assertEquals(NetProbe.RTT_EDGES_MS, b.getValue("rtt_edges_ms").jsonArray.map { it.jsonPrimitive.double })
        assertEquals(NetProbe.LOSS_EDGES_PCT, b.getValue("loss_edges_pct").jsonArray.map { it.jsonPrimitive.double })
    }

    @Test
    fun `fenetres, perte, aller-retour, gigue, hors sequence`() {
        for (c in shared.cases("window_stats")) {
            val beats = c.getValue("beats").jsonArray.map { r ->
                val a = r.jsonArray
                NetProbe.Beat(a[0].jsonPrimitive.long, a[1].jsonPrimitive.long, a[2].l())
            }
            val e = c.getValue("expect").jsonObject
            val got = NetProbe.windowStats(beats, c.getValue("now_ms").jsonPrimitive.long, c.getValue("window_ms").jsonPrimitive.long)
            val want = NetProbe.WindowStats(
                e.getValue("expected").jsonPrimitive.int, e.getValue("received").jsonPrimitive.int, e.getValue("lost").jsonPrimitive.int,
                e.getValue("late").jsonPrimitive.int, e["loss_pct"].d(), e["rtt_mean_ms"].d(), e["rtt_p95_ms"].l(), e["rtt_max_ms"].l(),
                e["jitter_ms"].d(), e.getValue("out_of_order").jsonPrimitive.int,
            )
            assertEquals(want, got, c.name())
        }
    }

    @Test
    fun `coupures`() {
        for (c in shared.cases("outages")) {
            val d = NetProbe.OutageDetector(c.getValue("missed").jsonPrimitive.int, c.getValue("interval_ms").jsonPrimitive.long)
            val got = mutableListOf<NetProbe.OutageEvent>()
            for (ev in c.getValue("events").jsonArray.map { it.jsonArray }) {
                when (ev[0].jsonPrimitive.content) {
                    "tick" -> got += d.tick(ev[1].jsonPrimitive.long)
                    "ping" -> got += d.ping(ev[1].jsonPrimitive.long, ev[2].jsonPrimitive.long)
                    else -> got += d.pong(ev[1].jsonPrimitive.long, ev[2].jsonPrimitive.long)
                }
            }
            val want = c.getValue("expect").jsonArray.map { it.jsonObject }.map {
                NetProbe.OutageEvent(it.getValue("type").jsonPrimitive.content, it.getValue("start_ms").jsonPrimitive.long,
                    it["detected_ms"].l(), it["end_ms"].l(), it["duration_ms"].l())
            }
            assertEquals(want, got, c.name())
        }
    }

    @Test
    fun `niveau de l'indicateur`() {
        val t = shared.getValue("thresholds").jsonObject
        fun v(k: String) = t.getValue(k).jsonPrimitive.double
        val th = NetProbe.Thresholds(v("loss_warn"), v("loss_alert"), v("rtt_warn"), v("rtt_alert"), v("rsrp_warn"), v("rsrp_alert"), v("sinr_warn"), v("sinr_alert"))
        for (c in shared.cases("level")) {
            val got = NetProbe.level(c.getValue("measured_ms").jsonPrimitive.long, c["loss_pct"].d(), c["rtt_p95_ms"].d(),
                c.getValue("outage_active").jsonPrimitive.boolean, c["since_outage_end_ms"].l(), c["rsrp_dbm"].d(), c["sinr_db"].d(), th)
            assertEquals(c.getValue("expect").jsonPrimitive.content, got, c.name())
        }
    }

    @Test
    fun `diagnostic et motif regulier`() {
        for (c in shared.cases("diagnose")) {
            val facts = c.getValue("facts").jsonObject.mapValues { it.value.jsonPrimitive.booleanOrNull ?: false }
            assertEquals(c.getValue("expect").jsonPrimitive.content, NetProbe.diagnose(facts), c.name())
        }
        for (c in shared.cases("regular_pattern")) {
            val outages = c.getValue("outages").jsonArray.map {
                NetProbe.Outage(it.jsonObject.getValue("start_ms").jsonPrimitive.long, it.jsonObject.getValue("duration_ms").jsonPrimitive.long)
            }
            val e = c.getValue("expect").jsonObject
            assertEquals(NetProbe.Pattern(e.getValue("regular").jsonPrimitive.boolean, e["period_ms"].l()),
                NetProbe.regularPattern(outages, c.getValue("now_ms").jsonPrimitive.long), c.name())
        }
    }

    @Test
    fun `histogrammes, cases, seuils proposes, essai de seuils`() {
        for (c in shared.getValue("buckets").jsonObject.cases("cases")) {
            val metric = c.getValue("metric").jsonPrimitive.content
            assertEquals(c.getValue("expect").jsonPrimitive.int, NetProbe.bucket(c.getValue("value").jsonPrimitive.double, edges(metric)), c.toString())
        }
        for (c in shared.cases("propose")) {
            val got = NetProbe.propose(hist(c), edges(c.getValue("metric").jsonPrimitive.content), c.getValue("days").jsonPrimitive.double)
            val e = c["expect"]
            if (e == null || e is JsonNull) assertNull(got, c.name())
            else assertEquals(NetProbe.Proposal(e.jsonObject.getValue("warn").jsonPrimitive.double, e.jsonObject["alert"].d()), got, c.name())
        }
        for (c in shared.cases("simulate")) {
            val got = NetProbe.simulate(hist(c), edges(c.getValue("metric").jsonPrimitive.content),
                c.getValue("warn").jsonPrimitive.double, c.getValue("alert").jsonPrimitive.double)
            val e = c.getValue("expect").jsonObject
            assertEquals(NetProbe.Simulation(e["orange_pct"].d(), e["red_pct"].d(), e["degraded_red_pct"].d(), e["degraded_green_pct"].d()), got, c.name())
        }
    }

    @Test
    fun `arrondi au dixieme, moitie vers le haut`() {
        assertEquals(listOf(0.3, 0.4, 2.5, -0.2), listOf(0.25, 0.35, 2.45, -0.25).map { NetProbe.round1(it) })
    }
}
