// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.NetState
import com.rfdiy.openremotetrx.protocol.NetVpnWarning
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import kotlin.math.floor
import kotlin.math.roundToInt

/**
 * Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 9, § 10) : MÊMES textes et mêmes vues que la page
 * (client.js : netView, netStatsModel, vpnText, NET_DIAGNOSES), vérifiés par NetUiTest.
 */
object NetUi {
    val DIAGNOSES = linkedMapOf(
        "app_station" to "application ou machine de la station", "lan" to "réseau local ou machine de la station",
        "box_internet" to "connexion Internet de la box", "webrtc" to "WebRTC ou passerelle", "phone_radio" to "radio du téléphone",
        "vpn_shared" to "profil VPN probablement partagé par un autre appareil", "mobile_or_tunnel" to "téléphone, réseau mobile ou tunnel",
        "unknown" to "indéterminé",
    )
    val TYPES = linkedMapOf("lan" to "réseau local", "wifi" to "Wi-Fi", "4g" to "4G", "5g" to "5G", "mobile" to "mobile", "unknown" to "inconnu")
    val LEVELS = linkedMapOf("gray" to "mesure en cours", "green" to "liaison bonne", "orange" to "liaison moyenne", "red" to "liaison faible")
    private val BARS = mapOf("gray" to 0, "red" to 1, "orange" to 2, "green" to 3)
    private val BASIS = mapOf("backlog" to "mesures du client", "health_ok" to "/health répondait", "radio_weak" to "signal faible",
                              "cell_changed" to "changement de cellule", "network_switched" to "bascule de réseau",
                              "regular_pattern" to "coupures régulières", "lan_probe_down" to "box injoignable",
                              "internet_probe_down" to "Internet injoignable")
    private val PROBES = linkedMapOf("lan" to "Box", "internet" to "Internet")

    data class Vpn(val address: String, val kind: String, val text: String)

    data class View(
        val level: String, val bars: Int, val outage: Boolean, val weak: Boolean, val title: String,
        val rows: List<Pair<String, String>>, val probes: List<Pair<String, String>>, val vpn: List<Vpn>,
        val thresholds: String, val netType: String,
    )

    fun duration(s: Double?): String {
        if (s == null || s.isNaN()) return "—"
        if (s < 60) return "${s.roundToInt()} s"
        if (s < 3600) return "${floor(s / 60).toInt()} min ${(s % 60).roundToInt().toString().padStart(2, '0')} s"
        return "${floor(s / 3600).toInt()} h ${floor((s % 3600) / 60).toInt().toString().padStart(2, '0')}"
    }

    /** Nombre comme la page : « 3,3 % », « 180 ms » (entier sans décimale), « — » si absent. */
    fun number(v: Double?, unit: String): String {
        if (v == null) return "—"
        val text = if (v == floor(v) && kotlin.math.abs(v) < 1e15) v.toLong().toString() else v.toString()
        return text.replace(".", ",") + " " + unit
    }

    fun vpnText(w: NetVpnWarning): String {
        val agents = w.agents.joinToString(" / ")
        if (w.kind == "pattern") {
            return "Coupures très régulières (toutes les ~${((w.periodMs ?: 0) / 1000.0).roundToInt()} s) sur $agents" +
                " : un autre appareil partage probablement le même profil VPN. Créez un profil par appareil."
        }
        return "Deux appareils ($agents) arrivent " + (if (w.kind == "same_time") "en même temps" else "à quelques minutes d'écart") +
            " par la même adresse ${w.address} : s'ils passent par un VPN, ils partagent probablement le même profil. Créez un profil par appareil."
    }

