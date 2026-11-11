// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.FreedvStatus
import java.util.Locale
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
            add("Dernier indicatif : " + c.callsign + (if (c.snrText.isNotEmpty()) " (${c.snrText})" else "") +
                (if (c.whenText.isNotEmpty()) ", ${c.whenText}" else ""))
        }
        if (restarts > 0) add("$restarts relance(s) des décodeurs")
        if (cause.isNotEmpty()) add("dernière panne : $cause")
    }.joinToString(" · ")
}

/**
 * FreeDV RADE V1 en réception (station 0.122.0+, docs/protocole.md § 17) : la station décode, l'application affiche.
 * Copie de freedvView, freedvStars, freedvDb et FREEDV_ENGINE de la page : les textes sont comparés à client.js.
 */
object FreeDvs {
    val ENGINE = linkedMapOf(
        "demarrage" to "démarrage des décodeurs…",
        "ecoute" to "écoute",
        "relance" to "relance des décodeurs…",
        "panne" to "décodeurs en panne",
        "arret" to "arrêté",
    )

    fun stars(note: Double?): String {
        val n = Math.round(note ?: 0.0).toInt().coerceIn(0, 5)
        return "★".repeat(n) + "☆".repeat(5 - n)
    }

    /** « +7,5 dB », « −3,0 dB », « 0,0 dB » (signe moins typographique). */
    fun db(v: Double): String =
        (if (v > 0) "+" else if (v < 0) "−" else "") + String.format(Locale.ROOT, "%.1f", abs(v)).replace(".", ",") + " dB"

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
        val engine = if (f.engine in ENGINE) f.engine else "arret"
        val fault = f.fault.orEmpty()
        val cause = f.cause.orEmpty()
        fun ago(t: Double?): String =
            if (t != null && t.isFinite() && nowS != null) "il y a " + durationText(nowS - t) else ""
        val level: FreeDvLevel
        val text: String
        when {
            !on -> {
                level = if (fault.isNotEmpty()) FreeDvLevel.BAD else FreeDvLevel.OFF
                text = if (fault.isNotEmpty()) "FreeDV abandonné : " + fault.take(200) + " (son du poste remis)"
                       else "Son du poste : mode FreeDV non choisi"
            }
            engine == "demarrage" || engine == "relance" || engine == "panne" -> {
                level = FreeDvLevel.WARN; text = "FreeDV : " + ENGINE.getValue(engine)
            }
            confirmed -> { level = FreeDvLevel.OK; text = "Voix FreeDV" + (snr?.let { " · SNR " + db(it) } ?: "") }
            else -> { level = FreeDvLevel.WARN; text = "FreeDV : recherche d'un signal…" }
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
        !v.on -> if (v.level == FreeDvLevel.BAD) "FDV PANNE" else null
        v.level == FreeDvLevel.OK -> "FDV"
        else -> "FDV …"
    }
}
