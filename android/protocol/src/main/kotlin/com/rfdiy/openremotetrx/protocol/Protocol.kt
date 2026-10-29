// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

/**
 * Constantes du protocole client <-> station (docs/protocole.md). Les valeurs de sécurité (battements, délais)
 * sont celles de la page web (client.js) : la station coupe d'elle-même si le client ne suit pas.
 */
object Protocol {
    /** Version comprise par cette application ; une station qui en annonce une autre est refusée (réception seule). */
    const val VERSION = 1

    /** Taille maximale d'une commande ordinaire (octets UTF-8), hors layout_save et bug_report. */
    const val MAX_MESSAGE_BYTES = 2048

    /** Cadence des battements pendant une émission (la station attend 500 ms et coupe après 2 s). */
    const val HEARTBEAT_TICK_MS = 400L

    /** Battements envoyés dès la demande de prise d'émission, avant même la confirmation de la station. */
    const val HEARTBEAT_GRACE_MS = 3000L

    /** États du PTT à afficher comme une émission. */
    val ACTIVE_STATES = setOf("KEYING", "TX", "UNKEYING")

    /** Fonctions toujours offertes (hello.features), puis celles qu'une station peut ne pas offrir. */
    val BASE_FEATURES = listOf("ptt", "frequency", "mode", "squelch", "functions", "levels", "local_release")
    val OPTIONAL_FEATURES = listOf("memories", "layouts", "spectrum", "beeps", "bug_report", "selcall", "selcall_send")
}
