// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/**
 * Monitoring inter-stations (docs/cdc-monitoring.md § 17, docs/protocole.md § 19), repris de la page (monitoring.js) :
 * MÊMES textes et mêmes règles ; code tapé vérifié sur les vecteurs de la station (tests/protocol/monlink_vectors.json).
 * Kotlin pur : le module « monlink » n'agit jamais sur le poste et la station qui aide ne peut que lire et DEMANDER.
 */
object Monitoring {
    const val REFRESH_MS = 15_000L
    /** Textes lus à chaque usage (la langue peut changer pendant la vie de l'application). */
    val ROLES: Map<String, String> get() = mapOf("receiver" to Tr.t("monitoring.role_receiver"), "emitter" to Tr.t("monitoring.role_emitter"))
    val STATES: Map<String, String> get() = mapOf("confirm" to Tr.t("monitoring.state_confirm"), "active" to Tr.t("monitoring.state_active"),
        "paused" to Tr.t("monitoring.state_paused"))
    val HOURS = listOf(1, 2, 4, 24)
    /** Profils prédéfinis : (clé, libellé, rig, events_min), comme la page. */
    val PROFILES: List<Triple<String, String, Pair<Boolean, String>>> get() = listOf(
        Triple("essentiel", Tr.t("monitoring.profile_essential"), false to "erreur"),
        Triple("diagnostic", Tr.t("monitoring.profile_diagnostic"), true to "avertissement"),
    )
    private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    /** Code tapé -> « ABCDE-FGHJK », ou null : casse libre, espaces et tirets ignorés, O = 0, I et L = 1. */
    fun normalizeCode(text: String): String? {
        if (text.length > 40) return null
        val code = text.uppercase().replace(Regex("[\\s-]"), "").replace('O', '0').replace('I', '1').replace('L', '1')
        if (code.length != 10 || code.any { it !in ALPHABET }) return null
        return code.substring(0, 5) + "-" + code.substring(5)
    }

    /** Profil envoyé au module : « essentiel » ou « diagnostic » (défaut), fréquence et mode à part. */
    fun profile(choice: String, freqMode: Boolean): JsonObject {
        val p = PROFILES.firstOrNull { it.first == choice } ?: PROFILES[1]
        return JsonObject(mapOf("rig" to JsonPrimitive(p.third.first), "events_min" to JsonPrimitive(p.third.second),
                                "freq_mode" to JsonPrimitive(freqMode)))
    }

    private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
    private fun JsonObject.num(key: String): Long? = (this[key] as? JsonPrimitive)?.longOrNull
    private fun JsonObject.flag(key: String): Boolean = (this[key] as? JsonPrimitive)?.booleanOrNull == true
    private fun JsonObject.obj(key: String): JsonObject? = this[key] as? JsonObject
    private fun present(e: JsonElement?): Boolean = e != null && e !is JsonNull

    /** Une liaison telle que l'écran la montre (titre, détails, couleur, boutons). */
    data class Link(
        val peer: String, val pseudo: String, val role: String, val state: String, val title: String,
        val details: List<String>, val level: String, val actions: List<String>, val stationLines: List<String>,
        val fingerprint: String, val requestText: String?, val reports: Long,
    )

    /** Ce que montre l'écran de l'application (types simples : l'écran ne lit pas le JSON). */
    data class UiView(
        val status: String, val pseudo: String, val links: List<Link>, val code: String?, val joined: Link?,
        val events: List<String>?, val notice: String, val loaded: Boolean,
    )

    fun ui(state: MonitoringState?): UiView? {
        state ?: return null
        val joined = state.joined?.let { j ->
            Link(peer = j.str("peer").orEmpty(), pseudo = j.str("pseudo") ?: "?", role = "emitter", state = "confirm", title = "",
                 details = emptyList(), level = "warn", actions = emptyList(), stationLines = emptyList(),
                 fingerprint = j.str("fingerprint").orEmpty(), requestText = null, reports = 0)
        }
        return UiView(status(state.data), state.data?.str("pseudo").orEmpty(), links(state.data), state.code, joined,
                      state.events?.second?.map(::eventLine), state.notice, state.data != null)
    }

    /** Profil d'envoi sous forme simple (l'écran le passe tel quel à la station). */
    fun profileMap(choice: String, freqMode: Boolean): Map<String, Any> {
        val p = PROFILES.firstOrNull { it.first == choice } ?: PROFILES[1]
        return mapOf("rig" to p.third.first, "events_min" to p.third.second, "freq_mode" to freqMode)
    }

    fun details(link: JsonObject): List<String> {
        val out = mutableListOf<String>()
        if (link.str("state") != "confirm") {
            val age = (link["last_rx_age"] as? JsonPrimitive)?.longOrNull
            out += if (age == null) Tr.t("monitoring.no_news") else Tr.t("monitoring.last_news", "min" to maxOf(0, age) / 60)
        }
        link.obj("request")?.let { out += Tr.t(if (it.flag("snapshot")) "monitoring.report_pending" else "monitoring.assist_pending") }
        val left = link.num("assist_left_s") ?: 0
        if (left > 0) out += Tr.t("monitoring.assist_left", "min" to maxOf(1, left / 60))
        if (link.flag("paused")) out += Tr.t("monitoring.paused")
        if (link.flag("silent")) out += Tr.t("monitoring.silent")
        if (link.flag("report_due")) out += Tr.t("monitoring.report_due")
        val reports = link.num("reports") ?: 0
        if (reports > 0) out += Tr.t("monitoring.reports_received", "reports" to reports)
        return out
    }

