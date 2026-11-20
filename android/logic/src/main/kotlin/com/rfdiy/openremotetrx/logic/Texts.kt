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
    val LOSSES: Map<String, String> get() = LOSS_CODES.associateWith { Tr.t("texts.loss_$it") }

    /** Codes de [LOSSES] (textes `texts.loss_<code>`). */
    private val LOSS_CODES = listOf(
        "datachannel_closed", "connection_failed", "connection_closed", "ice_failed", "silence", "no_hello", "network",
        "auth", "busy", "refused", "http", "client_error", "pin", "untrusted",
    )

    /** États du PTT -> libellé (textes `texts.ptt_<état en minuscules>`). */
    val PTT_LABELS: Map<String, String> get() = listOf("RX", "KEYING", "TX", "UNKEYING").associateWith { Tr.t("texts.ptt_" + it.lowercase()) }

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