    /** state.net -> pastille et panneau ; null = station sans sonde. */
    fun view(net: NetState?): View? {
        if (net == null || net.level !in LEVELS) return null
        val rows = mutableListOf(
            "Perte (60 s / 10 s)" to number(net.lossPct, "%") + " / " + number(net.lossPct10, "%"),
            "Aller-retour (p95 / moyen)" to number(net.rttMs, "ms") + " / " + number(net.rttMeanMs, "ms"),
            "Gigue" to number(net.jitterMs, "ms"),
            "Réseau du client" to (TYPES[net.netType] ?: "inconnu"),
        )
        if (net.outage) rows.add(0, "COUPURE EN COURS" to (net.outageS?.let { "depuis " + duration(it.toDouble()) } ?: ""))
        net.lastOutage?.let { last ->
            rows.add("Dernière coupure" to duration(last.durationS.toDouble()) + ", il y a " + duration(last.agoS.toDouble()) + " — " +
                (last.diagnosis?.let { "tronçon probable : " + (DIAGNOSES[it] ?: it) } ?: "diagnostic en cours…"))
        }
        val probes = net.probes.filterKeys { it in PROBES }.map { (name, p) ->
            "${PROBES[name]} (" + (if (p.method == "tcp") "TCP" else "ping") + ")" to
                (when (p.ok) { false -> "NE RÉPOND PAS"; true -> "répond"; null -> "—" }) + " · perte " + number(p.lossPct, "%") + " · " + number(p.rttMs, "ms")
        }
        val th = net.thresholds
        return View(
            level = net.level, bars = BARS.getValue(net.level), outage = net.outage, weak = net.level == "red",
            title = "Liaison avec la station : " + LEVELS[net.level] + (if (net.outage) " (COUPURE)" else "") +
                (net.rttMs?.let { ", aller-retour ${number(it, "ms")}" } ?: "") + (net.lossPct?.let { ", perte ${number(it, "%")}" } ?: ""),
            rows = rows, probes = probes,
            vpn = net.vpn.filter { it.address.isNotEmpty() }.map { Vpn(it.address, it.kind, vpnText(it)) },
            thresholds = th?.let { "Seuils : orange à ${number(it.rttWarn, "ms")} ou ${number(it.lossWarn, "%")}, rouge à ${number(it.rttAlert, "ms")} ou ${number(it.lossAlert, "%")}" } ?: "",
            netType = TYPES[net.netType] ?: "—",
        )
    }

    // ------------------------------------------------------------------ statistiques (net_stats)

    data class Day(val date: String, val outages: Int, val fraction: Double, val short: String, val detail: String, val hours: List<Pair<Int, Double>>)
    data class Diagnosis(val code: String, val label: String, val count: Int, val fraction: Double)
    data class Outage(val whenMs: Long, val duration: String, val diagnosis: String, val agent: String, val basis: String, val kind: String, val net: String)
    data class Device(val device: String, val agent: String)
    data class Thresholds(val netType: String, val label: String, val inForce: Map<String, Double>, val chosen: Boolean, val days: Double,
                          val proposedRtt: NetProbe.Proposal?, val proposedLoss: NetProbe.Proposal?,
                          val rttHist: List<NetProbe.Bucket>, val lossHist: List<NetProbe.Bucket>)
    data class Stats(val summary: List<Pair<String, String>>, val days: List<Day>, val diagnoses: List<Diagnosis>,
                     val types: List<Pair<String, String>>, val outages: List<Outage>, val devices: List<Device>,
                     val thresholds: List<Thresholds>, val rttEdges: List<Double>, val lossEdges: List<Double>)

    private fun JsonObject.d(key: String): Double? = (this[key] as? JsonPrimitive)?.doubleOrNull
    private fun JsonObject.i(key: String): Int = (this[key] as? JsonPrimitive)?.intOrNull ?: 0
    private fun JsonObject.s(key: String): String = (this[key] as? JsonPrimitive)?.contentOrNull ?: ""
    private fun JsonObject.o(key: String): JsonObject? = this[key] as? JsonObject
    private fun JsonObject.a(key: String): List<kotlinx.serialization.json.JsonElement> = (this[key] as? JsonArray) ?: emptyList()

    private fun hist(e: kotlinx.serialization.json.JsonElement?): List<NetProbe.Bucket> = ((e as? JsonArray) ?: emptyList()).mapNotNull { c ->
        val pair = c as? JsonArray ?: return@mapNotNull null
        NetProbe.Bucket((pair.getOrNull(0) as? JsonPrimitive)?.intOrNull ?: 0, (pair.getOrNull(1) as? JsonPrimitive)?.intOrNull ?: 0)
    }

    private fun proposal(e: kotlinx.serialization.json.JsonElement?): NetProbe.Proposal? {
        val o = e as? JsonObject ?: return null
        return NetProbe.Proposal(o.d("warn") ?: return null, o.d("alert"))
    }

