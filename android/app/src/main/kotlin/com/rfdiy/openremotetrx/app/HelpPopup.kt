// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.layout.layout
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

/**
 * Échelle de l'interface (tablette : taille du texte réglable, 1 = téléphone). Les boutons compacts et les interrupteurs
 * la suivent, comme le texte (demande de l'utilisateur, 2026-11-09). Le PTT et le STOP ne la suivent pas.
 */
val LocalUiScale = compositionLocalOf { 1f }

/** Aide courte par appui long (logic/Help.kt) : une seule fenêtre pour toute l'application. */
object HelpPopup {
    var shown by mutableStateOf<Pair<String, String>?>(null)
        private set

    fun show(title: String, text: String) { shown = title to text }

    fun close() { shown = null }
}

@Composable
fun HelpDialog() {
    val (title, text) = HelpPopup.shown ?: return
    AlertDialog(
        onDismissRequest = HelpPopup::close,
        title = { Text(title) },
        text = { Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) },
        confirmButton = { TextButton(onClick = HelpPopup::close) { Text("OK") } },
    )
}

/** Interrupteur à l'échelle de l'interface : réduit vraiment sa place (pas seulement son dessin). */
@Composable
fun AppSwitch(checked: Boolean, onCheckedChange: ((Boolean) -> Unit)?, modifier: Modifier = Modifier, enabled: Boolean = true) {
    val s = LocalUiScale.current
    if (s >= 0.999f) {
        Switch(checked = checked, onCheckedChange = onCheckedChange, modifier = modifier, enabled = enabled)
        return
    }
    Switch(
        checked = checked, onCheckedChange = onCheckedChange, enabled = enabled,
        modifier = modifier
            .layout { measurable, constraints ->
                val p = measurable.measure(constraints)
                layout((p.width * s).roundToInt(), (p.height * s).roundToInt()) {
                    p.place(((p.width * s - p.width) / 2).roundToInt(), ((p.height * s - p.height) / 2).roundToInt())
                }
            }
            .scale(s),
    )
}
