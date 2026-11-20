// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.DiffusionStatus
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Diffusion en direct dans l'application (docs/diffusion-cahier-des-charges.md, lot D4 ; protocole : docs/protocole.md
 * § 20). Copie de diffusion.js de la page : les textes sont comparés à ce fichier par les tests. L'état vient de
 * state.diffusion (opérateurs) ; le module « diffusion » n'agit jamais sur le poste.
 */
object Diffusions {
    /** Cahier § 1.1 : à confirmer une fois, au premier lancement (la station s'en souvient). */
    val WARNING: String get() = Tr.t("diffusion.warning")

    /** Durées proposées ; null = sans limite (24 h/24, choix explicite). */
    val HOURS: List<Int?> = listOf(1, 2, 3, 4, 6, 8, 12, 24, null)
    const val DEFAULT_HOURS = 1

    /** Codes des informations proposées (protocol.CHOICE_FIELDS de la station), dans l'ordre de l'écran. */
    private val META_KEYS = listOf("pseudo", "indicatif", "frequence_hz", "mode", "bande", "tx", "s_metre", "filtre",
                                   "voyants", "message")

    /** Informations proposées à l'opérateur (protocol.CHOICE_FIELDS de la station) ; TOUT coché par défaut (étape 248). */
    val META: List<Pair<String, String>> get() = META_KEYS.map { it to Tr.t("diffusion.meta_$it") }
    val DEFAULT_META: List<String> = META_KEYS
    val LIMITS: Map<String, Int> = mapOf("pseudo" to 32, "indicatif" to 16, "message" to 140)

    private val STOP_KEYS = listOf("operator", "duration", "overload", "gateway_restart", "auth", "disabled", "station_stop")
    private val PHASE_KEYS = listOf("connexion", "en_direct", "nouvel_essai")
    private val SILENCE_KEYS = listOf("hors_bandes", "emission", "pas_de_son", "poste_eteint")

    val STOPS: Map<String, String> get() = STOP_KEYS.associateWith { Tr.t("diffusion.stop_$it") }
    val PHASES: Map<String, String> get() = PHASE_KEYS.associateWith { Tr.t("diffusion.phase_$it") }
    /** Raison d'un silence voulu (la station la dit aussi aux auditeurs, docs/protocole-diffusion.md § 3.1). */
    val SILENCES: Map<String, String> get() = SILENCE_KEYS.associateWith { Tr.t("diffusion.silence_$it") }

    fun remaining(s: Int?): String {
        if (s == null) return Tr.t("diffusion.no_limit")
        val m = Math.round(maxOf(0, s) / 60.0).toInt()
        if (m < 60) return "$m min"
        return "${m / 60} h " + (m % 60).toString().padStart(2, '0')
    }

    fun hoursLabel(h: Int?): String = if (h == null) Tr.t("diffusion.hours_no_limit") else "$h h"

    /** Indicateur toujours visible pendant une diffusion (cahier § 8) ; `live` = en direct (sinon connexion ou reprise). */
    data class Indicator(val text: String, val live: Boolean, val title: String)

    fun indicator(d: DiffusionStatus?): Indicator? {
        if (d == null || !d.active) return null
        val n = d.listeners
        val parts = mutableListOf(Tr.t("diffusion.indicator"))
        if (n != null) parts += "🎧 $n"
        parts += remaining(d.remainingS)
        val silence = SILENCES[d.silence]
        if (silence != null) parts += "🔇"
        val title = Tr.t("diffusion.title",
            "access" to access(d.access),
            "phase" to (PHASES[d.phase] ?: d.phase.orEmpty()),
            "listeners" to (if (n != null) Tr.plural("diffusion.title_listeners", n) else ""),
            "remaining" to remaining(d.remainingS),
            "silence" to (if (silence != null) Tr.t("diffusion.title_silence", "silence" to silence) else ""))
        return Indicator(parts.joinToString(" · "), d.phase == "en_direct", title)
    }