    /** Réponse de net_stats -> écran des statistiques ; null si inutilisable. */
    fun stats(stats: JsonObject?): Stats? {
        val s = stats?.o("summary") ?: return null
        val days = stats.a("per_day").mapNotNull { it as? JsonObject }
        val maxDay = maxOf(1, days.maxOfOrNull { it.i("outages") } ?: 0)
        val maxCell = maxOf(1, days.flatMap { d -> d.a("hours").map { (it as? JsonPrimitive)?.intOrNull ?: 0 } }.maxOrNull() ?: 0)
        val diag = (stats.o("by_diagnosis") ?: JsonObject(emptyMap())).mapValues { (it.value as? JsonPrimitive)?.intOrNull ?: 0 }
            .entries.sortedByDescending { it.value }
        val totalDiag = maxOf(1, diag.sumOf { it.value })
        return Stats(
            summary = listOf(
                "Coupures" to s.i("outages").toString(), "Durée cumulée" to duration(s.d("outage_s")),
                "Plus longue" to duration(s.d("longest_s")), "Temps connecté" to duration(s.d("connected_s")),
                "Disponibilité" to number(s.d("availability_pct"), "%"), "Perte moyenne" to number(s.d("loss_pct"), "%"),
            ),
            days = days.map { d ->
                val n = d.i("outages")
                Day(d.s("date"), n, n.toDouble() / maxDay, "$n · " + duration(d.d("outage_s")),
                    duration(d.d("outage_s")) + " · perte " + number(d.d("loss_pct"), "%") + " · aller-retour p95 " + number(d.d("rtt_p95_ms"), "ms"),
                    d.a("hours").map { h -> val c = (h as? JsonPrimitive)?.intOrNull ?: 0; c to c.toDouble() / maxCell })
            },
            diagnoses = diag.map { Diagnosis(it.key, DIAGNOSES[it.key] ?: it.key, it.value, it.value.toDouble() / totalDiag) },
            types = (stats.o("by_net_type") ?: JsonObject(emptyMap())).map { (k, v) ->
                val o = v as? JsonObject ?: JsonObject(emptyMap())
                (TYPES[k] ?: k) to duration(o.i("windows") * 10.0) + " mesurés · " + o.i("outages") + " coupure(s) · perte " + number(o.d("loss_pct"), "%")
            },
            outages = stats.a("outages_list").mapNotNull { it as? JsonObject }.map { o ->
                Outage((o["start_ms"] as? JsonPrimitive)?.longOrNull ?: 0, duration((o.d("duration_ms") ?: 0.0) / 1000),
                       DIAGNOSES[o.s("diagnosis")] ?: "indéterminé", o.s("agent"),
                       o.a("basis").mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.joinToString(", ") { BASIS[it] ?: it },
                       if (o.s("kind") == "disconnect") "déconnexion" else "liaison ouverte", TYPES[o.s("net_type")] ?: "")
            },
            devices = stats.a("devices").mapNotNull { it as? JsonObject }.map { Device(it.s("device"), it.s("agent")) },
            thresholds = (stats.o("thresholds") ?: JsonObject(emptyMap())).map { (k, v) ->
                val t = v as? JsonObject ?: JsonObject(emptyMap())
                val inForce = (t.o("in_force") ?: JsonObject(emptyMap())).mapNotNull { (key, value) -> (value as? JsonPrimitive)?.doubleOrNull?.let { key to it } }.toMap()
                val p = t.o("proposed")
                Thresholds(k, TYPES[k] ?: k, inForce, (t["chosen"] as? JsonPrimitive)?.contentOrNull == "true", t.d("days") ?: 0.0,
                           proposal(p?.get("rtt")), proposal(p?.get("loss")), hist(t["rtt_hist"]), hist(t["loss_hist"]))
            },
            rttEdges = (stats.o("edges")?.a("rtt_ms") ?: emptyList()).mapNotNull { (it as? JsonPrimitive)?.doubleOrNull },
            lossEdges = (stats.o("edges")?.a("loss_pct") ?: emptyList()).mapNotNull { (it as? JsonPrimitive)?.doubleOrNull },
        )
    }

    /** Texte des curseurs (page : simulate de ui.js). */
    fun simulationText(t: Thresholds, rttEdges: List<Double>, lossEdges: List<Double>, rttWarn: Double, rttAlert: Double,
                       lossWarn: Double, lossAlert: Double): String {
        val r = NetProbe.simulate(t.rttHist, rttEdges, rttWarn, rttAlert)
        val l = NetProbe.simulate(t.lossHist, lossEdges, lossWarn, lossAlert)
        fun pct(x: Double?) = if (x == null) "—" else x.toString().replace(".", ",").removeSuffix(",0") + " %"
        return "Sur l'historique — aller-retour : orange ${pct(r.orangePct)} du temps, rouge ${pct(r.redPct)} ; son dégradé dans " +
            "${pct(r.degradedRedPct)} des moments rouges et ${pct(r.degradedGreenPct)} des moments verts. Perte : orange ${pct(l.orangePct)}, rouge ${pct(l.redPct)}."
    }
}

/**
 * Sonde réseau du TÉLÉPHONE (page : _netTick de client.js) : battement chaque seconde, échos, résumé de 10 s, 10 min
 * gardées pour la station après une coupure. Kotlin pur ; RigSession l'appelle sur son fil, l'heure en ms monotones.
 * Ne fait que mesurer : rien ici n'agit sur l'émission.
 */
