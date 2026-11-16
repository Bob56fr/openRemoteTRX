// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.FileProvider
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.Monitoring
import com.rfdiy.openremotetrx.logic.RigState
import java.io.File

/**
 * Monitoring inter-stations (page : rubrique « Monitoring » ; TRX Console : menu 6.5) : AIDER un opérateur en difficulté
 * ou ÊTRE AIDÉ. Mêmes actions et mêmes textes que la page (logic/Monitoring.kt). Le module « monlink » n'agit jamais sur
 * le poste et la station qui aide ne peut que lire et DEMANDER. Plein écran ouvert depuis les Réglages.
 */
@Composable
fun MonitoringScreen(rig: RigState, onClose: () -> Unit) {
    val m = Monitoring.ui(rig.monitoring)
    if (m == null) { LaunchedEffect(Unit) { onClose() }; return }    // station qui ne l'offre plus
    val context = LocalContext.current
    DisposableEffect(Unit) { RigHub.monitoringWatch(true); onDispose { RigHub.monitoringWatch(false) } }
    val ready by RigHub.monitoringReportReady.collectAsState()
    LaunchedEffect(ready) { ready?.let { (name, bytes) -> RigHub.monitoringReportTaken(); shareReport(context, name, bytes) } }
    val links = m.links
    var pseudo by remember(m.pseudo) { mutableStateOf(m.pseudo) }
    var join by remember { mutableStateOf(false) }
    var dialog by remember { mutableStateOf<Pair<String, Monitoring.Link>?>(null) }

    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = Page.FOND) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Monitoring", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    CompactChip("⟳", onClick = { RigHub.monitoringRefresh() })
                    TextButton(onClick = onClose) { Text("Fermer") }
                }
                Text(m.status, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
                if (m.notice.isNotEmpty()) Text(m.notice, color = Page.ALERTE, style = MaterialTheme.typography.bodySmall)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedTextField(pseudo, { pseudo = it.take(16) }, label = { Text("Pseudo") }, singleLine = true, modifier = Modifier.weight(1f))
                    CompactChip("Enregistrer", onClick = { RigHub.monitoringAction("pseudo", mapOf("pseudo" to pseudo.trim())) })
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedButton(onClick = { RigHub.monitoringAction("invite") }) { Text("Aider quelqu'un") }
                    OutlinedButton(onClick = { join = true }) { Text("Être aidé : j'ai un code") }
                }
                if (m.loaded && links.isEmpty()) {
                    Text("Aucune liaison : aidez quelqu'un (code à lui dicter) ou faites-vous aider (code reçu).", color = Page.TEXTE_2)
                }
                for (l in links) LinkCard(l) { action -> onAction(action, l) { dialog = it } }
                Text("La station aidée envoie ce que SON opérateur a choisi, toujours masqué et chiffré par le relais. La station " +
                     "qui aide ne peut que lire et demander ; rien ne commande le poste.", style = MaterialTheme.typography.bodySmall,
                     color = Page.TEXTE_2)
            }
        }
    }

    m.code?.let { code ->
        AlertDialog(onDismissRequest = { RigHub.monitoringDismiss() }, title = { Text("Aider quelqu'un") },
            text = {
                Column {
                    Text(code, fontSize = 30.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                    Text("Dictez ce code à l'opérateur que vous aidez (valable 15 minutes, une seule fois). Quand il l'a tapé, " +
                         "sa station apparaît ici : comparez alors les 6 chiffres de l'empreinte.")
                }
            }, confirmButton = { TextButton(onClick = { RigHub.monitoringDismiss() }) { Text("Fermer") } })
    }
    if (join) JoinDialog { join = false }
    m.joined?.let { link -> FingerprintDialog(link) { RigHub.monitoringDismiss() } }
    m.events?.let { list ->
        AlertDialog(onDismissRequest = { RigHub.monitoringDismiss() }, title = { Text("Derniers événements") },
            text = { Column { if (list.isEmpty()) Text("Aucun événement reçu.") else list.forEach { Text(it, style = MaterialTheme.typography.bodySmall) } } },
            confirmButton = { TextButton(onClick = { RigHub.monitoringDismiss() }) { Text("Fermer") } })
    }
    dialog?.let { (kind, link) ->
        val close = { dialog = null }
        when (kind) {
            "fingerprint" -> FingerprintDialog(link, close)
            "assist" -> AssistDialog(link, close)
            "answer" -> AnswerDialog(link, close)
            "profile" -> ProfileDialog(link, close)
            "end" -> EndDialog(link, close)
        }
    }
}

