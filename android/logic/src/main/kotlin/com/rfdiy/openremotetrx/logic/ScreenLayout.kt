// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/** Disposition de l'écran de la station, d'après la taille de la FENÊTRE (pas le type d'appareil). */
enum class ScreenLayout { PHONE, WIDE }

/**
 * Version tablette (lot A5, docs/android-tablette-cahier-des-charges.md § 3). Étape 149 : seule la fenêtre LARGE en
 * paysage (≥ 840 dp, Material 3 « Expanded », et au moins 600 dp de haut) change de disposition : colonne de l'afficheur à gauche, spectre HF et
 * rubriques à droite (modèle : la page PC). Une fenêtre moyenne (600 à 839 dp) ou un portrait gardent l'interface du
 * téléphone, jusqu'à l'étape suivante. Fenêtre partagée étroite = téléphone ; pliant ouvert en paysage = tablette.
 */
object ScreenLayouts {
    const val WIDE_MIN_DP = 840
    /** Plus petit côté d'une tablette (page : `detectDevice`, moins de 600 dp = téléphone) : un grand téléphone en
     *  paysage (915 × 412 dp) dépasse 840 dp de large mais garde son spectre HF plein écran. */
    const val SHORT_SIDE_MIN_DP = 600
    /** Largeur de la colonne de l'afficheur (page PC : environ 36 rem). */
    const val LEFT_COLUMN_DP = 400

    fun of(widthDp: Int, heightDp: Int): ScreenLayout =
        if (widthDp >= WIDE_MIN_DP && widthDp > heightDp && heightDp >= SHORT_SIDE_MIN_DP) ScreenLayout.WIDE else ScreenLayout.PHONE
}