class NetClient {
    private class Kept(val report: JsonObject, val t: Long, var sent: Boolean)

    private val beats = ArrayDeque<NetProbe.Beat>()
    private var seq = 0L
    private var nextPing = 0L
    private var nextReport = 0L
    private var nextClock = 0L
    private val reports = ArrayDeque<Kept>()
    private var healthOk = 0
    private var healthFail = 0
    var active = false
        private set
    private var lostAtWall = 0L

    fun start(now: Long) {
        active = true
        beats.clear()
        seq = 0
        nextPing = now; nextReport = now + REPORT_EVERY_MS; nextClock = now
    }

    fun stop(wallNow: Long) {
        if (active) lostAtWall = wallNow
        active = false
    }

    /** Déconnexion voulue : plus rien à remettre (une autre station peut suivre). */
    fun forget() {
        active = false
        reports.clear()
        healthOk = 0; healthFail = 0
    }

    /** /health : réponse ou échec (couche Android, toutes les 5 s, aussi pendant une reconnexion). */
    fun health(ok: Boolean) { if (ok) healthOk++ else healthFail++ }

    /** Battement dû : (numéro, t, w ou null) ; null si rien à envoyer. */
    fun ping(now: Long, wallNow: Long): Triple<Int, Long, Long?>? {
        if (!active || now < nextPing) return null
        seq += 1
        nextPing = now + PING_EVERY_MS
        beats.addLast(NetProbe.Beat(seq, now, null))
        while (beats.isNotEmpty() && now - beats.first().sentMs > KEEP_BEATS_MS) beats.removeFirst()
        val w = if (now >= nextClock) { nextClock = now + CLOCK_EVERY_MS; wallNow } else null
        return Triple(seq.toInt(), now, w)
    }

    fun pong(seqIn: Int, t: Long, now: Long) {
        val i = beats.indexOfFirst { it.seq == seqIn.toLong() }
        if (i >= 0 && beats[i].sentMs == t && beats[i].pongMs == null) beats[i] = beats[i].copy(pongMs = now)
    }

    /** Résumé de 10 s dû (connecté) ; gardé pour la remise après une coupure. */
    fun report(now: Long, wallNow: Long, netType: String?, ice: String?, open: Boolean): JsonObject? {
        if (!active || now < nextReport) return null
        nextReport = now + REPORT_EVERY_MS
        val s = NetProbe.windowStats(beats.toList(), now, REPORT_EVERY_MS)
        val r = buildJsonObject {
            put("t", wallNow); put("net_type", netType)
            put("loss_pct", s.lossPct); put("rtt_mean_ms", s.rttMeanMs); put("rtt_p95_ms", s.rttP95Ms); put("jitter_ms", s.jitterMs)
            put("health_ok", minOf(100, healthOk)); put("health_fail", minOf(100, healthFail)); put("degraded", false)
            put("ice", ice)
        }
        healthOk = 0; healthFail = 0
        keep(r, wallNow, open)
        return r
    }

    /** Pendant une reconnexion : un résumé hors ligne toutes les 10 s (/health et réseau seulement). */
    fun offline(now: Long, wallNow: Long, netType: String?) {
        if (now < nextReport) return
        nextReport = now + REPORT_EVERY_MS
        val r = buildJsonObject {
            put("t", wallNow); put("net_type", netType); put("health_ok", minOf(100, healthOk)); put("health_fail", minOf(100, healthFail))
            put("degraded", false)
        }
        healthOk = 0; healthFail = 0
        keep(r, wallNow, false)
    }

    private fun keep(r: JsonObject, t: Long, sent: Boolean) {
        reports.addLast(Kept(r, t, sent))
        while (reports.size > KEEP_REPORTS) reports.removeFirst()
    }

    /** Résumés à remettre après une reconnexion : jamais partis, et ceux des 30 s avant la perte. Tous marqués partis. */
    fun backlog(): List<JsonObject> {
        val since = if (lostAtWall > 0) lostAtWall - BACKLOG_BEFORE_MS else Long.MAX_VALUE   // pas de perte : jamais partis seulement
        val out = reports.filter { !it.sent || it.t >= since }.map { it.report }
        reports.forEach { it.sent = true }
        lostAtWall = 0                                           // remis une seule fois
        return out
    }

    companion object {
        const val PING_EVERY_MS = 1000L
        const val REPORT_EVERY_MS = 10_000L
        const val CLOCK_EVERY_MS = 60_000L
        const val KEEP_BEATS_MS = 70_000L
        const val KEEP_REPORTS = 60
        const val BACKLOG_BEFORE_MS = 30_000L
        const val HEALTH_EVERY_MS = 5000L
    }
}
