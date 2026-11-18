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
    const val WARNING = "Vous allez rediffuser le son de votre TRX sur Internet, vers des auditeurs sans compte sur la " +
        "station. Des milliers de SDR en ligne le font déjà, mais ce que vous diffusez est de VOTRE responsabilité. Hors " +
        "des bandes autorisées de la station, les auditeurs n'entendent rien, sauf si le réglage « Diffuser aussi hors " +
        "des bandes autorisées » est en service. Pendant vos émissions, votre voix n'est diffusée que si vous cochez " +
        "« Diffuser aussi ma voix ». Continuer ?"

    /** Durées proposées ; null = sans limite (24 h/24, choix explicite). */
    val HOURS: List<Int?> = listOf(1, 2, 3, 4, 6, 8, 12, 24, null)
    const val DEFAULT_HOURS = 1

    /** Informations proposées à l'opérateur (protocol.CHOICE_FIELDS de la station) ; TOUT coché par défaut (étape 248). */
    val META: List<Pair<String, String>> = listOf(
        "pseudo" to "Pseudo", "indicatif" to "Indicatif", "frequence_hz" to "Fréquence", "mode" to "Mode",
        "bande" to "Bande", "tx" to "Réception / émission", "s_metre" to "S-mètre", "filtre" to "Filtre",
        "voyants" to "Voyants (P.AMP, ATT, NB, NR…)", "message" to "Message",
    )
    val DEFAULT_META: List<String> = META.map { it.first }
    val LIMITS: Map<String, Int> = mapOf("pseudo" to 32, "indicatif" to 16, "message" to 140)

    val STOPS: Map<String, String> = linkedMapOf(
        "operator" to "arrêtée par un opérateur", "duration" to "fin de la durée choisie", "overload" to "station surchargée",
        "gateway_restart" to "passerelle relancée", "auth" to "mot de passe source refusé par le serveur",
        "disabled" to "fonction mise hors service", "station_stop" to "arrêt de la station",
    )
    val PHASES: Map<String, String> = linkedMapOf(
        "connexion" to "connexion au serveur…", "en_direct" to "en direct", "nouvel_essai" to "liaison perdue, nouvel essai…",
    )
    /** Raison d'un silence voulu (la station la dit aussi aux auditeurs, docs/protocole-diffusion.md § 3.1). */
    val SILENCES: Map<String, String> = linkedMapOf(
        "hors_bandes" to "réception hors des bandes autorisées",
        "emission" to "émission en cours, voix non diffusée",
        "pas_de_son" to "le son du poste n'arrive plus",
    )

    fun remaining(s: Int?): String {
        if (s == null) return "sans limite"
        val m = Math.round(maxOf(0, s) / 60.0).toInt()
        if (m < 60) return "$m min"
        return "${m / 60} h " + (m % 60).toString().padStart(2, '0')
    }

    fun hoursLabel(h: Int?): String = if (h == null) "Sans limite (24 h/24)" else "$h h"

    /** Indicateur toujours visible pendant une diffusion (cahier § 8) ; `live` = en direct (sinon connexion ou reprise). */
    data class Indicator(val text: String, val live: Boolean, val title: String)

    fun indicator(d: DiffusionStatus?): Indicator? {
        if (d == null || !d.active) return null
        val n = d.listeners
        val parts = mutableListOf("DIFFUSION")
        if (n != null) parts += "🎧 $n"
        parts += remaining(d.remainingS)
        val silence = SILENCES[d.silence]
        if (silence != null) parts += "🔇"
        val title = "Diffusion en direct (" + (if (d.access == "public") "publique" else "privée") + ", " +
            (PHASES[d.phase] ?: d.phase.orEmpty()) + (if (n != null) ", $n auditeur" + (if (n > 1) "s" else "") else "") +
            ", reste " + remaining(d.remainingS) + ")" + (if (silence != null) ". Silence pour les auditeurs : $silence" else "")
        return Indicator(parts.joinToString(" · "), d.phase == "en_direct", title)
    }

    /** Texte d'état de la fenêtre (comme la rubrique de la page). */
    fun status(d: DiffusionStatus?): String {
        if (d == null) return "Diffusion indisponible sur cette station."
        if (!d.enabled) return "Diffusion hors service ([diffusion] de station.toml, menu 8.1)."
        if (!d.problem.isNullOrEmpty()) return "Diffusion impossible : ${d.problem}."
        if (d.active) {
            val who = if (!d.operator.isNullOrEmpty()) " par ${d.operator}" else ""
            val silence = SILENCES[d.silence]
            return "En cours$who : " + (if (d.access == "public") "publique" else "privée") + ", " +
                (PHASES[d.phase] ?: d.phase.orEmpty()) + ", reste " + remaining(d.remainingS) +
                (if (d.voice) ", voix émise diffusée" else ", voix émise NON diffusée") +
                (if (d.outsideBands) ", hors bandes diffusé" else ", silence hors des bandes autorisées") + "." +
                (if (silence != null) " En ce moment, SILENCE pour les auditeurs : $silence." else "")
        }
        val last = d.lastStop?.cause?.let { STOPS[it] }?.let { " Dernière : $it." }.orEmpty()
        return "Aucune diffusion en cours.$last"
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
        if (f.hours != null && f.hours !in 1..24) return null to "Durée : 1 à 24 h, ou sans limite."
        val keys = META.map { it.first }
        val args = linkedMapOf(
            "access" to JsonPrimitive(if (f.public) "public" else "prive"),
            "hours" to (f.hours?.let { JsonPrimitive(it) } ?: JsonNull),
            "voice" to JsonPrimitive(f.voice),
            "meta" to JsonArray(f.meta.filter { it in keys }.map { JsonPrimitive(it) }),
        )
        for ((k, limit) in LIMITS) {
            val v = when (k) { "pseudo" -> f.pseudo; "indicatif" -> f.indicatif; else -> f.message }.trim()
            val label = META.first { it.first == k }.second
            if (v.length > limit) return null to "$label : $limit caractères au plus."
            if (v.any { it.code < 0x20 || it.code in 0x7F..0x9F }) return null to "$label : caractère invalide."
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
