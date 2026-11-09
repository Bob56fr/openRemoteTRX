// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.sqrt

/**
 * Sonde de qualité réseau (docs/netprobe-cahier-des-charges.md § 4.4, 4.5, 7, 8.3, 9.1, 9.6) : calculs purs de
 * l'application, MÊMES résultats que la station (trxstation/netprobe/calc.py) et la page (netprobe.js) ; exemples
 * partagés tests/protocol/netprobe_vectors.json. Durées en ms sur l'horloge MONOTONE de celui qui envoie le battement.
 * Rien ici n'agit sur le poste : la sonde mesure et affiche.
 */
object NetProbe {
    const val LATE_MS = 5_000L
    val WINDOWS_MS = listOf(10_000L, 60_000L)
    const val MIN_MEASURED_MS = 10_000L
    const val RECENT_OUTAGE_MS = 120_000L
    val RTT_EDGES_MS = listOf(50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 400.0, 600.0, 800.0, 1000.0)
    val LOSS_EDGES_PCT = listOf(0.5, 1.0, 2.0, 5.0, 10.0, 20.0)
    val DIAGNOSES = listOf("app_station", "lan", "box_internet", "webrtc", "phone_radio", "vpn_shared", "mobile_or_tunnel", "unknown")

    private const val PROPOSE_MIN_WINDOWS = 2_000
    private const val PROPOSE_MIN_DAYS = 7.0
    private const val PROPOSE_MIN_BUCKET = 20
    private const val PROPOSE_WARN_RATIO = 0.05
    private const val PROPOSE_ALERT_RATIO = 0.25
    private const val PATTERN_WINDOW_MS = 600_000L
    private const val PATTERN_MIN_OUTAGES = 4
    private const val PATTERN_MIN_PERIOD_MS = 10_000.0
    private const val PATTERN_MAX_PERIOD_MS = 150_000.0
    private const val PATTERN_MAX_PERIOD_CV = 0.25
    private const val PATTERN_MAX_DURATION_CV = 0.5

    /** Un net_ping envoyé ; `pongMs` = arrivée de son écho (null : pas encore). */
    data class Beat(val seq: Long, val sentMs: Long, val pongMs: Long?)

    data class WindowStats(
        val expected: Int, val received: Int, val lost: Int, val late: Int, val lossPct: Double?,
        val rttMeanMs: Double?, val rttP95Ms: Long?, val rttMaxMs: Long?, val jitterMs: Double?, val outOfOrder: Int,
    )

    /** Début (`endMs` null) ou fin d'une coupure. */
    data class OutageEvent(val type: String, val startMs: Long, val detectedMs: Long? = null, val endMs: Long? = null, val durationMs: Long? = null)

    data class Thresholds(
        val lossWarn: Double, val lossAlert: Double, val rttWarn: Double, val rttAlert: Double,
        val rsrpWarn: Double, val rsrpAlert: Double, val sinrWarn: Double, val sinrAlert: Double,
    )

    data class Pattern(val regular: Boolean, val periodMs: Long?)
    data class Outage(val startMs: Long, val durationMs: Long)
    data class Bucket(val n: Int, val degraded: Int)
    data class Proposal(val warn: Double, val alert: Double?)
    data class Simulation(val orangePct: Double?, val redPct: Double?, val degradedRedPct: Double?, val degradedGreenPct: Double?)

    /** Arrondi au dixième, moitié vers le haut (comme la station et la page). */
    fun round1(v: Double): Double = floor(v * 10 + 0.5) / 10

