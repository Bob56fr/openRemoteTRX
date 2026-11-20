// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.SpatialHub
import com.rfdiy.openremotetrx.logic.Spatials
import com.rfdiy.openremotetrx.logic.Tr
import com.rfdiy.openremotetrx.logic.Format
import kotlin.math.roundToInt

/** Réglages de la spatialisation stéréo de la réception (appui long sur ST), comme la rubrique de la page. */
@Composable
fun SpatialDialog(onDismiss: () -> Unit) {
    val context = LocalContext.current
    val ui by SpatialHub.ui.collectAsState()
    val s = ui.settings
    fun save(next: com.rfdiy.openremotetrx.logic.SpatialSettings) = SpatialHub.save(context, next)
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.close")) } },
        title = { Text(Tr.t("spatialdialog.title")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    Tr.t("spatialdialog.intro"),
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(Tr.t("spatialdialog.enabled"), Modifier.weight(1f))
                    AppSwitch(checked = s.on, onCheckedChange = { save(s.copy(on = it)) })
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((key, p) in Spatials.PRESETS) {
                        CompactChip(p.label, onClick = { save(Spatials.choose(s, key).copy(on = true)) }, selected = s.preset == key)
                    }
                }
                Text(Tr.t("spatialdialog.width", "value" to s.width))
                Slider(s.width.toFloat(), { save(s.copy(width = it.roundToInt())) }, valueRange = 0f..Spatials.WIDTH_MAX.toFloat())
                Text(Tr.t("spatialdialog.presence", "value" to s.presence))
                Slider(s.presence.toFloat(), { save(s.copy(presence = it.roundToInt())) }, valueRange = 0f..100f)
                Text(Tr.t("spatialdialog.balance", "value" to (if (s.balance == 0) Tr.t("spatialdialog.balance_center")
                    else Tr.t(if (s.balance < 0) "spatialdialog.balance_left" else "spatialdialog.balance_right", "amount" to kotlin.math.abs(s.balance)))))
                Slider(s.balance.toFloat(), { save(s.copy(balance = it.roundToInt())) }, valueRange = -100f..100f)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(onClick = {}, modifier = Modifier.pointerInput(Unit) {
                        detectTapGestures(onPress = { SpatialHub.setAb(true); tryAwaitRelease(); SpatialHub.setAb(false) })
                    }) { Text(if (ui.ab) "MONO" else Tr.t("spatialdialog.ab_hold")) }
                    Spacer(Modifier.width(8.dp))
                    OutlinedButton(onClick = { save(Spatials.choose(s, s.preset)) }, enabled = Spatials.isModified(s)) { Text(Tr.t("spatialdialog.preset_values")) }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(Tr.t("spatialdialog.mono_out"), Modifier.weight(1f))
                    AppSwitch(checked = s.monoOut, onCheckedChange = { save(s.copy(monoOut = it)) })
                }
                if (ui.playing) {
                    Text(Tr.t("spatialdialog.correlation", "value" to Format.decimal(ui.correlation.toDouble(), 2)), style = MaterialTheme.typography.bodySmall)
                    LinearProgressIndicator(progress = { (1 - ui.correlation).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                }
                Text(
                    Tr.t("spatialdialog.state", "state" to when {
                        ui.failed.isNotEmpty() -> ui.failed
                        !s.on -> Tr.t("spatialdialog.state_off")
                        ui.monoReason.isNotEmpty() -> ui.monoReason
                        s.preset == "mono" -> Tr.t("spatialdialog.state_mono")
                        ui.playing -> Tr.t(if (ui.ab) "spatialdialog.state_playing_ab" else "spatialdialog.state_playing", "preset" to Spatials.label(s))
                        else -> Tr.t("spatialdialog.state_waiting", "preset" to Spatials.label(s))
                    }),
                    style = MaterialTheme.typography.titleSmall,
                )
            }
        },
    )
}
