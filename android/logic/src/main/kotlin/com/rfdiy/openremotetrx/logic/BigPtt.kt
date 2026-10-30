// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Gros PTT rond au milieu de l'écran (opérateur mobile ou pédestre ; demande de l'utilisateur du 2026-10-30).
 *
 * Masqué par défaut ; il n'apparaît que si l'opérateur le demande par un APPUI LONG sur le PTT habituel. STOP le masque
 * (et coupe, comme toujours), de même qu'une déconnexion. Jamais en mode conduite (PTT tactile interdit en roulant).
 * C'est le MÊME toggle que le PTT habituel : un appui = une commande `toggle` ; l'état montré est celui de la station.
 */
object BigPtt {
    enum class Look { READY, DISARMED, MINE_TX, CUTTING, OTHER, OFF }

    /** Le gros bouton est-il affiché ? */
    fun visible(requested: Boolean, connected: Boolean, driving: Boolean): Boolean = requested && connected && !driving

    /** L'appui long sur le PTT habituel peut-il le faire apparaître ? (micro refusé = réception seule : non) */
    fun canShow(connected: Boolean, protocolOk: Boolean, micAllowed: Boolean, driving: Boolean): Boolean =
        connected && protocolOk && micAllowed && !driving

    fun look(ptt: PttView?, armed: Boolean, enabled: Boolean): Look = when {
        ptt != null && ptt.mine && ptt.transmitting -> Look.MINE_TX
        ptt?.mine == true -> Look.CUTTING
        ptt?.other == true -> Look.OTHER
        !enabled -> Look.OFF
        !armed -> Look.DISARMED
        else -> Look.READY
    }

    /** Texte sous « PTT » (mêmes mots que le PTT habituel). */
    fun caption(look: Look): String = when (look) {
        Look.MINE_TX -> "FIN D'ÉMISSION"
        Look.CUTTING -> "COUPURE…"
        Look.OTHER -> "AUTRE CLIENT EN ÉMISSION"
        Look.DISARMED -> "AUTORISER D'ABORD"
        Look.OFF -> "INDISPONIBLE"
        Look.READY -> "ÉMETTRE"
    }
}
