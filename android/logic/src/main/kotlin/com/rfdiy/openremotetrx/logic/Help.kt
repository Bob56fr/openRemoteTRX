// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Aides courtes affichées par un APPUI LONG sur un bouton qui n'a pas d'autre action longue (demande de l'utilisateur,
 * 2026-11-09). Un seul endroit pour les textes : fonctions du poste (clés de `Controls.chips`), boutons du client,
 * spectres. Un bouton sans aide ici ne montre rien (aucune fenêtre vide).
 */
object Help {
    /** Fonctions du poste, par clé de `ControlChip` (toutes couvertes : HelpTest). */
    val CONTROLS: Map<String, String> = mapOf(
        "NR" to "Réducteur de bruit du poste. Appui : marche / arrêt. Appui long : niveau de réduction (fenêtre NR / NB).",
        "NB" to "Suppresseur de parasites impulsionnels (allumages, clôtures électriques). Appui : marche / arrêt. Appui long : niveau.",
        "PREAMP" to "Préamplificateur de réception du poste. Appui : change de cran (arrêt, P.AMP 1, P.AMP 2 selon le poste). " +
            "Utile sur les bandes hautes ; à couper si les signaux forts saturent.",
        "ATT" to "Atténuateur d'entrée du poste. Appui : marche / arrêt. Réduit tous les signaux (station voisine puissante, " +
            "bandes basses chargées) ; coupe le préamplificateur.",
        "NOTCH" to "Filtre coupe-bande du poste contre une porteuse ou un sifflement. Appui : automatique, puis manuel, puis arrêt.",
        "AGC" to "Commande automatique de gain : vitesse de retour du gain après un signal fort (rapide, moyenne, lente). " +
            "Appui : vitesse suivante.",
        "FIL" to "Largeur du filtre de réception. Appui : filtre suivant (FIL1, FIL2, FIL3 sur un Icom, sinon les largeurs " +
            "déclarées par le poste).",
        "PWR" to "Puissance d'émission du poste. Appui : choisir la puissance (jamais au-delà du plafond de la station).",
        "AIP" to "IP+ (Icom) : améliore la tenue aux signaux forts au prix d'un peu de sensibilité. Appui : marche / arrêt.",
        "COMP" to "Compresseur de modulation du poste (BLU) : voix plus dense, plus « punchy ». Appui : marche / arrêt. " +
            "Surveiller l'ALC.",
        "RIT" to "Clarifieur de réception : décale l'écoute sans changer la fréquence d'émission. Appui : marche / arrêt ; " +
            "réglage par le curseur sous le squelch, toucher la valeur pour revenir à 0.",
        "XIT" to "ΔTX (XIT) : décale la fréquence d'ÉMISSION. La station vérifie la bande sur la fréquence réellement émise. " +
            "Appui : marche / arrêt.",
        "TUNER" to "Coupleur d'antenne automatique du poste. Appui : en service / hors service.",
    )

    /** Boutons du client et des spectres. */
    val CLIENT: Map<String, String> = mapOf(
        "SEL" to "SELCALL de la station : appel sélectif en BLU. « SEL 4721 » = en veille sur ce code (son coupé), " +
            "« SEL OUVERT » = appel reçu. Appui : panneau SELCALL.",
        "BZH" to "Breizh Audio Box : chaîne de traitement de la voix émise. Vert = prête, orange = repli en direct, " +
            "gris = absente. Appui : sa fenêtre.",
        "WF" to "Petit waterfall HF de l'onglet Station. Appui : affiché / masqué.",
        "HF" to "Spectre HF du poste, envoyé par la station : il consomme de la bande passante. Le masquer en 4G / 5G " +
            "pour économiser des données.",
        "SON" to "Spectre du son reçu, calculé sur cet appareil : aucune donnée réseau, un peu de batterie.",
        "STEP" to "Pas d'accord des touches − et +. Appui : pas suivant.",
        "ARM" to "Émission autorisée : sécurité à deux gestes. Tant qu'elle est coupée, le PTT est sans effet. " +
            "Toujours coupée après une connexion.",
        "MUTE" to "Coupe le son reçu sur cet appareil (la station continue de recevoir).",
    )

    fun control(key: String): String? = CONTROLS[key]

    fun client(key: String): String? = CLIENT[key]
}
