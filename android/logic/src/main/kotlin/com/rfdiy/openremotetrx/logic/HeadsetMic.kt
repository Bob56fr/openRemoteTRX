// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/** Ce que la couche Android doit faire pour le micro du casque Bluetooth. */
sealed interface HeadsetMicStep {
    data object None : HeadsetMicStep
    /** Passer le casque en mode appel (appareil de communication) ; le micro reste FERMÉ. */
    data object Route : HeadsetMicStep
    /** Casque en mode appel confirmé : ouvrir le micro. */
    data object OpenMic : HeadsetMicStep
    /** Fin d'émission : fermer le micro, rendre le casque à la musique. */
    data object Release : HeadsetMicStep
    /** Fermer le micro, rendre le casque, envoyer STOP (motif au journal). `failure` : panne (son de refus). */
    data class Stop(val why: String, val failure: Boolean = true) : HeadsetMicStep
}

/**
 * Micro du casque Bluetooth pendant l'émission SEULEMENT (étape 96). En mode appel (HFP), le bouton du casque
 * « raccroche » : Android termine lui-même l'appel virtuel et l'application ne reçoit aucune touche (relevé sur le
 * S25 le 2026-11-01). Donc : réception en mode musique (le bouton arrive comme Lecture/Pause => prise d'émission),
 * mode appel ouvert à la confirmation de l'émission, et toute sortie du mode appel pendant l'émission (bouton du
 * casque, casque perdu) = fin d'émission. Sens toujours sûr : cette classe ne peut que couper, jamais émettre.
 *
 * Fail-safe : le micro ne s'ouvre qu'une fois le casque en mode appel ; casque absent, refus d'Android ou mode appel
 * pas établi en [timeoutMs] => STOP (jamais le micro du téléphone à la place).
 */
class HeadsetMic(private val timeoutMs: Long = TIMEOUT_MS) {
    private enum class Phase { IDLE, OPENING, OPEN, STOPPED }

    private var phase = Phase.IDLE
    private var since = 0L

    /** Micro voulu par la session (appelé à chaque état reçu : seules les transitions comptent). */
    fun micWanted(open: Boolean, now: Long): HeadsetMicStep = when {
        open && phase == Phase.IDLE -> {
            phase = Phase.OPENING
            since = now
            HeadsetMicStep.Route
        }
        open -> HeadsetMicStep.None                                // en cours, ouvert, ou déjà coupé : rien de plus
        phase == Phase.IDLE -> HeadsetMicStep.None
        else -> {
            phase = Phase.IDLE
            HeadsetMicStep.Release
        }
    }

    /** Appareil de communication changé (ou relu) : `headset` vrai si c'est le casque Bluetooth. */
    fun routed(headset: Boolean): HeadsetMicStep = when {
        phase == Phase.OPENING && headset -> {
            phase = Phase.OPEN
            HeadsetMicStep.OpenMic
        }
        phase == Phase.OPEN && !headset ->                         // geste normal : appui sur le bouton du casque
            stop("Bouton du casque (ou casque perdu) : fin d'émission.", failure = false)
        else -> HeadsetMicStep.None                                // passage transitoire pendant l'ouverture : attendre
    }

    /** Casque absent ou refusé par Android au moment de l'ouvrir. */
    fun routeFailed(why: String): HeadsetMicStep =
        if (phase == Phase.OPENING) stop(why) else HeadsetMicStep.None

    fun tick(now: Long): HeadsetMicStep =
        if (phase == Phase.OPENING && now - since >= timeoutMs) {
            stop("Le casque n'est pas passé en mode appel en ${timeoutMs / 1000} s : retour en réception (micro resté fermé).")
        } else {
            HeadsetMicStep.None
        }

    /** Fin de la connexion : plus rien d'ouvert. */
    fun reset() {
        phase = Phase.IDLE
    }

    private fun stop(why: String, failure: Boolean = true): HeadsetMicStep {
        phase = Phase.STOPPED                                      // jusqu'à ce que la session ferme le micro
        return HeadsetMicStep.Stop(why, failure)
    }

    companion object {
        const val TIMEOUT_MS = 3000L
    }
}
