// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color

/**
 * Couleurs du thème par défaut de la page web (client.css, :root) : même identité visuelle que la page (demande de
 * l'utilisateur). Les rôles Material sont reliés aux variables de la page.
 */
object Page {
    val FOND = Color(0xFF04070B)            // --fond
    val PANNEAU = Color(0xFF0B1118)         // --fond-panneau
    val INSTRUMENT = Color(0xFF0E151D)      // --fond-instrument (afficheur)
    val CHAMP = Color(0xFF0F151D)           // --fond-champ
    val TEXTE = Color(0xFFE9F1FB)           // --texte, --frequence
    val TEXTE_2 = Color(0xFF7F90A5)         // --texte-secondaire
    val ACCENT = Color(0xFF2F86E0)          // --accent
    val MESURE = Color(0xFF7CC0FF)          // --mesure
    val BORD = Color(0xFF33465C)            // --bouton-bord
    val LIGNE = Color(0xFF1A2532)           // --ligne : séparateurs doux
    val SELECTION = Color(0xFF14304F)       // --selection-fond
    val TX = Color(0xFFE5484D)              // --tx, --erreur
    val TX_FOND = Color(0xFF2A1012)         // --tx-fond
    val ALERTE = Color(0xFFF0A830)          // --alerte
    val SUCCES = Color(0xFF35C47A)          // --succes
    val COMMANDE = Color(0xFF243040)        // --commande-fond

    val scheme = darkColorScheme(
        primary = ACCENT, onPrimary = Color.White,
        secondary = MESURE, onSecondary = FOND,
        secondaryContainer = SELECTION, onSecondaryContainer = Color.White,
        tertiary = ALERTE, onTertiary = FOND,
        background = FOND, onBackground = TEXTE,
        surface = FOND, onSurface = TEXTE,
        surfaceVariant = INSTRUMENT, onSurfaceVariant = TEXTE_2,
        surfaceContainer = PANNEAU, surfaceContainerHigh = INSTRUMENT, surfaceContainerHighest = CHAMP,
        surfaceContainerLow = PANNEAU, surfaceContainerLowest = FOND,
        outline = BORD, outlineVariant = LIGNE,
        error = TX, onError = Color.White,
    )
}
