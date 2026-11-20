// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/** Traitements du micro : annulation d'écho, réduction de bruit (le contrôle automatique de gain reste toujours coupé). */
data class MicProcessing(val echo: Boolean, val noise: Boolean)

/** Profil du micro selon l'environnement (mêmes clés et mêmes valeurs que la page : client.js, MIC_PROFILES). */
data class MicProfile(val key: String, val label: String, val processing: MicProcessing?)

/**
 * Demande de l'utilisateur (2026-10-29) : coupures de la voix en émission, réduction de bruit trop forte selon
 * l'environnement. « custom » : l'utilisateur choisit lui-même l'écho et le bruit.
 */
object MicProfiles {
    /** Libellés lus à l'affichage (langue de l'application). */
    val ALL: List<MicProfile> get() = listOf(
        MicProfile("quiet", Tr.t("micprofiles.quiet"), MicProcessing(echo = true, noise = false)),
        MicProfile("noisy", Tr.t("micprofiles.noisy"), MicProcessing(echo = true, noise = true)),
        MicProfile("headset_nr", Tr.t("micprofiles.headset_nr"), MicProcessing(echo = false, noise = false)),
        MicProfile("headset", Tr.t("micprofiles.headset"), MicProcessing(echo = false, noise = true)),
        MicProfile("custom", Tr.t("micprofiles.custom"), null),
    )
    const val DEFAULT = "quiet"

    /** Traitements à appliquer ; profil inconnu = pièce calme (comme la page). */
    fun processing(key: String?, customEcho: Boolean = true, customNoise: Boolean = false): MicProcessing {
        val profile = ALL.firstOrNull { it.key == key } ?: ALL.first { it.key == DEFAULT }
        return profile.processing ?: MicProcessing(customEcho, customNoise)
    }
}
