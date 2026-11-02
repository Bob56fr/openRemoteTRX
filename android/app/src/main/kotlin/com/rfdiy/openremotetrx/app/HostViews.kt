// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.logic.HostHealth
import com.rfdiy.openremotetrx.logic.HostSection

private fun hostColor(level: String) = when (level) {
    "bad" -> Page.TX
    "warn" -> Page.ALERTE
    else -> Page.SUCCES
}

/** Petit bargraph vertical de la santé de la machine de la station (page : #host-bar). */
@Composable
fun HostBar(health: HostHealth, onClick: () -> Unit) {
    Box(
        Modifier.size(width = 10.dp, height = 26.dp).clip6()
            .border(BorderStroke(1.dp, Page.BORD), RoundedCornerShape(3.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.BottomCenter,
    ) {
        Box(Modifier.fillMaxWidth().fillMaxHeight(health.fraction.coerceIn(0.04f, 1f))
            .background(hostColor(health.level), RoundedCornerShape(2.dp)))
    }
}

private fun Modifier.clip6(): Modifier = this.background(Page.INSTRUMENT, RoundedCornerShape(3.dp))

/** Synthèse du matériel de la station : rubriques rédigées par la station (host_info), affichées telles quelles. */
@Composable
fun HostDialog(health: HostHealth?, sections: List<HostSection>?, onRefresh: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Matériel de la station") },
        text = {
            Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                health?.let {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        HostBar(it, onClick = {})
                        Text("  " + it.summary, style = MaterialTheme.typography.bodySmall, color = hostColor(it.level))
                    }
                }
                when {
                    sections == null -> Text("Lecture…")
                    sections.isEmpty() -> Text("Synthèse indisponible (station plus ancienne ou déconnectée).")
                    else -> for (section in sections) {
                        Text(section.title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(top = 8.dp))
                        for ((label, value) in section.rows) {
                            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                                Text(label, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2, modifier = Modifier.width(120.dp))
                                Text(value, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                            }
                            HorizontalDivider()
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        dismissButton = { TextButton(onClick = onRefresh) { Text("Actualiser") } },
    )
}
