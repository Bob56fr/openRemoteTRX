// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * « Fonctionnalités mobiles » (demande de l'utilisateur du 2026-11-20, étape 300) : commutateurs d'AFFICHAGE de
 * l'application, rangés sur le téléphone (jamais sur la station). Règles :
 * - masquer n'arrête rien : une fonction EN SERVICE reste toujours affichée (sinon elle agirait sans qu'on la voie) ;
 * - rien de sécurité n'est masquable : PTT, STOP, armement, TOT, bandeaux (émission, TOS, mode sûr, poste éteint) ;
 * - le micro (onglet Audio) est toujours visible.
 * Kotlin pur : l'écran lit `shown`, les préférences sont lues et écrites par l'application.
 */
enum class MobileFeature(val key: String, val label: String, val where: String, val default: Boolean) {
    ROGER("roger", "Bips de fin d'émission (roger bip)", "onglet Audio", false),
    EQ("eq", "Égaliseur", "bouton EQ, onglet Audio", false),
    CHORUS_REVERB("chorus_reverb", "Chorus et réverbération", "onglet Audio", false),
    SELCALL("selcall", "SELCALL", "bouton SEL", false),
    WATERFALL("waterfall", "Petit waterfall", "bouton WF, onglet Station", true),
    SPATIAL("spatial", "Spatialisation stéréo", "bouton ST", true),
    BREIZH("breizh", "Breizh Audio Box", "voyant BZH", true),
    FREEDV("freedv", "FreeDV", "voyant FDV", true),
    DIFFUSION("diffusion", "Diffusion en direct", "voyant DIF", true),
    LISTEN("listen", "S'écouter sans émettre", "onglet Audio", true),
    SCRAMBLER("scrambler", "Scrambler", "onglet Audio", true),
    REPLAY("replay", "Rediffusion d'un enregistrement", "onglet Audio", true),
    FRIENDS("friends", "Amis", "onglet Amis", true),
    BIG_PTT("big_ptt", "Gros PTT rond", "appui long sur le PTT", true);

    val prefKey: String get() = "feature_$key"
}

object MobileFeatures {
    /** Texte de la ligne « toujours visible » de la rubrique. */
    const val ALWAYS = "Toujours visibles : micro, PTT, STOP, armement, compte à rebours du TOT et bandeaux de sécurité."
    const val IN_SERVICE = "en service : reste affiché"

    /** Choix de l'opérateur (`stored`, null = jamais réglé => défaut) ; une fonction en service est toujours affichée. */
    fun shown(feature: MobileFeature, stored: Boolean?, inService: Boolean = false): Boolean =
        inService || (stored ?: feature.default)
}
