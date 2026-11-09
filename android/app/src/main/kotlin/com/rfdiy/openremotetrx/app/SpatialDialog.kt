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
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        title = { Text("Spatialisation (stéréo)") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "Rend l'audio reçu stéréo au casque : confort d'écoute, voix au centre, souffle autour. Traité sur ce " +
                        "téléphone seulement : la station n'envoie toujours qu'un son mono.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Spatialisation en service", Modifier.weight(1f))
                    AppSwitch(checked = s.on, onCheckedChange = { save(s.copy(on = it)) })
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((key, p) in Spatials.PRESETS) {
                        CompactChip(p.label, onClick = { save(Spatials.choose(s, key).copy(on = true)) }, selected = s.preset == key)
                    }
                }
                Text("Intensité ${s.width} %")
                Slider(s.width.toFloat(), { save(s.copy(width = it.roundToInt())) }, valueRange = 0f..Spatials.WIDTH_MAX.toFloat())
                Text("Présence voix ${s.presence} %")
                Slider(s.presence.toFloat(), { save(s.copy(presence = it.roundToInt())) }, valueRange = 0f..100f)
                Text("Équilibre G/D " + if (s.balance == 0) "centre" else (if (s.balance < 0) "G " else "D ") + kotlin.math.abs(s.balance))
                Slider(s.balance.toFloat(), { save(s.copy(balance = it.roundToInt())) }, valueRange = -100f..100f)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(onClick = {}, modifier = Modifier.pointerInput(Unit) {
                        detectTapGestures(onPress = { SpatialHub.setAb(true); tryAwaitRelease(); SpatialHub.setAb(false) })
                    }) { Text(if (ui.ab) "MONO" else "A/B (maintenir)") }
                    Spacer(Modifier.width(8.dp))
                    OutlinedButton(onClick = { save(Spatials.choose(s, s.preset)) }, enabled = Spatials.isModified(s)) { Text("Valeurs du préréglage") }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Sortie mono (pas de casque)", Modifier.weight(1f))
                    AppSwitch(checked = s.monoOut, onCheckedChange = { save(s.copy(monoOut = it)) })
                }
                if (ui.playing) {
                    Text("Corrélation G/D ${"%.2f".format(ui.correlation)} (1 = mono)", style = MaterialTheme.typography.bodySmall)
                    LinearProgressIndicator(progress = { (1 - ui.correlation).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                }
                Text(
                    "État : " + when {
                        ui.failed.isNotEmpty() -> ui.failed
                        !s.on -> "éteinte (son mono)"
                        ui.monoReason.isNotEmpty() -> ui.monoReason
                        s.preset == "mono" -> "préréglage Mono (comparaison)"
                        ui.playing -> "« ${Spatials.label(s)} »" + if (ui.ab) " — A/B : MONO" else ""
                        else -> "« ${Spatials.label(s)} » dès la connexion"
                    } + ".",
                    style = MaterialTheme.typography.titleSmall,
                )
            }
        },
    )
}