    /** Indicateurs d'une fenêtre glissante : voir calc.window_stats. */
    fun windowStats(beats: List<Beat>, nowMs: Long, windowMs: Long): WindowStats {
        val inside = beats.filter { nowMs - windowMs < it.sentMs && it.sentMs <= nowMs }
        val received = mutableListOf<Beat>()
        var lost = 0
        var late = 0
        for (b in inside) {
            val pong = b.pongMs
            if (pong != null && pong <= nowMs) {
                if (pong - b.sentMs >= LATE_MS) { lost++; late++ } else received.add(b)
            } else if (nowMs - b.sentMs >= LATE_MS) lost++
        }
        val expected = received.size + lost
        val rtts = received.sortedBy { it.seq }.map { it.pongMs!! - it.sentMs }
        var jitter = 0.0
        for (i in 1 until rtts.size) jitter += (abs(rtts[i] - rtts[i - 1]) - jitter) / 16
        var outOfOrder = 0
        var highest: Long? = null
        for (b in received.sortedWith(compareBy<Beat>({ it.pongMs }, { it.seq }))) {
            if (highest != null && b.seq < highest) outOfOrder++
            highest = if (highest == null) b.seq else maxOf(highest, b.seq)
        }
        val ordered = rtts.sorted()
        return WindowStats(
            expected = expected, received = received.size, lost = lost, late = late,
            lossPct = if (expected > 0) round1(100.0 * lost / expected) else null,
            rttMeanMs = if (rtts.isNotEmpty()) round1(rtts.sum().toDouble() / rtts.size) else null,
            rttP95Ms = if (ordered.isNotEmpty()) ordered[(95 * ordered.size + 99) / 100 - 1] else null,
            rttMaxMs = ordered.lastOrNull(),
            jitterMs = if (rtts.size > 1) round1(jitter) else null,
            outOfOrder = outOfOrder,
        )
    }

    /** Coupures : voir calc.OutageDetector (début à l'envoi du premier battement manqué, fin au premier écho reçu). */
    class OutageDetector(private val missed: Int = 3, private val intervalMs: Long = 1_000) {
        private val pending = LinkedHashMap<Long, Long>()
        var startMs: Long? = null
            private set

        fun ping(seq: Long, nowMs: Long): List<OutageEvent> {
            val events = tick(nowMs)
            pending[seq] = nowMs
            return events
        }

        fun pong(@Suppress("UNUSED_PARAMETER") seq: Long, nowMs: Long): List<OutageEvent> {
            pending.clear()
            val start = startMs ?: return emptyList()
            startMs = null
            return listOf(OutageEvent("end", start, endMs = nowMs, durationMs = nowMs - start))
        }

        fun tick(nowMs: Long): List<OutageEvent> {
            if (startMs != null) return emptyList()
            val late = pending.values.filter { nowMs - it >= intervalMs }.sorted()
            if (late.size < missed) return emptyList()
            startMs = late[0]
            return listOf(OutageEvent("start", late[0], detectedMs = nowMs))
        }
    }

    /** Niveau de l'indicateur : gray, green, orange ou red. Voir calc.level. */
    fun level(
        measuredMs: Long, lossPct: Double?, rttP95Ms: Double?, outageActive: Boolean, sinceOutageEndMs: Long?,
        rsrpDbm: Double?, sinrDb: Double?, th: Thresholds,
    ): String {
        if (outageActive) return "red"
        if (measuredMs < MIN_MEASURED_MS) return "gray"
        if ((lossPct != null && lossPct >= th.lossAlert) || (rttP95Ms != null && rttP95Ms >= th.rttAlert) ||
            (rsrpDbm != null && rsrpDbm < th.rsrpAlert) || (sinrDb != null && sinrDb < th.sinrAlert)) return "red"
        if ((sinceOutageEndMs != null && sinceOutageEndMs < RECENT_OUTAGE_MS) ||
            (lossPct != null && lossPct >= th.lossWarn) || (rttP95Ms != null && rttP95Ms >= th.rttWarn) ||
            (rsrpDbm != null && rsrpDbm < th.rsrpWarn) || (sinrDb != null && sinrDb < th.sinrWarn)) return "orange"
        return "green"
    }