private fun onAction(action: String, l: Monitoring.Link, open: (Pair<String, Monitoring.Link>) -> Unit) {
    when (action) {
        "fingerprint", "assist", "answer", "profile", "end" -> open(action to l)
        "events" -> RigHub.monitoringEvents(l.peer)
        "report" -> RigHub.monitoringAction("request_report", mapOf("peer" to l.peer))
        "download" -> RigHub.monitoringReport(l.peer)
        "send_report" -> RigHub.monitoringAction("send_report", mapOf("peer" to l.peer))
        "pause", "resume" -> RigHub.monitoringAction("pause", mapOf("peer" to l.peer, "paused" to (action == "pause")))
    }
}

private val LABELS = mapOf(
    "fingerprint" to "Comparer l'empreinte", "assist" to "Demander l'assistance", "report" to "Demander le rapport",
    "download" to "Télécharger le rapport", "answer" to "Répondre à la demande", "send_report" to "Envoyer mon rapport",
    "profile" to "Ce qui est envoyé", "pause" to "Pause", "resume" to "Reprendre", "end" to "Terminer", "events" to "Événements",
)

@Composable
private fun LinkCard(l: Monitoring.Link, onAction: (String) -> Unit) {
    val bar = when (l.level) { "warn" -> Page.ALERTE; "ok" -> Page.SUCCES; else -> Page.LIGNE }
    Row(Modifier.fillMaxWidth().background(Page.CHAMP)) {
        Column(Modifier.width(4.dp).background(bar)) { Text("") }
        Column(Modifier.padding(8.dp).weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(l.title, fontWeight = FontWeight.SemiBold)
            if (l.details.isNotEmpty()) Text(l.details.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            for (line in l.stationLines) Text(line, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            val actions = if (l.role == "receiver" && l.state != "confirm") listOf("events") + l.actions else l.actions
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (a in actions.take(3)) CompactChip(LABELS[a] ?: a, onClick = { onAction(a) })
            }
            if (actions.size > 3) Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (a in actions.drop(3)) CompactChip(LABELS[a] ?: a, onClick = { onAction(a) })
            }
        }
    }
}

@Composable
private fun ProfileChoice(onChange: (Map<String, Any>) -> Unit) {
    var choice by remember { mutableStateOf("diagnostic") }
    var freq by remember { mutableStateOf(false) }
    LaunchedEffect(choice, freq) { onChange(Monitoring.profileMap(choice, freq)) }
    Column {
        for ((key, label, _) in Monitoring.PROFILES) Row(verticalAlignment = Alignment.CenterVertically) {
            RadioButton(choice == key, onClick = { choice = key }); Text(label, style = MaterialTheme.typography.bodySmall)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(freq, onCheckedChange = { freq = it }); Text("Envoyer aussi la fréquence et le mode du poste", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun FingerprintDialog(link: Monitoring.Link, onClose: () -> Unit) {
    var profile by remember { mutableStateOf(Monitoring.profileMap("diagnostic", false)) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Empreinte de la liaison avec ${link.pseudo}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(link.fingerprint.ifEmpty { "?" }, fontSize = 30.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                Text("Comparez ces 6 chiffres avec ceux de votre correspondant, de vive voix ou par message.")
                if (link.role == "emitter") {
                    Text("Si les chiffres sont les mêmes, choisissez ce que vous envoyez (rien ne part avant) :")
                    ProfileChoice { profile = it }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                RigHub.monitoringAction("confirm", buildMap {
                    put("peer", link.peer)
                    if (link.role == "emitter") put("profile", profile)
                })
                onClose()
            }) { Text("Mêmes chiffres : confirmer") }
        },
        dismissButton = {
            TextButton(onClick = { RigHub.monitoringAction("end", mapOf("peer" to link.peer)); onClose() }) { Text("Chiffres différents : refuser") }
        })
}

@Composable
private fun JoinDialog(onClose: () -> Unit) {
    var code by remember { mutableStateOf("") }
    val ok = Monitoring.normalizeCode(code)
    AlertDialog(onDismissRequest = onClose, title = { Text("Être aidé") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("La station qui vous aide recevra ce que VOUS choisissez (santé de la machine, état du poste, codes d'erreur), " +
                     "toujours masqué. Elle ne pourra RIEN commander. Vous pourrez tout arrêter à tout moment.")
                OutlinedTextField(code, { code = it.take(16) }, label = { Text("Code dicté par la personne qui vous aide") }, singleLine = true)
            }
        },
        confirmButton = { TextButton(enabled = ok != null, onClick = { RigHub.monitoringAction("join", mapOf("code" to ok)); onClose() }) { Text("Rejoindre") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } })
}

@Composable
private fun AssistDialog(link: Monitoring.Link, onClose: () -> Unit) {
    var hours by remember { mutableStateOf(2) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Demander le mode assistance") },
        text = {
            Column {
                Text("Nouvelles toutes les 30 secondes et tous les événements, pendant la durée choisie. L'opérateur aidé doit l'accepter.")
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    for (h in Monitoring.HOURS) CompactChip("$h h", onClick = { hours = h }, selected = hours == h)
                }
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.monitoringAction("request_assist", mapOf("peer" to link.peer, "duration_s" to hours * 3600)); onClose() }) { Text("Demander") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } })
}

