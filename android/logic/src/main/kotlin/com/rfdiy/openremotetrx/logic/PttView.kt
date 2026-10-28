// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Protocol
import com.rfdiy.openremotetrx.protocol.PttStatus
import kotlin.math.ceil
import kotlin.math.max

/**
 * Ce que l'écran, la notification et la voiture montrent de l'émission. Tout vient de l'état publié par la
 * station (`state.ptt`) : aucune émission n'est jamais supposée après un appui.
 */
data class PttView(
    /** KEYING, TX ou UNKEYING : à montrer comme une émission. */
    val transmitting: Boolean,
    /** Émission de CE téléphone (propriétaire) : battements, micro, compte à rebours. */
    val mine: Boolean,
    /** Émission d'un autre client : le PTT de ce téléphone ne peut que couper. */
    val other: Boolean,
    val label: String,
    /** Secondes restantes avant la coupure par le TOT, ou null. */
    val totSeconds: Int?,
    val totWarning: Boolean,
    /** Bandeau « poste utilisé sur place », ou null. */
    val local: String?,
    /** « Reprendre la main » possible : attente locale en cours ET pas d'émission au micro du poste. */
    val canReleaseLocal: Boolean,
    /** Alerte de température : "", "warn" ou "hot". */
    val tempAlert: String,
    /** Défaut verrouillé (unkey_failed) : intervention sur la station. */
    val fault: String,
    val lastCut: String,
) {
    companion object {
        private val LOCAL_REASONS = mapOf(
            "tx" to "émission au micro du poste",
            "frequency" to "fréquence changée sur le poste",
            "mode" to "mode changé sur le poste",
        )

        fun of(ptt: PttStatus, clientId: String): PttView {
            val active = ptt.state in Protocol.ACTIVE_STATES
            val left = ptt.localRemainingS
            val local = left?.let {
                val s = max(0, ceil(it).toInt())
                val time = if (ptt.localTx) "pendant l'émission locale" else "encore %d:%02d".format(s / 60, s % 60)
                "POSTE UTILISÉ SUR PLACE (${LOCAL_REASONS[ptt.localReason] ?: "action sur le poste"}) : PTT à distance bloqué $time"
            }
            return PttView(
                transmitting = active,
                mine = active && ptt.owner == clientId,
                other = active && ptt.owner != null && ptt.owner != clientId,
                label = Texts.PTT_LABELS[ptt.state] ?: ptt.state,
                totSeconds = if (active) ptt.totRemainingS?.let { max(0, ceil(it).toInt()) } else null,
                totWarning = active && ptt.totWarning,
                local = local,
                canReleaseLocal = left != null && !ptt.localTx,
                tempAlert = ptt.tempAlert.takeIf { it == "warn" || it == "hot" } ?: "",
                fault = ptt.fault,
                lastCut = ptt.lastCutReason.takeIf { it.isNotEmpty() }?.let { Texts.cut(it) } ?: "",
            )
        }
    }
}
