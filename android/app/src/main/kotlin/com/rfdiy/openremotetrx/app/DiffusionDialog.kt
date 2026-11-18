// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.DiffusionState
import com.rfdiy.openremotetrx.logic.Diffusions

/** Couleur de l'indicateur DIFFUSION : rouge en direct, orange pendant la connexion ou une reprise, gris sinon. */
fun diffusionColor(d: DiffusionState?): Color {
    val ind = Diffusions.indicator(d?.status) ?: return Page.TEXTE_2
    return if (ind.live) Page.TX else Page.ALERTE
}

/**
 * Diffusion en direct (station 0.189.0+, opérateurs ; docs/diffusion-cahier-des-charges.md, lot D4) : état, lancement
 * (canal, durée, voix, informations diffusées, avertissement au premier lancement), arrêt, page des auditeurs et leurs
 * identifiants. Comme la rubrique « Diffusion en direct » de la page ; le module n'agit jamais sur le poste.
 */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun DiffusionDialog(d: DiffusionState, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val st = d.status
    var public by rememberSaveable { mutableStateOf(false) }
    var hours by rememberSaveable { mutableStateOf<Int?>(Diffusions.DEFAULT_HOURS) }
    var hoursMenu by remember { mutableStateOf(false) }
    var voice by rememberSaveable { mutableStateOf(false) }
    val meta = remember { mutableStateListOf<String>().apply { addAll(Diffusions.DEFAULT_META) } }
    var pseudo by rememberSaveable { mutableStateOf("") }
    var indicatif by rememberSaveable { mutableStateOf("") }
    var message by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    var askStop by remember { mutableStateOf(false) }
    var askNew by remember { mutableStateOf(false) }
    val close = { RigHub.diffusionForget(); onDismiss() }
    AlertDialog(
        onDismissRequest = close,
        confirmButton = { TextButton(onClick = close) { Text("Fermer") } },
        title = { Text("Diffusion en direct") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "Faire entendre le son du TRX à quelques internautes sans compte sur la station, par un serveur de " +
                        "diffusion : ils ne joignent jamais la station. Privée par défaut (c'est vous qui transmettez l'adresse et " +
                        "l'identifiant), 1 heure par défaut ; pendant vos émissions, silence sauf si vous cochez « Diffuser aussi ma " +
                        "voix ». Tout opérateur peut arrêter une diffusion ; elle ne reprend jamais seule.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Text(Diffusions.status(st), color = if (st?.active == true) diffusionColor(d) else Page.TEXTE,
                     fontWeight = FontWeight.Bold)
                if (d.notice.isNotEmpty()) Text(d.notice, color = if (d.noticeBad) Page.TX else Page.SUCCES,
                                                style = MaterialTheme.typography.bodySmall)
                val canStart = st != null && st.enabled && st.problem.isNullOrEmpty() && !st.active
                if (canStart) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(!public, onClick = { public = false }); Text("Privée (identifiant et mot de passe)")
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(public, onClick = { public = true }); Text("Publique")
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Durée")
                        Spacer(Modifier.width(8.dp))
                        Box {
                            OutlinedButton(onClick = { hoursMenu = true }) { Text(Diffusions.hoursLabel(hours)) }
                            DropdownMenu(expanded = hoursMenu, onDismissRequest = { hoursMenu = false }) {
                                for (h in Diffusions.HOURS) DropdownMenuItem(text = { Text(Diffusions.hoursLabel(h)) },
                                                                             onClick = { hours = h; hoursMenu = false })
                            }
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AppSwitch(checked = voice, onCheckedChange = { voice = it })
                        Spacer(Modifier.width(8.dp))
                        Text("Diffuser aussi ma voix pendant mes émissions")
                    }
                    Text("Informations diffusées", style = MaterialTheme.typography.titleSmall)
                    FlowRow {
                        for ((key, label) in Diffusions.META) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(key in meta, { on -> if (on) meta.add(key) else meta.remove(key) })
                                Text(label, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    OutlinedTextField(pseudo, { pseudo = it.take(32) }, label = { Text("Pseudo") }, singleLine = true,
                                      modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(indicatif, { indicatif = it.take(16) }, label = { Text("Indicatif") }, singleLine = true,
                                      modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(message, { message = it.take(140) }, label = { Text("Message") },
                                      modifier = Modifier.fillMaxWidth())
                    if (error.isNotEmpty()) Text(error, color = Page.TX, style = MaterialTheme.typography.bodySmall)
                    Button(onClick = {
                        val form = Diffusions.Form(public, hours, voice, Diffusions.META.map { it.first }.filter { it in meta },
                                                   pseudo, indicatif, message)
                        error = Diffusions.formError(form).orEmpty()
                        if (error.isEmpty()) RigHub.diffusionStart(form)
                    }) { Text("Lancer la diffusion") }
                }
                if (st?.active == true) {
                    Button(onClick = { askStop = true },
                           colors = ButtonDefaults.buttonColors(containerColor = Page.TX, contentColor = Color.White)) {
                        Text("Arrêter la diffusion")
                    }
                }
                val page = st?.listenPage
                if (!page.isNullOrEmpty()) {
                    Text("Page des auditeurs", style = MaterialTheme.typography.titleSmall)
                    Text(page, color = Page.MESURE, style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = {
                            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(page))) }
                        }) { Text("Ouvrir") }
                        OutlinedButton(onClick = {
                            val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, page)
                                .putExtra(Intent.EXTRA_SUBJECT, "Écoute en direct")
                            context.startActivity(Intent.createChooser(send, "Envoyer l'adresse"))
                        }) { Text("Partager") }
                        OutlinedButton(onClick = {
                            (context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager)
                                ?.setPrimaryClip(ClipData.newPlainText("Page des auditeurs", page))
                        }) { Text("Copier") }
                    }
                }
                if (st != null && st.enabled) {
                    Text("Auditeurs de la diffusion privée", style = MaterialTheme.typography.titleSmall)
                    Text("Identifiant : " + (d.user ?: "—"), style = MaterialTheme.typography.bodySmall)
                    val password = d.password
                    if (password != null) {
                        Text("Mot de passe : " + password.ifEmpty { "(aucun : généré au premier lancement privé)" },
                             fontWeight = FontWeight.Bold)
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { RigHub.diffusionReveal() }) { Text("Voir le mot de passe") }
                        OutlinedButton(onClick = { askNew = true }) { Text("En générer un") }
                    }
                }
            }
        },
    )
    if (d.confirm) {
        AlertDialog(
            onDismissRequest = { RigHub.diffusionConfirm(false) },
            title = { Text("Avant la première diffusion") },
            text = { Text(Diffusions.WARNING) },
            confirmButton = { TextButton(onClick = { RigHub.diffusionConfirm(true) }) { Text("Continuer") } },
            dismissButton = { TextButton(onClick = { RigHub.diffusionConfirm(false) }) { Text("Annuler") } },
        )
    }
    if (askStop) {
        AlertDialog(
            onDismissRequest = { askStop = false },
            text = { Text("Arrêter la diffusion en direct ?") },
            confirmButton = { TextButton(onClick = { askStop = false; RigHub.diffusionStop() }) { Text("Arrêter") } },
            dismissButton = { TextButton(onClick = { askStop = false }) { Text("Annuler") } },
        )
    }
    if (askNew) {
        AlertDialog(
            onDismissRequest = { askNew = false },
            text = {
                Text("Générer un nouveau mot de passe pour les auditeurs ? L'ancien ne servira plus (ceux qui écoutent ne sont " +
                     "pas coupés) : à retransmettre à vos auditeurs.")
            },
            confirmButton = { TextButton(onClick = { askNew = false; RigHub.diffusionNewPassword() }) { Text("Générer") } },
            dismissButton = { TextButton(onClick = { askNew = false }) { Text("Annuler") } },
        )
    }
}
