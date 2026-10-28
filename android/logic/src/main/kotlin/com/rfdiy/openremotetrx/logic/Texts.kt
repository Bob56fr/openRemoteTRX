// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Textes en français des codes de la station (docs/protocole.md § 5 et § 7), repris de la page web (client.js :
 * REASONS, CUT_REASONS). TextsTest vérifie que les deux listes gardent les mêmes codes.
 */
object Texts {
    val REFUSALS: Map<String, String> = mapOf(
        "spectrum_unavailable" to "Spectre HF indisponible pour le moment.",
        "spectrum_busy" to "Réglage du spectre déjà en cours : réessaie.",
        "spectrum_timeout" to "Le poste n'a pas confirmé le réglage du spectre.",
        "spectrum_refused" to "Le poste a refusé ce réglage du spectre (en mode fixe, la largeur ne se règle pas).",
        "bad_setting" to "Réglage du spectre invalide.",
        "out_of_band" to "Fréquence hors des bandes d'émission autorisées.",
        "cooldown" to "Trop rapproché : attends une seconde avant de réémettre.",
        "unknown_client" to "Client non reconnu par la passerelle.",
        "tx_disabled" to "Aucune bande d'émission autorisée dans la configuration.",
        "cat_down" to "Liaison avec le poste perdue.",
        "cat_error" to "Le poste ne répond pas correctement.",
        "ptt_unreadable" to "L'état du PTT n'est pas lisible sur ce poste : émission refusée par sécurité.",
        "rig_already_tx" to "Le poste est déjà en émission.",
        "local_active" to "Poste utilisé sur place (micro, bouton ou mode du poste) : PTT à distance bloqué. « Reprendre la main » pour le débloquer.",
        "local_tx" to "Le poste émet en ce moment depuis son micro : impossible de reprendre la main.",
        "rig_hot" to "Poste trop chaud : émission refusée jusqu'à ce qu'il refroidisse.",
        "report_empty" to "Le rapport est vide.",
        "report_too_soon" to "Un rapport vient déjà d'être envoyé : réessaie dans quelques secondes.",
        "report_storage_error" to "La station n'a pas pu enregistrer le rapport (disque ?).",
        "reports_unavailable" to "Cette station ne reçoit pas les rapports : utilise « Partager / e-mail ».",
        "fault_latched" to "Défaut verrouillé : intervention sur la station requise.",
        "starting" to "La station démarre : réessaie dans un instant.",
        "not_idle" to "Une coupure ou une émission est en cours.",
        "cancelled" to "Prise d'émission annulée par une coupure.",
        "ptt_write_failed" to "L'ordre d'émission a échoué ; retour en réception.",
        "rig_did_not_key" to "Le poste n'est pas passé en émission ; retour en réception.",
        "tx_active" to "Impossible pendant l'émission (fréquence, mode et réglages du poste sont verrouillés).",
        "mode_not_allowed" to "Émission refusée dans ce mode : le poste ne module par l'USB qu'en mode données (USB-D...). Change de mode.",
        "unknown_memory" to "Cette mémoire n'existe plus (supprimée depuis un autre appareil ?).",
        "memories_unavailable" to "Les mémoires ne sont pas disponibles sur cette station.",
        "storage_error" to "La station n'a pas pu enregistrer les mémoires (disque ?).",
        "layouts_unavailable" to "Les mises en page personnalisées ne sont pas disponibles sur cette station.",
        "beeps_unavailable" to "Les bips de fin d'émission ne sont pas disponibles sur cette station.",
        "beeps_storage_error" to "La station n'a pas pu enregistrer le réglage des bips.",
        "layout_invalid" to "Mise en page refusée par la station (règles de sécurité ou de lisibilité non respectées).",
        "layout_storage_error" to "La station n'a pas pu enregistrer la mise en page (disque ?).",
        "invalid" to "Valeur refusée par le poste.",
        "rig_error" to "Erreur du poste.",
    )

    val CUTS: Map<String, String> = mapOf(
        "tot" to "durée maximale d'émission atteinte",
        "heartbeat" to "perte du signal de vie du client",
        "toggle" to "demande d'un client",
        "stop" to "bouton STOP",
        "client_disconnected" to "déconnexion du client émetteur",
        "frequency_changed" to "fréquence modifiée sur le poste",
        "mode_changed" to "mode modifié sur le poste pendant l'émission",
        "rig_reported_rx" to "le poste est repassé en réception",
        "cat_down" to "liaison avec le poste perdue",
        "rig_silent" to "poste muet",
        "rig_overheat" to "poste trop chaud",
        "ptt_write_failed" to "échec de l'ordre d'émission",
        "rig_did_not_key" to "le poste n'a pas émis",
        "shutdown" to "arrêt de la station",
        "startup" to "démarrage de la station",
    )

    /**
     * Causes d'une connexion perdue ou impossible (client.js : LOSS_REASONS, titres). « pin » et « protocol » sont
     * propres à l'application (empreinte du certificat, version de protocole inconnue).
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
        "http" to "Réponse inattendue de la station",
        "client_error" to "Erreur dans l'application",
        "pin" to "Empreinte du certificat DIFFÉRENTE : ce n'est peut-être pas ta station, connexion bloquée",
    )

    val PTT_LABELS = mapOf("RX" to "RÉCEPTION", "KEYING" to "PRISE D'ÉMISSION", "TX" to "ÉMISSION", "UNKEYING" to "COUPURE EN COURS")

    /** Refus d'une commande : texte connu, sinon le détail donné par la station, sinon le code. */
    fun refusal(reason: String, detail: String = ""): String =
        REFUSALS[reason] ?: detail.ifBlank { "Refusé par la station ($reason)." }

    fun cut(reason: String): String = CUTS[reason] ?: reason

    fun loss(code: String): String = LOSSES[code] ?: LOSSES.getValue("client_error")
}
