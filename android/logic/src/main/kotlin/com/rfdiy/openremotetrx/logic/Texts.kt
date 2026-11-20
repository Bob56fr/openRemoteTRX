// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Textes des codes de la station (docs/protocole.md § 5 et § 7). Refus et coupures : tronc commun partagé avec la
 * station et la page web (trxstation/i18n/client.<langue>.json, lu par [Tr]) ; le reste encore en français (lot T2).
 */
object Texts {
    /** Refus de la station, par code (tronc commun `refus.<code>` de trxstation/i18n/client.<langue>.json). */
    val REFUSALS: Map<String, String> get() = Tr.section("refus")

    /** Motifs d'une coupure de l'émission, par code (tronc commun `coupure.<code>`). */
    val CUTS: Map<String, String> get() = Tr.section("coupure")

    /**
     * Causes d'une connexion perdue ou impossible (client.js : LOSS_REASONS, titres). « pin » et « untrusted » sont
     * propres à l'application (empreinte différente ; certificat auto-signé sans empreinte).
     */
    val LOSSES: Map<String, String> = mapOf(
        "datachannel_closed" to "Canal de contrôle fermé",
        "connection_failed" to "Liaison réseau échouée",
        "connection_closed" to "Liaison fermée",
        "ice_failed" to "Liaison réseau échouée (ICE)",
        "silence" to "Plus de nouvelles de la station",
        "no_hello" to "Canal de contrôle jamais ouvert (UDP bloqué ?)",
        "network" to "Station injoignable",
        "auth" to "Identifiants refusés (ou trop d'essais : attends quelques minutes)",
        "busy" to "Station occupée (trop de connexions)",
        "refused" to "Accès refusé par la station (compte désactivé ou expiré, visiteurs complets, opérateur absent)",
        "http" to "Réponse inattendue de la station",
        "client_error" to "Erreur dans l'application",
        "pin" to "Empreinte du certificat DIFFÉRENTE : ce n'est peut-être pas ta station, connexion bloquée",
        "untrusted" to "Certificat de la station non reconnu : saisis son empreinte (TRX Console, menu 4.1) ou scanne son QR code",
    )

    val PTT_LABELS = mapOf("RX" to "RÉCEPTION", "KEYING" to "PRISE D'ÉMISSION", "TX" to "ÉMISSION", "UNKEYING" to "COUPURE EN COURS")

    /** Refus d'une commande : texte connu, sinon le détail donné par la station, sinon le code. */
    fun refusal(reason: String, detail: String = ""): String =
        (if (reason.isNotEmpty() && !reason.startsWith("_")) Tr.find("refus.$reason") else null)
            ?: detail.ifBlank { Tr.t("refus._inconnu", "code" to reason) }

    /** Texte d'un refus suivi du code du catalogue (« … [ORT-5116] ») ; tout autre texte que ORT-NNNN est ignoré. */
    fun withCode(text: String, ort: String?): String =
        if (ort != null && Regex("^ORT-\\d{4}$").matches(ort)) "$text [$ort]" else text

    fun cut(reason: String): String =
        (if (reason.isNotEmpty() && !reason.startsWith("_")) Tr.find("coupure.$reason") else null) ?: reason

    fun loss(code: String): String = LOSSES[code] ?: LOSSES.getValue("client_error")
}
