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

    /** Taille du texte sur tablette, en % (réglable dans Réglages, mémorisée sur l'appareil ; demande de l'utilisateur). */
    const val FONT_MIN_PCT = 70
    const val FONT_MAX_PCT = 100
    const val FONT_DEFAULT_PCT = 85
    /** Part de la hauteur donnée au spectre HF (en bas, toute la largeur : « l'effet waouh », choix de l'utilisateur). */
    const val SPECTRUM_SHARE = 0.40f

    /** Spectres HF et audio côte à côte : part de la largeur du spectre HF (séparateur à glisser), bornée. */
    const val SPLIT_DEFAULT = 0.7f
    const val SPLIT_MIN = 0.2f
    const val SPLIT_MAX = 0.8f

    fun split(value: Float?): Float =
        if (value == null || value.isNaN()) SPLIT_DEFAULT else value.coerceIn(SPLIT_MIN, SPLIT_MAX)

    /** Valeur mémorisée => taille permise (pas de 5 %), défaut si absente ou illisible. */
    fun fontPct(stored: Int?): Int {
        val v = stored ?: return FONT_DEFAULT_PCT
        if (v < FONT_MIN_PCT || v > FONT_MAX_PCT) return FONT_DEFAULT_PCT
        return (v / 5) * 5
    }

    fun of(widthDp: Int, heightDp: Int): ScreenLayout =
        if (widthDp >= WIDE_MIN_DP && widthDp > heightDp && heightDp >= SHORT_SIDE_MIN_DP) ScreenLayout.WIDE else ScreenLayout.PHONE
}
