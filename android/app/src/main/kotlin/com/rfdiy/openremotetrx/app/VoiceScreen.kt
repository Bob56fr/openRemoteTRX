// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.VoiceHub
import com.rfdiy.openremotetrx.logic.ScramblerSettings
import com.rfdiy.openremotetrx.logic.Scramblers
import com.rfdiy.openremotetrx.logic.VoiceEq
import com.rfdiy.openremotetrx.logic.VoiceSettings
import java.util.Locale
import kotlin.math.roundToInt

private val WARN = Page.ALERTE

/**
 * Onglet « Égaliseur » (docs/egaliseur-voix.md) : mêmes réglages que la page, enregistrés sur le téléphone, appliqués
 * tout de suite à la voix envoyée en émission. Limiteur toujours actif ; effets déconseillés en BLU.
 */
@Composable
fun VoiceTab(transmitting: Boolean, panel: @Composable (@Composable ColumnScope.() -> Unit) -> Unit) {
    val context = LocalContext.current
    val ui by VoiceHub.ui.collectAsState()
    val s = ui.settings
    LaunchedEffect(Unit) { VoiceHub.load(context) }                 // réglages enregistrés, même avant la connexion
    fun save(next: VoiceSettings) = VoiceHub.save(context, next)
    fun say(text: String?) { text?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() } }

    val exporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        runCatching { context.contentResolver.openOutputStream(uri)?.use { it.write(VoiceEq.exportJson(s).toByteArray()) } }
            .onSuccess { say("Réglages exportés.") }.onFailure { say("Export impossible : ${it.message}") }
    }
    val importer = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        runCatching {
            val text = context.contentResolver.openInputStream(uri)?.use { it.readBytes().decodeToString() } ?: error("fichier illisible")
            require(text.length < 64_000) { "fichier trop gros" }
            VoiceEq.importJson(text)
        }.onSuccess { save(it); say("Réglages importés.") }.onFailure { say("Import refusé : ${it.message}") }
    }

    panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = s.enabled, onCheckedChange = { save(s.copy(enabled = it)) })
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text("Égaliseur et effets de voix", style = MaterialTheme.typography.titleSmall)
                Text(
                    if (s.enabled) "Allumé : appliqué à votre voix en émission." else "Éteint : voix envoyée telle quelle (limiteur seul).",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((_, preset) in VoiceEq.PRESETS) CompactChip(preset.first, onClick = { save(preset.second().copy(mic = s.mic)) })
        }
        if (ui.failed.isNotEmpty()) Text(ui.failed, color = WARN, style = MaterialTheme.typography.bodySmall)
        Text(
            "Limiteur toujours actif (crêtes à ${VoiceEq.LIMIT_DBFS.toInt()} dBFS). Vérifiez l'ALC sur charge fictive après un réglage.",
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
    }

    panel {
        Text("Micro", style = MaterialTheme.typography.titleSmall)
        Text(
            if (ui.live) "Niveau : ${dbText(ui.micLevelDb)}" else "Niveau affiché pendant un enregistrement (ci-dessous) ou une émission.",
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
        SliderRow("Gain", s.mic.gainDb, -12.0..20.0, 0.5, "dB") { save(s.copy(mic = s.mic.copy(gainDb = it))) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = s.mic.gateOn, onCheckedChange = { save(s.copy(mic = s.mic.copy(gateOn = it))) })
            Spacer(Modifier.width(8.dp))
            Text("Porte de bruit (atténue de 30 dB sous le seuil, jamais muette)", style = MaterialTheme.typography.bodyMedium)
        }
        if (s.mic.gateOn) SliderRow("Seuil", s.mic.gateDb, -80.0..-20.0, 1.0, "dBFS") { save(s.copy(mic = s.mic.copy(gateDb = it))) }
    }

    panel {
        Text("Filtres et égaliseur 10 bandes", style = MaterialTheme.typography.titleSmall)
        SliderRow("Coupe-bas", s.highpassHz, 20.0..1000.0, 10.0, "Hz") { save(s.copy(highpassHz = it)) }
        SliderRow("Coupe-haut", s.lowpassHz, 1500.0..8000.0, 50.0, "Hz") { save(s.copy(lowpassHz = it)) }
        var details by remember { mutableStateOf(false) }
        s.bands.forEachIndexed { i, b ->
            val name = (if (b.hz >= 1000) String.format(Locale.FRANCE, "%.2f kHz", b.hz / 1000) else "${b.hz.roundToInt()} Hz") +
                if (b.shelf) " (plateau)" else ""
            SliderRow(name, b.gainDb, -VoiceEq.GAIN_MAX_DB..VoiceEq.GAIN_MAX_DB, 0.5, "dB") { v ->
                save(s.copy(bands = s.bands.mapIndexed { j, x -> if (j == i) x.copy(gainDb = v) else x }))
            }
            if (details) {
                val base = VoiceEq.BANDS_HZ[i]
                SliderRow("   fréquence", b.hz, base / 1.5..base * 1.5, 5.0, "Hz") { v ->
                    save(s.copy(bands = s.bands.mapIndexed { j, x -> if (j == i) x.copy(hz = v) else x }))
                }
                SliderRow("   largeur Q", b.q, VoiceEq.Q_MIN..VoiceEq.Q_MAX, 0.1, "") { v ->
                    save(s.copy(bands = s.bands.mapIndexed { j, x -> if (j == i) x.copy(q = v) else x }))
                }
            }
        }
        TextButton(onClick = { details = !details }) { Text(if (details) "Masquer fréquence et Q" else "Fréquence et Q de chaque bande") }
    }

    panel {
        Text("Chorus et réverbération", style = MaterialTheme.typography.titleSmall)
        Text("Déconseillés en BLU : ils réduisent la compréhension. Coupés net à la fin de chaque émission.",
            color = WARN, style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = s.chorus.on, onCheckedChange = { save(s.copy(chorus = s.chorus.copy(on = it))) })
            Spacer(Modifier.width(8.dp))
            Text("Chorus", style = MaterialTheme.typography.bodyMedium)
        }
        if (s.chorus.on) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((key, t) in VoiceEq.CHORUS_TYPES) CompactChip(t.label, onClick = { save(s.copy(chorus = s.chorus.copy(type = key))) }, selected = s.chorus.type == key)
            }
            SliderRow("Dosage", s.chorus.mix, 0.0..100.0, 5.0, "%") { save(s.copy(chorus = s.chorus.copy(mix = it))) }
            SliderRow("Vitesse", s.chorus.rateHz, 0.1..5.0, 0.1, "Hz") { save(s.copy(chorus = s.chorus.copy(rateHz = it))) }
            SliderRow("Profondeur", s.chorus.depthMs, 0.5..8.0, 0.5, "ms") { save(s.copy(chorus = s.chorus.copy(depthMs = it))) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = s.reverb.on, onCheckedChange = { save(s.copy(reverb = s.reverb.copy(on = it))) })
            Spacer(Modifier.width(8.dp))
            Text("Réverbération", style = MaterialTheme.typography.bodyMedium)
        }
        if (s.reverb.on) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((key, t) in VoiceEq.REVERB_TYPES) CompactChip(t.label, onClick = {
                    save(s.copy(reverb = s.reverb.copy(type = key, seconds = t.seconds)))
                }, selected = s.reverb.type == key)
            }
            SliderRow("Dosage", s.reverb.mix, 0.0..100.0, 5.0, "%") { save(s.copy(reverb = s.reverb.copy(mix = it))) }
            SliderRow("Durée", s.reverb.seconds, 0.2..4.0, 0.1, "s") { save(s.copy(reverb = s.reverb.copy(seconds = it))) }
        }
    }

    panel {
        Text("S'écouter sans émettre", style = MaterialTheme.typography.titleSmall)
        Text(
            "Enregistrez quelques secondes (30 s au plus), puis relisez-les avec les réglages en cours, modifiables pendant " +
                "la relecture. Jamais envoyé à la station ; impossible pendant une émission (toute prise l'arrête). Casque conseillé.",
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { if (ui.recording) VoiceHub.stopRecording() else say(VoiceHub.startRecording()) }, enabled = !transmitting) {
                Text(if (ui.recording) "Arrêter (${ui.recordedS.roundToInt()} s)" else "Enregistrer")
            }
            OutlinedButton(onClick = { if (ui.playing) VoiceHub.stopPlayback() else say(VoiceHub.play()) },
                enabled = !transmitting && !ui.recording && ui.recordedS > 0) {
                Text(if (ui.playing) "Arrêter la relecture" else "Relire" + if (ui.recordedS > 0) " (${ui.recordedS.roundToInt()} s)" else "")
            }
        }
    }

    if (BuildConfig.SCRAMBLER) ScramblerPanel(ui.scrambler, panel)   // absent de la version Google Play

    panel {
        Text("Partager les réglages", style = MaterialTheme.typography.titleSmall)
        Text("Format commun avec la page web : la même voix sur le PC et le téléphone.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { exporter.launch("voix-openremotetrx.json") }) { Text("Exporter") }
            OutlinedButton(onClick = { importer.launch(arrayOf("application/json", "text/plain", "*/*")) }) { Text("Importer") }
            TextButton(onClick = { save(VoiceSettings()) }) { Text("Réinitialiser") }
        }
    }
}

