// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.PresenceUi

/** Visiteurs (docs/visiteurs-cahier-des-charges.md) : liste des connectés ; « Déconnecter » et « Rouvrir » pour l'opérateur. */
@Composable
fun PresenceDialog(p: PresenceUi, onDismiss: () -> Unit) {
    var confirm by remember { mutableStateOf<PresenceUi.Kick?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Connectés à la station") },
        text = {
            Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for (person in p.people) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(person.text, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                        Text("${person.role} · ${person.since}", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                    }
                }
                for (visitor in p.kick) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(visitor.text, style = MaterialTheme.typography.bodyMedium)
                            Text(visitor.detail, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                        }
                        OutlinedButton(onClick = { confirm = visitor }) { Text("Déconnecter") }
                    }
                }
                val note = p.suspended.ifEmpty { p.grace }.ifEmpty { if (p.people.isEmpty()) "Personne d'autre n'est connecté." else "" }
                if (note.isNotEmpty()) Text(note, color = Page.ALERTE, style = MaterialTheme.typography.bodySmall)
                if (p.canReopen) OutlinedButton(onClick = { RigHub.reopenListeners() }) { Text("Rouvrir l'écoute des visiteurs") }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
    )
    confirm?.let { visitor ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("Déconnecter « ${visitor.text} » ?") },
            text = { Text("Il peut se reconnecter ; pour l'en empêcher, désactive son compte sur la station (TRX Console, menu 20).") },
            confirmButton = { TextButton(onClick = { RigHub.kickListener(visitor.account); confirm = null }) { Text("Déconnecter") } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Annuler") } },
        )
    }
}

/** Commutateur « Écoute des visiteurs » (fin de la rubrique de connexion) ; fermer déconnecte les visiteurs présents. */
@Composable
fun ListenersSwitch(p: PresenceUi) {
    var confirmClose by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = p.switchOn, enabled = p.switchAvailable || p.switchOn, onCheckedChange = { on ->
                if (!on && p.count > 0) confirmClose = true else RigHub.setListenersOpen(on)
            })
            Spacer(Modifier.width(8.dp))
            Text("Écoute des visiteurs (réception seule)", style = MaterialTheme.typography.bodyMedium)
        }
        Text(p.switchNote, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall, modifier = Modifier.fillMaxWidth())
    }
    if (confirmClose) AlertDialog(
        onDismissRequest = { confirmClose = false },
        title = { Text("Fermer l'écoute des visiteurs ?") },
        text = { Text("Les ${p.count} visiteur(s) connecté(s) seront déconnectés.") },
        confirmButton = { TextButton(onClick = { RigHub.setListenersOpen(false); confirmClose = false }) { Text("Fermer l'écoute") } },
        dismissButton = { TextButton(onClick = { confirmClose = false }) { Text("Annuler") } },
    )
}
