// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.State
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * « Signaler un problème » (lot A3) : MÊME texte que la page (`formatProblemReport` de client.js), montré en entier à
 * l'utilisateur AVANT l'envoi, rangé par la station (`bug_report`) et joint au rapport de dépannage (TRX Console, menu 6.3).
 * Aucun secret : ni mot de passe, ni empreinte, ni jeton. Appareil : modèle et version d'Android (choix de l'utilisateur,
 * 2026-11-09), à la place de l'« user agent » de la page.
 */
object ProblemReport {
    /** Même limite que la station (protocol.MAX_BUG_REPORT_CHARS) et la page (MAX_REPORT_CHARS). */
    const val MAX_CHARS = 30000
    const val DESCRIPTION_MAX = 2000
    const val LOG_LINES = 8

    data class Input(
        val nowMs: Long, val description: String, val hello: Hello?, val state: State?, val connected: Boolean,
        val device: String, val screen: String, val rttMs: Int?, val log: List<LogLine>, val zone: ZoneId = ZoneId.systemDefault(),
    )

    private val DATE = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm:ss")   // i18n-ok
    private val TIME = DateTimeFormatter.ofPattern("HH:mm:ss")

    /** 7074000 -> « 7 074 000 Hz » (formatFrequency de la page). */
    fun frequency(hz: Long?): String =
        if (hz == null) "—" else hz.toString().reversed().chunked(3).joinToString(" ").reversed() + " Hz"

    /** Ligne « Poste : » de la page : fréquence, mode, liaison CAT, PTT, poste utilisé sur place. */
    fun rigLine(state: State?): String? {
        state ?: return null
        val r = state.rig
        val p = state.ptt
        return Tr.t("problemreport.rig_line", "frequency" to frequency(r.frequencyHz), "mode" to (r.mode ?: "?"),
            "cat" to Tr.t(if (r.connected) "problemreport.cat_active" else "problemreport.cat_lost"), "ptt" to p.state) +
            (if ((p.localRemainingS ?: 0.0) > 0) Tr.t("problemreport.local_use") else "")
    }

    private fun spectrumLine(hello: Hello?, state: State?): String? {
        if (hello?.spectrum == null) return null
        fun f(k: String) = (state?.spectrum?.get(k) as? JsonPrimitive)?.contentOrNull
        return (f("state") ?: "?") + (f("code")?.let { " ($it)" } ?: "")
    }

    fun format(d: Input): String {
        fun at(ms: Long, f: DateTimeFormatter) = f.format(Instant.ofEpochMilli(ms).atZone(d.zone))
        val h = d.hello
        val lines = mutableListOf(
            Tr.t("problemreport.header"), Tr.t("problemreport.date", "date" to at(d.nowMs, DATE)), "",
            Tr.t("problemreport.what_happened"), d.description.trim().ifEmpty { Tr.t("problemreport.not_described") }.take(DESCRIPTION_MAX), "",
            Tr.t("problemreport.station", "version" to (if (!h?.version.isNullOrEmpty()) "v" + h!!.version else Tr.t("problemreport.version_unknown"))) +
                (h?.let { Tr.t("problemreport.protocol", "protocol" to it.protocol) } ?: "") +
                (h?.clientId?.let { Tr.t("problemreport.account", "account" to it) } ?: "") +
                Tr.t(if (d.connected) "problemreport.connected" else "problemreport.not_connected"),
            Tr.t("problemreport.device", "device" to d.device.ifEmpty { "?" }), Tr.t("problemreport.screen", "screen" to d.screen.ifEmpty { "?" }),
        )
        rigLine(d.state)?.let { lines += Tr.t("problemreport.rig", "rig" to it) }
        spectrumLine(h, d.state)?.let { lines += Tr.t("problemreport.spectrum", "spectrum" to it) }
        d.rttMs?.let { lines += Tr.t("problemreport.rtt", "rtt" to it) }
        lines += listOf("", Tr.t("problemreport.log_header"))
        for (l in d.log.takeLast(LOG_LINES)) lines += "  " + at(l.atMs, TIME) + "  " + l.text.take(200)
        return lines.joinToString("\n").take(MAX_CHARS)
    }
}
