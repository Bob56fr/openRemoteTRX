// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.FreedvStatus
import kotlin.math.abs
import kotlin.math.floor

/** Voyant FDV : vert = voix (synchro tenue 2 s), orange = recherche ou relance, rouge = abandon, gris = son du poste. */
enum class FreeDvLevel { OK, WARN, BAD, OFF }

/** Ce que l'écran affiche de state.freedv (mêmes textes que freedvView de la page, client.js). */
data class FreeDvView(
    val on: Boolean,
    val level: FreeDvLevel,
    val text: String,
    val confirmed: Boolean,
    val snrText: String,
    val engine: String,
    val restarts: Int,
    val cause: String,
    val fault: String,
    val calls: List<Call>,
    val lastCall: Call?,
    val sequences: List<Sequence>,
) {
    data class Call(val callsign: String, val snrText: String, val whenText: String)
    data class Sequence(val note: Int, val stars: String, val duration: String, val detail: String, val callsigns: String,
                        val whenText: String)

    /** Ligne de détails de la rubrique (comme la page) : dernier indicatif, relances, dernière panne. */
    val details: String get() = buildList {
        lastCall?.let { c ->
            add(Tr.t("freedv.last_call", "callsign" to c.callsign,
                "snr" to (if (c.snrText.isNotEmpty()) " (${c.snrText})" else ""),
                "when" to (if (c.whenText.isNotEmpty()) ", ${c.whenText}" else "")))
        }
        if (restarts > 0) add(Tr.t("freedv.restarts", "restarts" to restarts))
        if (cause.isNotEmpty()) add(Tr.t("freedv.last_fault", "cause" to cause))
    }.joinToString(" · ")
}

/**
 * FreeDV RADE V1 en réception (station 0.122.0+, docs/protocole.md § 17) : la station décode, l'application affiche.
 * Copie de freedvView, freedvStars, freedvDb et FREEDV_ENGINE de la page : les textes sont comparés à client.js.
 */
object FreeDvs {
    /** États du moteur (codes de state.freedv.engine, textes `freedv.engine_<code>`). */
    private val ENGINE_KEYS = listOf("demarrage", "ecoute", "relance", "panne", "arret")
    val ENGINE: Map<String, String> get() = ENGINE_KEYS.associateWith { Tr.t("freedv.engine_$it") }

    fun stars(note: Double?): String {
        val n = Math.round(note ?: 0.0).toInt().coerceIn(0, 5)
        return "★".repeat(n) + "☆".repeat(5 - n)
    }

    /** « +7,5 dB », « −3,0 dB », « 0,0 dB » (signe moins typographique). */
    fun db(v: Double): String =
        (if (v > 0) "+" else if (v < 0) "−" else "") + Format.decimal(abs(v), 1) + " dB"

    /** Nombre écrit comme JavaScript le ferait (« 9 », « 9.5 »). */
    private fun jsNumber(v: Double): String =
        if (v == floor(v) && abs(v) < 1e15) v.toLong().toString() else v.toString()

    private fun durationText(seconds: Double?): String =
        PresenceUi.duration(Math.round(seconds ?: 0.0).toInt().coerceAtLeast(0))

    /** `nowS` : heure Unix (secondes) ; null = pas de « il y a … ». */
    fun view(f: FreedvStatus?, nowS: Double?): FreeDvView? {
        if (f == null || f.on == null) return null
        val on = f.on == true
        val confirmed = on && f.confirmed
        val snr = if (on) f.snrDb?.takeIf { it.isFinite() } else null
        val engine = if (f.engine in ENGINE_KEYS) f.engine else "arret"
        val fault = f.fault.orEmpty()
        val cause = f.cause.orEmpty()
        fun ago(t: Double?): String =
            if (t != null && t.isFinite() && nowS != null) Tr.t("freedv.ago", "duration" to durationText(nowS - t)) else ""
        val level: FreeDvLevel
        val text: String
        when {
            !on -> {
                level = if (fault.isNotEmpty()) FreeDvLevel.BAD else FreeDvLevel.OFF
                text = if (fault.isNotEmpty()) Tr.t("freedv.abandoned", "fault" to fault.take(200))
                       else Tr.t("freedv.rig_audio")
            }
            engine == "demarrage" || engine == "relance" || engine == "panne" -> {
                level = FreeDvLevel.WARN; text = Tr.t("freedv.engine_text", "state" to ENGINE.getValue(engine))
            }
            confirmed -> { level = FreeDvLevel.OK; text = Tr.t("freedv.voice") + (snr?.let { " · SNR " + db(it) } ?: "") }
            else -> { level = FreeDvLevel.WARN; text = Tr.t("freedv.searching") }
        }
        val calls = f.calls.mapNotNull { c -> c.callsign?.let { it to c } }.take(10).map { (callsign, it) ->
            FreeDvView.Call(callsign.take(12), it.snrDb?.takeIf { d -> d.isFinite() }?.let { d -> jsNumber(d) + " dB" } ?: "", ago(it.t))
        }
        val sequences = f.sequences.mapNotNull { s -> s.note?.takeIf { it.isFinite() }?.let { it to s } }.take(10).map { (note, s) ->
            val end = s.start?.let { it + (s.durationS ?: 0.0) }
            FreeDvView.Sequence(Math.round(note).toInt().coerceIn(1, 5), stars(note), durationText(s.durationS),
                s.detail.take(200), s.callsigns.joinToString(", ") { it.take(12) }, ago(end))
        }
        return FreeDvView(
            on = on, level = level, text = text, confirmed = confirmed, snrText = snr?.let { db(it) } ?: "",
            engine = engine, restarts = f.restarts.coerceAtLeast(0),
            cause = if (on && cause.isNotEmpty()) cause.take(200) else "",
            fault = fault.take(200),
            calls = calls, lastCall = calls.firstOrNull(), sequences = sequences,
        )
    }

    /**
     * Android Auto : état seul, en TÊTE du sous-titre (aucun bouton) : « FDV » = voix décodée, « FDV … » = recherche ou
     * relance, « FDV PANNE » = abandon (son du poste remis) ; rien hors du mode FreeDV.
     */
    fun carPart(v: FreeDvView?): String? = when {
        v == null -> null
        !v.on -> if (v.level == FreeDvLevel.BAD) Tr.t("freedv.car_fault") else null
        v.level == FreeDvLevel.OK -> "FDV"
        else -> "FDV …"                                                      // i18n-ok
    }
}
