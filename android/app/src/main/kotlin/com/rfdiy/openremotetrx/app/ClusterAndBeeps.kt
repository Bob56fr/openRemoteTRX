// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.LinkSounds
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.BeepSettings
import com.rfdiy.openremotetrx.logic.MicProfiles
import com.rfdiy.openremotetrx.logic.Spot
import com.rfdiy.openremotetrx.logic.Spots
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val HOUR = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault())

/**
 * « Tout afficher » de la rubrique Cluster DX : les 30 derniers spots, le plus récent en tête (heure locale, indicatif,
 * fréquence, source). La station n'envoie les spots qu'aux clients qui regardent le spectre : la liste s'y abonne
 * le temps d'être ouverte. Toucher un spot = QSY (en réception).
 */
@Composable
fun RecentSpotsDialog(recentSpots: List<Spot>, bandSpots: List<Spot>, hasSpectrum: Boolean, canSet: Boolean, onDismiss: () -> Unit) {
    DisposableEffect(Unit) {
        RigHub.watchSpectrum(true)
        onDispose { RigHub.watchSpectrum(false) }
    }
    // Station 0.56.0+ : derniers spots toutes bandes ; plus ancienne : ceux de la bande du poste seulement
    val recent = recentSpots.ifEmpty { Spots.recent(bandSpots) }
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        title = { Text("Derniers spots (${recent.size})") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                when {
                    !hasSpectrum -> Text("Cette station n'envoie les spots qu'avec le spectre HF (second port CI-V).", style = MaterialTheme.typography.bodySmall)
                    recent.isEmpty() -> Text("Aucun spot actif pour l'instant (spots de moins de 15 min).", style = MaterialTheme.typography.bodySmall)
                }
                for (s in recent) {
                    Row(
                        Modifier.fillMaxWidth().clickable(enabled = canSet) { RigHub.qsySpot(s.id); onDismiss() }.padding(vertical = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(HOUR.format(Instant.ofEpochMilli(Spots.arrivalMs(s))), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                        Text(s.dx, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        Text(String.format(Locale.ROOT, "%.1f", s.khz), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                    }
                    Text(
                        Spots.sourceLabel(s) + " · " + Spots.modeLabel(s) + if (s.comment.isNotEmpty()) " · " + s.comment else "",
                        color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        },
    )
}

/**
 * Bips de fin d'émission (page : « beeps-box ») : produits et ÉMIS par la station, réglage commun à tous les appareils.
 * Le bip de liaison perdue est une émission automatique : confirmation avant de l'activer.
 */
@Composable
fun BeepsSection(beeps: BeepSettings?, connected: Boolean) {
    val context = LocalContext.current
    val sounds = remember { LinkSounds(context) }
    var confirmLost by remember { mutableStateOf(false) }
    Text("Bips de fin d'émission", style = MaterialTheme.typography.titleSmall)
    if (beeps == null) {
        if (connected) Text("Cette station ne propose pas les bips de fin.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        return
    }
    Text("Produits et ÉMIS par la station ; réglage commun à tous les appareils.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = beeps.rogerEnabled, enabled = connected, onCheckedChange = { RigHub.setBeep("roger_enabled", it) })
        Spacer(Modifier.width(8.dp))
        Text("Roger bip quand je relâche le PTT", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        TextButton(onClick = { sounds.playSequence(beeps.rogerSequence) }) { Text("Écouter") }
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (t in beeps.tones) {
            CompactChip(BeepSettings.toneLabel(t), onClick = { RigHub.setBeep("roger_tone", t) }, enabled = connected, selected = t == beeps.tone)
        }
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        for (n in beeps.patterns) {
            CompactChip(BeepSettings.patternLabel(n), onClick = { RigHub.setBeep("roger_pattern", n) }, enabled = connected, selected = n == beeps.pattern)
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = beeps.linkLostEnabled, enabled = connected, onCheckedChange = { on ->
            if (on) confirmLost = true else RigHub.setBeep("link_lost_enabled", false)
        })
        Spacer(Modifier.width(8.dp))
        Text("Bip de liaison perdue (émis si la liaison tombe pendant mon émission)", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        TextButton(onClick = { sounds.playSequence(beeps.linkLostSequence) }) { Text("Écouter") }
    }
    if (beeps.linkLostEnabled) {
        Text(
            "Bip de liaison perdue ACTIF : si la liaison tombe pendant votre émission, la station émet trois tons descendants " +
                "avant de couper (émission automatique, sous votre responsabilité).",
            color = Page.ALERTE, style = MaterialTheme.typography.bodySmall,
        )
    }
    if (confirmLost) AlertDialog(
        onDismissRequest = { confirmLost = false },
        title = { Text("Bip de liaison perdue") },
        text = {
            Text(
                "Ce bip est ÉMIS par la station quand la liaison avec ce téléphone tombe pendant votre émission : " +
                    "une émission automatique de 0,4 s, sous votre responsabilité. L'activer ?"
            )
        },
        confirmButton = { TextButton(onClick = { confirmLost = false; RigHub.setBeep("link_lost_enabled", true) }) { Text("Activer") } },
        dismissButton = { TextButton(onClick = { confirmLost = false }) { Text("Annuler") } },
    )
}

/** Réglages du casque et du volant (téléphone seulement, désactivés par défaut). */
@Composable
fun HeadsetSection(headsetMicState: String) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences(RigHub.PREFS, android.content.Context.MODE_PRIVATE) }
    var mediaPtt by remember { mutableStateOf(prefs.getBoolean(RigHub.PREF_MEDIA_PTT, false)) }
    var headsetMic by remember { mutableStateOf(prefs.getBoolean(RigHub.PREF_HEADSET_MIC, false)) }
    Text("Casque et volant", style = MaterialTheme.typography.titleSmall)
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = mediaPtt, onCheckedChange = {
            mediaPtt = it
            prefs.edit().putBoolean(RigHub.PREF_MEDIA_PTT, it).apply()
            RigHub.mediaButtonsChanged()
        })
        Spacer(Modifier.width(8.dp))
        Column {
            Text("PTT par le bouton du casque ou les touches du volant (Lecture/Pause)", style = MaterialTheme.typography.bodyMedium)
            Text(
                "Appui = prise ou fin d'émission, jamais un maintien ; « Émission autorisée » reste exigée ; " +
                    "la lecture automatique à la connexion d'un casque est ignorée.",
                color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
            )
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Switch(checked = headsetMic, onCheckedChange = {
            headsetMic = it
            prefs.edit().putBoolean(RigHub.PREF_HEADSET_MIC, it).apply()
        })
        Spacer(Modifier.width(8.dp))
        Column {
            Text("Micro du casque Bluetooth", style = MaterialTheme.typography.bodyMedium)
            Text(
                headsetMicState.ifEmpty { "Son en qualité téléphone dans le casque. Prend effet à la prochaine connexion." },
                color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/** Micro : environnement (traitements d'écho et de bruit), comme la page ; pris en compte à la connexion suivante. */
@Composable
fun MicSection() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences(RigHub.PREFS, android.content.Context.MODE_PRIVATE) }
    var profile by remember { mutableStateOf(prefs.getString(RigHub.PREF_MIC_PROFILE, MicProfiles.DEFAULT) ?: MicProfiles.DEFAULT) }
    var echo by remember { mutableStateOf(prefs.getBoolean(RigHub.PREF_MIC_ECHO, true)) }
    var noise by remember { mutableStateOf(prefs.getBoolean(RigHub.PREF_MIC_NOISE, false)) }
    Text("Micro : environnement", style = MaterialTheme.typography.titleSmall)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (p in MicProfiles.ALL) {
            CompactChip(p.label, onClick = { profile = p.key; prefs.edit().putString(RigHub.PREF_MIC_PROFILE, p.key).apply() }, selected = p.key == profile)
        }
    }
    if (profile == "custom") {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = echo, onCheckedChange = { echo = it; prefs.edit().putBoolean(RigHub.PREF_MIC_ECHO, it).apply() })
            Spacer(Modifier.width(8.dp))
            Text("Annulation d'écho", style = MaterialTheme.typography.bodyMedium)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = noise, onCheckedChange = { noise = it; prefs.edit().putBoolean(RigHub.PREF_MIC_NOISE, it).apply() })
            Spacer(Modifier.width(8.dp))
            Text("Réduction de bruit", style = MaterialTheme.typography.bodyMedium)
        }
    }
    Text(
        "Coupures de la voix en émission : essayez « pièce calme » ou un profil « micro-casque » (réduction de bruit coupée). " +
            "Pris en compte à la prochaine connexion.",
        color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
    )
}