    /** Tronçon probable d'une coupure : voir calc.diagnose. Faits absents de la table = inconnus. */
    fun diagnose(facts: Map<String, Boolean>): String {
        if (facts["station_restarted"] == true) return "app_station"
        if (facts["lan_probe_down"] == true) return "lan"
        if (facts["internet_probe_down"] == true) return "box_internet"
        if (facts["backlog"] != true) return "unknown"
        if (facts["health_ok"] == true) return "webrtc"
        if (facts["radio_weak"] == true || facts["cell_changed"] == true || facts["network_switched"] == true) return "phone_radio"
        if (facts["regular_pattern"] == true) return "vpn_shared"
        if (facts["health_ok"] == false) return "mobile_or_tunnel"
        return "unknown"
    }

    private fun cv(values: List<Double>): Double {
        var sum = 0.0
        for (v in values) sum += v
        val mean = sum / values.size
        if (mean <= 0) return Double.POSITIVE_INFINITY
        var sq = 0.0
        for (v in values) sq += (v - mean) * (v - mean)
        return sqrt(sq / values.size) / mean
    }

    /** Motif régulier des coupures (profil VPN partagé) : voir calc.regular_pattern. */
    fun regularPattern(outages: List<Outage>, nowMs: Long): Pattern {
        val recent = outages.filter { nowMs - PATTERN_WINDOW_MS < it.startMs && it.startMs <= nowMs }.sortedBy { it.startMs }
        if (recent.size < PATTERN_MIN_OUTAGES) return Pattern(false, null)
        val gaps = (1 until recent.size).map { (recent[it].startMs - recent[it - 1].startMs).toDouble() }
        var sum = 0.0
        for (g in gaps) sum += g
        val period = sum / gaps.size
        val regular = period in PATTERN_MIN_PERIOD_MS..PATTERN_MAX_PERIOD_MS && cv(gaps) < PATTERN_MAX_PERIOD_CV &&
            cv(recent.map { it.durationMs.toDouble() }) < PATTERN_MAX_DURATION_CV
        return Pattern(regular, if (regular) floor(period + 0.5).toLong() else null)
    }

    fun bucket(value: Double, edges: List<Double>): Int {
        for (i in edges.indices) if (value < edges[i]) return i
        return edges.size
    }

    private fun lowerEdge(index: Int, edges: List<Double>): Double = if (index == 0) 0.0 else edges[index - 1]

    /** Seuils proposés pour un type de réseau et une mesure : voir calc.propose. */
    fun propose(hist: List<Bucket>, edges: List<Double>, days: Double): Proposal? {
        val total = hist.sumOf { it.n }
        if (total < PROPOSE_MIN_WINDOWS || days < PROPOSE_MIN_DAYS) return null
        var seen = 0
        var p75 = hist.size - 1
        for (i in hist.indices) {
            seen += hist[i].n
            if (seen >= 0.75 * total) { p75 = i; break }
        }
        val floorValue = maxOf(lowerEdge(p75, edges), edges[0])
        fun first(ratio: Double): Double? {
            for (i in hist.indices) {
                if (hist[i].n >= PROPOSE_MIN_BUCKET && hist[i].degraded > ratio * hist[i].n) return maxOf(lowerEdge(i, edges), floorValue)
            }
            return null
        }
        val warn = first(PROPOSE_WARN_RATIO) ?: return null
        var alert = first(PROPOSE_ALERT_RATIO)
        if (alert == null || alert <= warn) alert = edges.firstOrNull { it > warn }
        return Proposal(warn, alert)
    }

    /** Ce qu'auraient donné des seuils sur l'historique (curseurs) : voir calc.simulate. */
    fun simulate(hist: List<Bucket>, edges: List<Double>, warn: Double, alert: Double): Simulation {
        val total = hist.sumOf { it.n }
        val n = IntArray(3)
        val degraded = IntArray(3)                        // 0 vert, 1 orange, 2 rouge
        hist.forEachIndexed { i, h ->
            val low = lowerEdge(i, edges)
            val c = if (low >= alert) 2 else if (low >= warn) 1 else 0
            n[c] += h.n
            degraded[c] += h.degraded
        }
        fun pct(part: Int, whole: Int): Double? = if (whole > 0) round1(100.0 * part / whole) else null
        return Simulation(pct(n[1], total), pct(n[2], total), pct(degraded[2], n[2]), pct(degraded[0], n[0]))
    }
}
