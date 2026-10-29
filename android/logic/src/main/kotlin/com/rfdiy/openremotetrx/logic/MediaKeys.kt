// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/** Touche « média » reçue (bouton d'un casque, touches du volant), déjà ramenée à son rôle. */
enum class MediaKey {
    /** Lecture/Pause, bouton unique d'un casque (HEADSETHOOK). */
    TOGGLE,
    PLAY,
    PAUSE,
    STOP,
    /** Piste suivante, volume… : laissée au système. */
    OTHER,
}

enum class MediaAction { TOGGLE, IGNORE }

/**
 * PTT par le bouton d'un casque ou les touches du volant (réglage désactivé par défaut). Toujours un appui simple
 * (toggle), jamais un maintien ; la prise passe ensuite par les mêmes contrôles que le bouton de l'écran
 * (« Émission autorisée », station source de vérité).
 *
 * Sécurités : appui maintenu (répétitions) ignoré ; un « lecture » envoyé tout seul à la connexion d'un casque ou
 * d'une voiture (premières secondes après l'arrivée d'un appareil audio) ne prend JAMAIS l'émission ; rebonds
 * ignorés ; « pause » et « stop » ne font que terminer SA propre émission, « lecture » ne fait que la prendre.
 */
object MediaKeys {
    /** Après l'arrivée d'un appareil audio (Bluetooth, voiture) : aucune prise d'émission pendant ce délai. */
    const val DEVICE_GRACE_MS = 3000L
    const val DEBOUNCE_MS = 600L

    /**
     * `mine` : CE téléphone détient l'émission (demandée ou confirmée). `sinceDeviceMs` / `sinceLastMs` : temps
     * écoulé depuis l'arrivée du dernier appareil audio et depuis la dernière touche acceptée (null = jamais).
     */
    fun decide(key: MediaKey, repeat: Int, mine: Boolean, sinceDeviceMs: Long?, sinceLastMs: Long?): MediaAction {
        if (key == MediaKey.OTHER || repeat > 0) return MediaAction.IGNORE
        if (sinceLastMs != null && sinceLastMs < DEBOUNCE_MS) return MediaAction.IGNORE
        return when {
            mine -> if (key == MediaKey.PLAY) MediaAction.IGNORE else MediaAction.TOGGLE        // fin de SON émission
            key == MediaKey.PAUSE || key == MediaKey.STOP -> MediaAction.IGNORE
            sinceDeviceMs != null && sinceDeviceMs < DEVICE_GRACE_MS -> MediaAction.IGNORE      // lecture automatique
            else -> MediaAction.TOGGLE                                                         // demande de prise
        }
    }
}