private fun dbText(db: Double) = if (db <= -119) "—" else "${db.roundToInt()} dBFS"

/** Curseur avec sa valeur ; la valeur n'est enregistrée qu'au relâchement (pas d'écriture à chaque pixel). */
@Composable
private fun SliderRow(label: String, value: Double, range: ClosedFloatingPointRange<Double>, step: Double, unit: String, onDone: (Double) -> Unit) {
    var drag by remember { mutableStateOf<Float?>(null) }
    val shown = drag ?: value.toFloat()
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(96.dp))
        Slider(
            value = shown, onValueChange = { drag = it },
            onValueChangeFinished = { drag?.let { v -> onDone((Math.round(v / step) * step).coerceIn(range.start, range.endInclusive)) }; drag = null },
            valueRange = range.start.toFloat()..range.endInclusive.toFloat(), modifier = Modifier.weight(1f),
        )
        val v = Math.round(shown / step) * step
        Text(
            (if (step < 1) String.format(Locale.FRANCE, "%.1f", v) else v.roundToInt().toString()) + if (unit.isNotEmpty()) " $unit" else "",
            style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(64.dp),
        )
    }
}

/** Texte montré avant toute mise en service (décision de l'utilisateur du 2026-10-29 : message clair et confirmation). */
const val SCRAMBLER_WARNING = "Le scrambler rend votre voix incompréhensible pour qui n'a pas le même réglage. Ce n'est PAS un " +
    "chiffrement : tout possesseur d'un scrambler identique vous entend.\n\nEn bandes radioamateur, le Règlement des " +
    "radiocommunications (UIT, art. 25) et la réglementation nationale interdisent les émissions destinées à masquer le sens " +
    "des messages. Vous en prenez l'ENTIÈRE responsabilité."