    /** « warn » si l'opérateur doit agir ou si la station suivie se tait ; « dim » en pause ; « ok » sinon. */
    fun level(link: JsonObject): String = when {
        link.str("state") == "confirm" || present(link["request"]) || link.flag("silent") -> "warn"
        link.flag("paused") -> "dim"
        else -> "ok"
    }

    /** Boutons d'une liaison, selon son rôle et son état : jamais de commande vers l'autre station. */
    fun actions(link: JsonObject): List<String> {
        if (link.str("state") == "confirm") return listOf("fingerprint", "end")
        if (link.str("role") == "receiver") {
            return buildList {
                add("assist"); add("report")
                if ((link.num("reports") ?: 0) > 0) add("download")
                add("end")
            }
        }
        return buildList {
            if (present(link["request"])) add("answer")
            if (link.str("state") == "paused") add("resume") else { add("send_report"); add("profile"); add("pause") }
            add("end")
        }
    }

    /** Dernières nouvelles d'une station suivie (station qui aide), comme le choix 2 du menu 6.5. */
    fun stationLines(link: JsonObject): List<String> {
        val out = mutableListOf<String>()
        val hb = link.obj("last_hb")
        val st = link.obj("last_st")
        hb?.str("v")?.let { v ->
            out += Tr.t("monitoring.station_line", "version" to v, "gateway" to (hb.str("gateway") ?: "?"),
                "safe" to (hb.str("safe") ?: Tr.t("monitoring.safe_no")))
        }
        st?.obj("system")?.takeIf { it.isNotEmpty() }?.let { s ->
            fun v(key: String) = (s[key] as? JsonPrimitive)?.let { p -> p.longOrNull?.toString() ?: p.doubleOrNull?.toString() } ?: "--"
            val temp = (s["temp"] as? JsonPrimitive)?.let { p -> p.longOrNull?.toString() ?: p.doubleOrNull?.toString() }
            out += Tr.t("monitoring.machine_line", "cpu" to v("cpu"), "mem" to v("mem"), "disk" to v("disk"),
                "temp" to (if (temp == null) "--" else "$temp °C"))
        }
        st?.obj("rig")?.takeIf { it.isNotEmpty() }?.let { r ->
            val freq = r.num("freq")?.let { ", " + String.format(java.util.Locale.ROOT, "%.3f", it / 1e6) + " MHz " + (r.str("mode") ?: "") }.orEmpty()
            out += Tr.t("monitoring.rig_line", "cat" to (if (r.flag("cat")) "OK" else (r.str("cat_error")?.ifEmpty { null } ?: "?")),
                "tx" to (r.str("tx") ?: "?"), "clients" to (r.num("clients") ?: 0), "freq" to freq).trimEnd()
        }
        if (out.isEmpty()) out += Tr.t("monitoring.no_news_received")
        return out
    }

    /** Un événement reçu : « 2026-11-21 10:00 ORT-2104 erreur CAT lent ». */
    fun eventLine(e: JsonObject): String {
        val c = e.obj("content") ?: JsonObject(emptyMap())
        return listOf((c.str("ts") ?: "").take(16).replace('T', ' '), c.str("code") ?: "?", c.str("gravite") ?: "?",
                      c.str("titre") ?: c.str("message") ?: "").filter { it.isNotEmpty() }.joinToString(" ")
    }

    fun link(raw: JsonObject): Link {
        val role = raw.str("role") ?: "?"
        val state = raw.str("state") ?: "?"
        val pseudo = raw.str("pseudo")?.ifEmpty { null } ?: "?"
        return Link(
            peer = raw.str("peer").orEmpty(), pseudo = pseudo, role = role, state = state,
            title = Tr.t("monitoring.link_title", "pseudo" to pseudo, "role" to (ROLES[role] ?: "?"), "state" to (STATES[state] ?: "?")),
            details = details(raw), level = level(raw), actions = actions(raw),
            stationLines = if (role == "receiver" && state != "confirm") stationLines(raw) else emptyList(),
            fingerprint = raw.str("fingerprint").orEmpty(), requestText = raw.obj("request")?.let { requestText(pseudo, it) },
            reports = raw.num("reports") ?: 0,
        )
    }

    fun status(view: JsonObject?): String {
        if (view == null) return Tr.t("monitoring.reading")
        return listOfNotNull(
            view.str("pseudo")?.ifEmpty { null }?.let { Tr.t("monitoring.pseudo", "pseudo" to it) } ?: Tr.t("monitoring.no_pseudo"),
            Tr.t(if (view.flag("registered")) "monitoring.registered" else "monitoring.not_registered"),
            view.str("problem")?.ifEmpty { null }?.let { Tr.t("monitoring.problem", "problem" to it) },
        ).joinToString(" · ")
    }

    fun links(view: JsonObject?): List<Link> = (view?.get("links") as? JsonArray).orEmpty().mapNotNull { (it as? JsonObject)?.let(::link) }

    /** Texte d'une demande reçue (station aidée), comme la page. */
    fun requestText(pseudo: String, request: JsonObject): String =
        if (request.flag("snapshot")) Tr.t("monitoring.request_report", "pseudo" to pseudo)
        else Tr.t("monitoring.request_assist", "pseudo" to pseudo, "hours" to Math.round((request.num("assist") ?: 0) / 360.0) / 10.0)
}
