// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * « Fonctionnalités mobiles » (demande de l'utilisateur du 2026-11-20, étape 300) : commutateurs d'AFFICHAGE de
 * l'application, rangés sur le téléphone (jamais sur la station). Règles :
 * - masquer n'arrête rien : une fonction EN SERVICE reste toujours affichée (sinon elle agirait sans qu'on la voie) ;
 * - rien de sécurité n'est masquable : PTT, STOP, armement, TOT, bandeaux (émission, TOS, mise en sécurité, poste éteint) ;
 * - le micro (onglet Audio) est toujours visible.
 * Kotlin pur : l'écran lit `shown`, les préférences sont lues et écrites par l'application.
 */
enum class MobileFeature(val key: String, val default: Boolean) {
    ROGER("roger", false),
    EQ("eq", false),
    CHORUS_REVERB("chorus_reverb", false),
    SELCALL("selcall", false),
    WATERFALL("waterfall", true),
    SPATIAL("spatial", true),
    BREIZH("breizh", true),
    FREEDV("freedv", true),
    DIFFUSION("diffusion", true),
    LISTEN("listen", true),
    SCRAMBLER("scrambler", true),
    REPLAY("replay", true),
    FRIENDS("friends", true),
    BIG_PTT("big_ptt", true);

    /** Nom de la fonction (clé `mobilefeatures.<clé>_label`), lu à l'affichage. */
    val label: String get() = Tr.t("mobilefeatures." + key + "_label")
    /** Où la fonction apparaît (clé `mobilefeatures.<clé>_where`). */
    val where: String get() = Tr.t("mobilefeatures." + key + "_where")

    val prefKey: String get() = "feature_$key"
}

object MobileFeatures {
    /** Texte de la ligne « toujours visible » de la rubrique. */
    val ALWAYS: String get() = Tr.t("mobilefeatures.always")
    val IN_SERVICE: String get() = Tr.t("mobilefeatures.in_service")

    /**
     * Fonction qui n'existe que si la STATION l'offre (`hello.features`) et menu d'openRemoteTRX Console qui la met en
     * service (étape 392 : interrupteur bloqué avec ce message, pour ne pas croire à une panne) ; null = fonction de
     * l'application seule, toujours disponible.
     */
    private val STATION: Map<MobileFeature, Pair<String, String>> = mapOf(
        MobileFeature.SELCALL to ("selcall" to "5.5"),
        MobileFeature.BREIZH to ("breizh" to "5.5"),
        MobileFeature.FREEDV to ("freedv" to "5.5"),
        MobileFeature.DIFFUSION to ("diffusion" to "5.5"),
        MobileFeature.FRIENDS to ("friends" to "5.5"),
        MobileFeature.WATERFALL to ("spectrum" to "2.7"),
        MobileFeature.REPLAY to ("replay" to "2.1"),
    )

    /** Nom de la fonction de la station (`hello.features`) dont dépend `feature`, ou null. */
    fun stationFeature(feature: MobileFeature): String? = STATION[feature]?.first

    /**
     * Texte sous l'interrupteur quand la station connectée n'offre pas la fonction ; null = interrupteur utilisable
     * (fonction de l'application, station qui l'offre, ou aucune station connectée : rien à juger).
     */
    fun unavailable(feature: MobileFeature, offers: ((String) -> Boolean)?): String? {
        val (name, menu) = STATION[feature] ?: return null
        if (offers == null || offers(name)) return null
        return Tr.t("mobilefeatures.not_on_station", "menu" to menu)
    }

    /** Choix de l'opérateur (`stored`, null = jamais réglé => défaut) ; une fonction en service est toujours affichée. */
    fun shown(feature: MobileFeature, stored: Boolean?, inService: Boolean = false): Boolean =
        inService || (stored ?: feature.default)
}
