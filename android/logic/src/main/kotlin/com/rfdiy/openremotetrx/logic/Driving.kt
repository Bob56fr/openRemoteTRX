// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/** Pourquoi le mode conduite est en service (ou non). */
enum class DrivingReason { OFF, MANUAL, CAR, PASSENGER }

/**
 * Mode conduite (cahier des charges Android, lot A3) : en roulant, l'écran du téléphone est réduit et le PTT TACTILE
 * est désactivé (règle anti-distraction ; usage du téléphone tenu en main interdit au volant). On n'émet plus que par
 * l'écran de la voiture, les touches du volant ou un bouton Bluetooth ; STOP reste toujours permis.
 *
 * En service : à la main (réglage), ou automatiquement quand une voiture est connectée (Android Auto, mode voiture
 * d'Android), sauf si un passager l'a levé pour cette connexion de la voiture.
 */
object Driving {
    fun reason(manual: Boolean, auto: Boolean, carConnected: Boolean, passenger: Boolean): DrivingReason = when {
        manual -> DrivingReason.MANUAL
        auto && carConnected && passenger -> DrivingReason.PASSENGER
        auto && carConnected -> DrivingReason.CAR
        else -> DrivingReason.OFF
    }

    fun active(reason: DrivingReason) = reason == DrivingReason.MANUAL || reason == DrivingReason.CAR

    /** PTT par l'écran du téléphone : jamais en conduite (STOP reste permis partout). */
    fun touchPttAllowed(reason: DrivingReason) = !active(reason)

    fun label(reason: DrivingReason): String = when (reason) {
        DrivingReason.MANUAL -> "Mode conduite (réglage)"
        DrivingReason.CAR -> "Mode conduite : voiture connectée"
        DrivingReason.PASSENGER -> "Voiture connectée : mode passager"
        DrivingReason.OFF -> ""
    }

    const val PTT_HINT = "En conduite, le PTT de l'écran est désactivé : émettez par l'écran de la voiture, les touches du " +
        "volant ou un bouton Bluetooth (réglage « PTT par le bouton »). STOP reste toujours disponible."
}
