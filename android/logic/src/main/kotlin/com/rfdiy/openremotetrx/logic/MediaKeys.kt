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
 * Lecture, Pause, Lecture/Pause et le bouton unique d'un casque sont UN SEUL appui « PTT » : un casque choisit
 * lui-même d'envoyer « lecture » ou « pause » selon l'état qu'il croit connaître, ce qui ne dit rien de l'émission
 * (essai du 2026-10-29 : « pause » pendant l'émission n'a pas coupé). Seul « stop » ne prend jamais l'émission.
 *
 * Sécurités : appui maintenu (répétitions) ignoré ; une touche envoyée toute seule à la connexion d'un casque ou
 * d'une voiture (premières secondes après l'arrivée d'un appareil audio) ne prend JAMAIS l'émission (terminer reste
 * toujours permis) ; rebonds ignorés.
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
            mine -> MediaAction.TOGGLE                                                          // fin de SON émission
            key == MediaKey.STOP -> MediaAction.IGNORE
            sinceDeviceMs != null && sinceDeviceMs < DEVICE_GRACE_MS -> MediaAction.IGNORE      // touche automatique
            else -> MediaAction.TOGGLE                                                         // demande de prise
        }
    }

    /** Pourquoi une touche a été ignorée (journal de l'application, pour les essais). */
    fun ignoredWhy(key: MediaKey, repeat: Int, mine: Boolean, sinceDeviceMs: Long?, sinceLastMs: Long?): String = when {
        key == MediaKey.OTHER -> "touche non utilisée"
        repeat > 0 -> "appui maintenu"
        sinceLastMs != null && sinceLastMs < DEBOUNCE_MS -> "rebond"
        !mine && key == MediaKey.STOP -> "« stop » ne prend jamais l'émission"
        !mine && sinceDeviceMs != null && sinceDeviceMs < DEVICE_GRACE_MS -> "appareil audio arrivé à l'instant (touche automatique ?)"
        else -> ""
    }
}