@Composable
private fun AnswerDialog(link: Monitoring.Link, onClose: () -> Unit) {
    val req = link.requestText
    if (req == null) { LaunchedEffect(Unit) { onClose() }; return }
    AlertDialog(onDismissRequest = onClose, title = { Text("Demande de ${link.pseudo}") },
        text = { Text(req) },
        confirmButton = { TextButton(onClick = { RigHub.monitoringAction("answer", mapOf("peer" to link.peer, "accept" to true)); onClose() }) { Text("Accepter") } },
        dismissButton = { TextButton(onClick = { RigHub.monitoringAction("answer", mapOf("peer" to link.peer, "accept" to false)); onClose() }) { Text("Refuser") } })
}

@Composable
private fun ProfileDialog(link: Monitoring.Link, onClose: () -> Unit) {
    var profile by remember { mutableStateOf(Monitoring.profileMap("diagnostic", false)) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Ce que vous envoyez à ${link.pseudo}") },
        text = { ProfileChoice { profile = it } },
        confirmButton = { TextButton(onClick = { RigHub.monitoringAction("profile", mapOf("peer" to link.peer, "profile" to profile)); onClose() }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } })
}

@Composable
private fun EndDialog(link: Monitoring.Link, onClose: () -> Unit) {
    var purge by remember { mutableStateOf(true) }
    AlertDialog(onDismissRequest = onClose, title = { Text("Terminer la liaison") },
        text = {
            Column {
                Text("Terminer la liaison avec ${link.pseudo} ? Immédiat ; la reprendre demandera un nouveau code.")
                if (link.role == "receiver") Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(purge, onCheckedChange = { purge = it }); Text("Effacer aussi ce qui a été reçu de cette station")
                }
            }
        },
        confirmButton = { TextButton(onClick = { RigHub.monitoringAction("end", mapOf("peer" to link.peer, "purge" to (link.role == "receiver" && purge))); onClose() }) { Text("Terminer") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } })
}

/** Rapport de dépannage reçu : partagé par les applications du téléphone (courriel, messagerie, fichiers). */
private fun shareReport(context: Context, name: String, bytes: ByteArray) {
    val dir = File(context.cacheDir, "monitoring").apply { mkdirs() }
    dir.listFiles()?.forEach { it.delete() }                       // un seul rapport gardé
    val file = File(dir, name.replace(Regex("[^\\w.-]"), "_"))
    file.writeBytes(bytes)
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
    val send = Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM, uri)
        .putExtra(Intent.EXTRA_SUBJECT, "Rapport de dépannage OpenRemoteTRX").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, "Ouvrir ou envoyer le rapport"))
}
