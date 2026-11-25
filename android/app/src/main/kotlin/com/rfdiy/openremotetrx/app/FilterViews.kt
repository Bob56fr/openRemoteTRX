// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.Controls
import com.rfdiy.openremotetrx.logic.Filters
import com.rfdiy.openremotetrx.logic.Tr
import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.State
import kotlin.math.roundToInt

/**
 * Fenêtre « Largeur des filtres » (étape 395, comme la page) : appui long sur FIL. Icom = trois curseurs (largeurs relues
 * par la station sur le port B, le poste passe un instant sur chaque préréglage) ; paliers imposés (Yaesu) = un curseur
 * sur les paliers du mode. La largeur part au LÂCHER du curseur ; tout est verrouillé pendant l'émission.
 */
@Composable
internal fun FilterWidthDialog(hello: Hello?, state: State?, enabled: Boolean, onDismiss: () -> Unit) {
    val view = Filters.dialog(hello, state, locked = !enabled)
    val dragging = remember { mutableStateMapOf<Int, Float>() }       // préréglage (0 = paliers) -> position du doigt

    @Composable
    fun row(key: Int, title: String, steps: List<Int>, hz: Int?, current: Boolean, onSet: (Int) -> Unit) {
        val at = dragging[key] ?: (if (hz != null) steps.indexOf(Filters.nearest(steps, hz)) else 0).toFloat()
        val width = steps[at.roundToInt().coerceIn(0, steps.size - 1)]
        Text(title + " · " + Controls.formatWidth(width) + if (current) " (" + Tr.t("filterdialog.current") + ")" else "",
             fontWeight = if (current) FontWeight.Bold else FontWeight.Normal)
        Slider(
            value = at, onValueChange = { dragging[key] = it }, enabled = enabled,
            valueRange = 0f..(steps.size - 1).toFloat(), steps = (steps.size - 2).coerceAtLeast(0),
            onValueChangeFinished = { dragging.remove(key)?.let { onSet(steps[it.roundToInt().coerceIn(0, steps.size - 1)]) } },
        )
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(Tr.t("filterdialog.title")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (view.mode.isNotEmpty()) Text(Tr.t("filterdialog.mode", "mode" to view.mode), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
                when {
                    view.kind == "presets" && view.known -> for (r in view.rows) {
                        row(r.filter, "FIL${r.filter}", view.steps, r.hz, r.filter == view.current) { RigHub.setFilterWidth(r.filter, it) }   // i18n-ok
                    }
                    view.kind == "steps" -> row(0, "FIL", view.steps, view.hz, true) { RigHub.setFilterWidth(null, it) }   // i18n-ok
                }
                val note = when {
                    !enabled -> Tr.t("rigdialogs.locked_tx")
                    view.kind == "presets" -> if (view.known) Tr.t("filterdialog.hint_presets") else Tr.t("filterdialog.reading")
                    view.kind == "steps" -> if (view.quick) Tr.t("filterdialog.hint_quick") else Tr.t("filterdialog.hint_steps")
                    else -> Tr.t("filterdialog.none")
                }
                Text(note, style = MaterialTheme.typography.bodySmall, color = if (!enabled) Page.ALERTE else Page.TEXTE_2)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.close")) } },
    )
}
