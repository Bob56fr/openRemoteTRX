// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.FreedvActivity
import java.util.Locale
import kotlin.math.abs
import kotlin.math.floor

/** Ce que la fenêtre FreeDV montre de l'activité (mêmes textes que freedvActivityView de la page, client.js). */
data class FreeDvActivityView(val status: String, val text: String, val rows: List<Row>) {
    /** `here` : la fréquence du poste (à 1,5 kHz près). `tx` : texte et « émet en ce moment » (affiché en vert). */
    data class Row(val hz: Long, val freqText: String, val note: Double, val noteText: String, val here: Boolean,
                   val tx: List<Tx>, val rx: List<String>)
    data class Tx(val text: String, val on: Boolean)
}

/**
 * Activité FreeDV (module « freedv_activity », station 0.125.0+, docs/protocole.md § 17) : stations FreeDV actives
 * par fréquence, d'après FreeDV Reporter lu par la station en observateur. Copie de freedvActivityView,
 * freedvQsyMode et freedvFreqText de la page : les textes sont comparés à client.js.
 */
object FreeDvActivities {
    const val STALE_S = 60.0
    val STALE_TEXT: String get() = Tr.t("freedvactivity.stale")
    val CONNECTING_TEXT: String get() = Tr.t("freedvactivity.connecting")
    val DEFAULT_ERROR: String get() = Tr.t("freedvactivity.unreachable")
    val NO_LOCATOR: String get() = Tr.t("freedvactivity.no_locator")
    val HERE: String get() = Tr.t("freedvactivity.here")
    val EMPTY: String get() = Tr.t("freedvactivity.empty")

    /** 14 236 000 Hz -> « 14236,0 kHz » (arrondi à 100 Hz). */
    fun freqText(hz: Long): String =
        String.format(Locale.ROOT, "%.1f", Math.round(hz / 100.0) / 10.0).replace(".", ",") + " kHz"

    /** FreeDV se reçoit en BLU supérieure : mode gardé en USB ou PKTUSB, sinon USB. */
    fun qsyMode(rigMode: String?): String? = if (rigMode == "USB" || rigMode == "PKTUSB") null else "USB"

    /** Nombre écrit comme JavaScript le ferait (« 6 », « -2 », « 4.4 »). */
    private fun js(v: Double): String = if (v == floor(v) && abs(v) < 1e15) v.toLong().toString() else v.toString()

    fun view(a: FreedvActivity?, rigHz: Long?, nowS: Double?): FreeDvActivityView? {
        if (a == null) return null
        val t = a.t
        val stale = t != null && nowS != null && nowS - t > STALE_S
        val status = if (stale) "erreur" else if (a.status in setOf("ok", "connexion", "erreur")) a.status else "erreur"
        val total = a.total ?: 0
        val text = when {
            stale -> STALE_TEXT
            status == "connexion" -> CONNECTING_TEXT
            status == "erreur" -> a.message.ifEmpty { DEFAULT_ERROR }.take(200)
            else -> Tr.plural("freedvactivity.connected", total) + (if (a.locator) "" else NO_LOCATOR)
        }
        fun km(k: Int?) = if (k != null) " $k km" else ""
        fun other(m: String?) = if (!m.isNullOrEmpty() && m != "RADEV1") m.take(12) else ""
        fun call(c: String?) = (c?.ifEmpty { null } ?: "?").take(12)
        val rows = if (stale) emptyList() else a.freqs.take(20).map { g ->
            val tx = g.tx.take(8).map { t ->
                val m = other(t.m)
                val who = call(t.c) + km(t.km)
                FreeDvActivityView.Tx(
                    if (t.on) Tr.t("freedvactivity.tx_on", "who" to who, "mode" to (if (m.isNotEmpty()) " $m" else ""))
                    else Tr.t("freedvactivity.tx_off", "who" to who, "min" to (t.min?.toString() ?: "?"),
                              "mode" to (if (m.isNotEmpty()) ", $m" else "")), t.on)
            }
            val rx = g.rx.take(6).map { r ->
                call(r.c) + km(r.km) + (r.snr?.let { " " + js(it) + " dB" } ?: "") +
                    (if (other(r.m).isNotEmpty()) " (" + other(r.m) + ")" else "")
            }
            val note = g.note ?: 0.0
            FreeDvActivityView.Row(g.f, freqText(g.f), note, js(note).replace(".", ","),
                rigHz != null && abs(g.f - rigHz) <= 1500, tx, rx)
        }
        return FreeDvActivityView(status, text, rows)
    }
}
