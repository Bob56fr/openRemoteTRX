// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.SharedPreferences
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.logic.MobileFeature
import com.rfdiy.openremotetrx.logic.MobileFeatures

/**
 * Choix d'affichage des « Fonctionnalités mobiles » (logic/MobileFeatures.kt), gardés dans les préférences « ui » du
 * téléphone ; état Compose partagé par tous les écrans (une seule lecture des préférences par processus).
 */
object Features {
    private val chosen = mutableStateMapOf<String, Boolean>()
    private var loaded = false

    fun load(prefs: SharedPreferences) {
        if (loaded) return
        loaded = true
        for (f in MobileFeature.entries) if (prefs.contains(f.prefKey)) chosen[f.key] = prefs.getBoolean(f.prefKey, f.default)
    }

    /** Affichée ? Une fonction EN SERVICE l'est toujours (masquer n'arrête rien). */
    fun shown(f: MobileFeature, inService: Boolean = false): Boolean = MobileFeatures.shown(f, chosen[f.key], inService)

    fun chosen(f: MobileFeature): Boolean = chosen[f.key] ?: f.default

    fun set(prefs: SharedPreferences, f: MobileFeature, on: Boolean) {
        chosen[f.key] = on
        prefs.edit().putBoolean(f.prefKey, on).apply()
    }
}

/** Rubrique « Fonctionnalités mobiles » des Réglages : un interrupteur d'affichage par fonction. */
@Composable
internal fun FeaturesSection(prefs: SharedPreferences, inService: (MobileFeature) -> Boolean) {
    Text("Fonctionnalités mobiles", style = MaterialTheme.typography.titleSmall)
    Text("Ce qui s'affiche dans l'application, sur ce téléphone seulement. Masquer n'arrête rien : une fonction en service reste affichée.",
         color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
    for (f in MobileFeature.entries) {
        val busy = inService(f)
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppSwitch(checked = Features.chosen(f), onCheckedChange = { Features.set(prefs, f, it) })
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(f.label, style = MaterialTheme.typography.bodyMedium)
                Text(f.where + if (busy && !Features.chosen(f)) " · " + MobileFeatures.IN_SERVICE else "",
                     color = if (busy && !Features.chosen(f)) Page.ALERTE else Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
    Text(MobileFeatures.ALWAYS, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
}