/** Rubrique « Scrambler » : brouiller l'émission, débrouiller la réception, mode commun avec la page, décalage fin. */
@Composable
private fun ScramblerPanel(scr: ScramblerSettings, panel: @Composable (@Composable ColumnScope.() -> Unit) -> Unit) {
    val context = LocalContext.current
    var asking by remember { mutableStateOf<ScramblerSettings?>(null) }
    fun change(next: ScramblerSettings) {
        if ((next.tx && !scr.tx) || (next.rx && !scr.rx)) asking = next else VoiceHub.setScrambler(context, next)
    }
    panel {
        Text("Scrambler (voix brouillée)", style = MaterialTheme.typography.titleSmall)
        Text("Désactivé à chaque démarrage. Même mode des deux côtés ; retard ajouté : environ 43 ms. Les tonalités SELCALL et les " +
            "bips de la station ne sont pas brouillés.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = scr.tx, onCheckedChange = { change(scr.copy(tx = it)) })
            Spacer(Modifier.width(8.dp))
            Text("Brouiller mon émission", style = MaterialTheme.typography.bodyMedium, color = if (scr.tx) WARN else Page.TEXTE)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = scr.rx, onCheckedChange = { change(scr.copy(rx = it)) })
            Spacer(Modifier.width(8.dp))
            Text("Débrouiller la réception", style = MaterialTheme.typography.bodyMedium)
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((key, m) in Scramblers.MODES) CompactChip(m.label, onClick = { VoiceHub.setScrambler(context, scr.copy(mode = key)) }, selected = scr.mode == key)
        }
        SliderRow("Décalage fin", scr.offsetHz.toDouble(), -Scramblers.OFFSET_MAX_HZ.toDouble()..Scramblers.OFFSET_MAX_HZ.toDouble(), 5.0, "Hz") {
            VoiceHub.setScrambler(context, scr.copy(offsetHz = it.roundToInt()))
        }
        Text("Réception BLU encore brouillée : ajustez le décalage fin (ou le RIT du poste). Essai sans émettre : « Relire » "+
            "(ci-dessus) fait entendre votre voix brouillée ; avec « Débrouiller » aussi, elle doit redevenir claire.",
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
    }
    asking?.let { next ->
        AlertDialog(
            onDismissRequest = { asking = null },
            title = { Text(if (next.tx && !scr.tx) "Brouiller votre émission ?" else "Débrouiller la réception ?") },
            text = { Text(SCRAMBLER_WARNING) },
            confirmButton = { TextButton(onClick = { VoiceHub.setScrambler(context, next); asking = null }) { Text("J'ai compris, activer") } },
            dismissButton = { TextButton(onClick = { asking = null }) { Text("Annuler") } },
        )
    }
}

