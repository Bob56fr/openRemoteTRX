// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.BreizhEntry
import com.rfdiy.openremotetrx.logic.BreizhLevel
import com.rfdiy.openremotetrx.logic.BreizhView
import com.rfdiy.openremotetrx.logic.Breizhs

/** Couleur du voyant BZH et du texte d'état (vert, orange, gris), comme la page. */
fun breizhColor(level: BreizhLevel): Color = when (level) {
    BreizhLevel.OK -> Page.SUCCES
    BreizhLevel.WARN -> Page.ALERTE
    BreizhLevel.OFF -> Page.TEXTE_2
}

/**
 * Breizh Audio Box (station 0.100.0+, opérateur) : état, volume retour, « Direct », réactivation après un repli,
 * journal de la liaison. Comme la rubrique de la page ; réglages pris à la PROCHAINE émission, jamais pendant.
 */
@Composable
fun BreizhDialog(view: BreizhView, events: List<BreizhEntry>, onDismiss: () -> Unit) {
    var gain by remember(view.returnGainDb) { mutableStateOf(view.returnGainDb.toFloat()) }
    LaunchedEffect(Unit) { RigHub.breizhLog() }                      // journal relu sur la station à l'ouverture
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        title = { Text("Breizh Audio Box") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "Votre voix passe par Breizh Audio Box, sur un PC du réseau local de la station, avant d'aller au poste. La " +
                        "station garde le PTT, le TOT et son limiteur : si Breizh ne répond plus, l'émission continue en direct, à " +
                        "gain réduit. Le son du micro circule en clair sur ce réseau local.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Text(view.text, color = breizhColor(view.level), fontWeight = FontWeight.Bold)
                if (view.details.isNotEmpty()) Text(view.details, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Volume retour", style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.width(8.dp))
                    Slider(
                        value = gain, onValueChange = { gain = Breizhs.snapGain(it.toDouble()).toFloat() },
                        onValueChangeFinished = { RigHub.breizhSet(returnGainDb = gain.toDouble()) },
                        valueRange = Breizhs.GAIN_MIN.toFloat()..Breizhs.GAIN_MAX.toFloat(), steps = 51,
                        modifier = Modifier.weight(1f),
                    )
                    Text(Breizhs.gainText(gain.toDouble()), style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(64.dp))
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AppSwitch(checked = view.bypass, onCheckedChange = { RigHub.breizhSet(bypass = it) })
                    Spacer(Modifier.width(8.dp))
                    Text("Direct : ignorer Breizh (à la prochaine émission)", style = MaterialTheme.typography.bodyMedium)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (view.canReactivate) OutlinedButton(onClick = { RigHub.breizhReactivate() }) { Text("Réactiver Breizh") }
                    OutlinedButton(onClick = { RigHub.breizhLog() }) { Text("Relire le journal") }
                }
                Text(
                    "Les réglages s'appliquent à la prochaine émission, jamais pendant. Égaliseur, chorus, réverbération et " +
                        "scrambler de ce téléphone sont coupés quand la voix passe par Breizh.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                if (events.isNotEmpty()) Text("Journal", style = MaterialTheme.typography.titleSmall)
                for (e in events.asReversed()) {                           // le plus récent en tête
                    Text(e.line, color = if (e.warn) Page.ALERTE else Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
    )
}
