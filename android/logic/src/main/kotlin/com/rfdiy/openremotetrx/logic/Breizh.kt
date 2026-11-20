// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.BreizhEvent
import com.rfdiy.openremotetrx.protocol.BreizhStatus
import kotlin.math.abs

/** Voyant BZH : vert (prêt, émission par Breizh), orange (repli), gris (recherche, refus, « Direct » choisi). */
enum class BreizhLevel { OK, WARN, OFF }

/** Ce que l'écran affiche de state.breizh (mêmes textes que breizhView de la page, client.js). */
data class BreizhView(
    val state: String,
    val route: String,
    val bypass: Boolean,
    val level: BreizhLevel,
    val text: String,
    val details: String,
    val returnGainDb: Double,
    val returnGainText: String,
    val canReactivate: Boolean,
    /** Voix par Breizh : égaliseur, chorus et réverbération coupés (limiteur gardé), scrambler d'émission exclu. */
    val effectsOff: Boolean,
)

/** Ligne du journal de la liaison avec Breizh (breizh_event, breizh_log). */
data class BreizhEntry(val t: String, val event: String, val detail: String) {
    val warn: Boolean get() = event in WARN_EVENTS

    /** « 2026-11-04 10:00:00 UTC : texte », comme la page. */
    val line: String get() = (if (t.isNotEmpty()) t.replace("T", " ").replace("Z", " UTC") + " : " else "") + detail

    companion object {
        val WARN_EVENTS = setOf("fallback", "lost", "refused")
        fun of(e: BreizhEvent) = BreizhEntry(e.t, e.event, e.detail.take(300))
    }
}

/**
 * Breizh Audio Box dans la chaîne d'émission (docs/breizh-cahier-des-charges.md, station 0.100.0+). Copie de breizhView
 * et BREIZH_STATES de la page : les textes sont comparés à client.js par les tests.
 */
object Breizhs {
    const val EVENTS_MAX = 50
    const val GAIN_MIN = -20.0
    const val GAIN_MAX = 6.0

    /** États de la liaison (codes de state.breizh.state, textes `breizh.state_<code>`). */
    private val STATE_KEYS = listOf("connecting", "ready", "active", "fallback", "refused")
    val STATES: Map<String, String> get() = STATE_KEYS.associateWith { Tr.t("breizh.state_$it") }

    /** « −3,5 dB », « +6 dB », « 0 dB » (signe moins typographique, comme la page). */
    fun gainText(gain: Double): String {
        val a = abs(gain)
        val number = if (a == Math.floor(a)) a.toLong().toString() else Format.localize(a.toString())
        return (if (gain > 0) "+" else if (gain < 0) "−" else "") + number + " dB"
    }

    /** Volume retour arrondi au pas de 0,5 dB et borné (curseur). */
    fun snapGain(value: Double): Double = (Math.round(value * 2) / 2.0).coerceIn(GAIN_MIN, GAIN_MAX)

    fun view(b: BreizhStatus?): BreizhView? {
        if (b == null) return null
        val state = if (b.state in STATE_KEYS) b.state else "connecting"
        val level = when {
            b.bypass -> BreizhLevel.OFF
            state == "ready" || state == "active" -> BreizhLevel.OK
            state == "fallback" -> BreizhLevel.WARN
            else -> BreizhLevel.OFF
        }
        val details = buildList {
            if (b.peer.isNotEmpty()) add(b.peer.take(64))
            b.rttMs?.let { add(Tr.t("breizh.rtt", "rtt" to it)) }
            if (b.late > 0) add(Tr.t("breizh.late", "late" to b.late))
            b.reactivateInS?.let { add(Tr.t("breizh.reactivate_in", "seconds" to it)) }
        }.joinToString(" · ")
        val text = STATES.getValue(state)
        return BreizhView(
            state = state, route = if (b.route == "breizh") "breizh" else "direct", bypass = b.bypass, level = level,
            text = if (b.bypass) Tr.t("breizh.bypass", "state" to text) else text,
            details = details, returnGainDb = b.returnGainDb, returnGainText = gainText(b.returnGainDb),
            canReactivate = !b.bypass && (state == "fallback" || state == "refused"),
            effectsOff = b.route == "breizh",
        )
    }
}
