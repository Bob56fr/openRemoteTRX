// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Pochette d'Android Auto (F5) : une image par bande, une « hors bande », le logo sans liaison. Image FIXE choisie
 * d'après la fréquence (aucune donnée dynamique dessinée dedans : fréquence et S-mètre restent en texte).
 *
 * Nom du fichier = clé + « .png » : `logo`, `hors_bande`, `160m` … `6m`, `2m`, `70cm`. Le service cherche d'abord le
 * fichier de l'utilisateur (dossier `pochettes` de l'application), puis l'image fournie avec l'application.
 */
object Artwork {
    const val LOGO = "logo"
    const val OUT_OF_BAND = "hors_bande"

    /** Bandes VHF/UHF absentes du choix des bandes de l'écran (IC-7300 : HF et 6 m) mais prévues pour les pochettes. */
    private val EXTRA = listOf(Triple("2m", 144_000_000L, 146_000_000L), Triple("70cm", 430_000_000L, 440_000_000L))

    /** Toutes les clés possibles : la liste blanche du fournisseur d'images (rien d'autre n'est servi). */
    val KEYS: List<String> = listOf(LOGO, OUT_OF_BAND) + Radio.BANDS.map { "${it.key}m" } + EXTRA.map { it.first }

    /** Clé de l'image pour l'état de la liaison et la fréquence du poste. */
    fun key(connected: Boolean, hz: Long?): String {
        if (!connected || hz == null) return LOGO
        Radio.bandOf(hz)?.let { return "${it.key}m" }
        return EXTRA.firstOrNull { hz in it.second..it.third }?.first ?: OUT_OF_BAND
    }

    /** Clé d'une bande de l'écran (« 40 » -> « 40m »), pour les icônes de Parcourir. */
    fun bandKey(band: String): String = "${band}m"

    fun isKey(name: String): Boolean = name in KEYS
}