    /** « publique » ou « privée ». */
    private fun access(access: String?): String =
        Tr.t(if (access == "public") "diffusion.access_public" else "diffusion.access_private")

    /** Texte d'état de la fenêtre (comme la rubrique de la page). */
    fun status(d: DiffusionStatus?): String {
        if (d == null) return Tr.t("diffusion.status_unavailable")
        if (!d.enabled) return Tr.t("diffusion.status_disabled")
        if (!d.problem.isNullOrEmpty()) return Tr.t("diffusion.status_problem", "problem" to d.problem)
        if (d.active) {
            val who = if (!d.operator.isNullOrEmpty()) Tr.t("diffusion.status_by", "operator" to d.operator) else ""
            val silence = SILENCES[d.silence]
            return Tr.t("diffusion.status_active",
                "who" to who,
                "access" to access(d.access),
                "phase" to (PHASES[d.phase] ?: d.phase.orEmpty()),
                "remaining" to remaining(d.remainingS),
                "voice" to Tr.t(if (d.voice) "diffusion.status_voice_on" else "diffusion.status_voice_off"),
                "bands" to Tr.t(if (d.outsideBands) "diffusion.status_bands_on" else "diffusion.status_bands_off"),
                "silence" to (if (silence != null) Tr.t("diffusion.status_silence", "silence" to silence) else ""))
        }
        val last = d.lastStop?.cause?.let { STOPS[it] }?.let { Tr.t("diffusion.status_last", "stop" to it) }.orEmpty()
        return Tr.t("diffusion.status_idle", "last" to last)
    }

    /** Formulaire de lancement. */
    data class Form(
        val public: Boolean = false,
        val hours: Int? = DEFAULT_HOURS,
        val voice: Boolean = false,
        val meta: List<String> = DEFAULT_META,
        val pseudo: String = "",
        val indicatif: String = "",
        val message: String = "",
    )

    /** Contrôle du formulaire avant envoi (la station vérifie de nouveau tout) : (arguments, null) ou (null, erreur). */
    fun startArgs(f: Form): Pair<JsonObject?, String?> {
        if (f.hours != null && f.hours !in 1..24) return null to Tr.t("diffusion.form_hours")
        val keys = META_KEYS
        val args = linkedMapOf(
            "access" to JsonPrimitive(if (f.public) "public" else "prive"),
            "hours" to (f.hours?.let { JsonPrimitive(it) } ?: JsonNull),
            "voice" to JsonPrimitive(f.voice),
            "meta" to JsonArray(f.meta.filter { it in keys }.map { JsonPrimitive(it) }),
        )
        for ((k, limit) in LIMITS) {
            val v = when (k) { "pseudo" -> f.pseudo; "indicatif" -> f.indicatif; else -> f.message }.trim()
            val label = Tr.t("diffusion.meta_$k")
            if (v.length > limit) return null to Tr.t("diffusion.form_too_long", "label" to label, "limit" to limit)
            if (v.any { it.code < 0x20 || it.code in 0x7F..0x9F }) return null to Tr.t("diffusion.form_invalid", "label" to label)
            if (v.isNotEmpty()) args[k] = JsonPrimitive(v)
        }
        return JsonObject(args) to null
    }

    /** Erreur du formulaire à montrer sous le bouton, null s'il est bon. */
    fun formError(f: Form): String? = startArgs(f).second

    fun passwordOk(pw: String): Boolean = Regex("^[A-Za-z0-9]{8,64}$").matches(pw)
}

/**
 * Diffusion telle que l'écran la montre : `status` = state.diffusion ; `notice` = dernier message (lancée, arrêtée,
 * refus…) ; `user` / `password` = identifiants des auditeurs révélés à la demande (jamais dans state) ; `confirm` =
 * la station demande l'avertissement de responsabilité avant ce lancement.
 */
data class DiffusionState(
    val status: DiffusionStatus?,
    val notice: String = "",
    val noticeBad: Boolean = false,
    val user: String? = null,
    val password: String? = null,
    val confirm: Boolean = false,
)
