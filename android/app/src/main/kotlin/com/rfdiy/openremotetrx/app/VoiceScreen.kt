// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.height
import androidx.compose.material3.OutlinedTextField
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.VoiceProfile
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import com.rfdiy.openremotetrx.logic.Tr
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.VoiceEq
import com.rfdiy.openremotetrx.logic.VoiceSettings
import kotlin.math.roundToInt

private val WARN = Page.ALERTE

/**
 * Onglet « Audio » (ex « Égaliseur », docs/egaliseur-voix.md) : mêmes réglages que la page, enregistrés sur le téléphone, appliqués
 * tout de suite à la voix envoyée en émission. Limiteur toujours actif ; effets déconseillés en BLU.
 */
@Composable
fun VoiceTab(
    transmitting: Boolean,
    profiles: List<VoiceProfile>? = null,
    /** Rediffusion accordée par la station ; `canBroadcast` = émission autorisée et possible (armé, micro, liaison). */
    replayAllowed: Boolean = false,
    canBroadcast: Boolean = false,
    onBroadcast: () -> Unit = {},
    /** Bips de fin d'émission (réglage de la STATION, déplacé des Réglages à l'étape 300) ; `beepsConnected` : modifiables. */
    beeps: com.rfdiy.openremotetrx.logic.BeepSettings? = null,
    beepsConnected: Boolean = false,
    panel: @Composable (@Composable ColumnScope.() -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val ui by VoiceHub.ui.collectAsState()
    val s = ui.settings
    LaunchedEffect(Unit) { VoiceHub.load(context) }                 // réglages enregistrés, même avant la connexion
    fun save(next: VoiceSettings) = VoiceHub.save(context, next)
    fun say(text: String?) { text?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() } }

    val exporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        runCatching { context.contentResolver.openOutputStream(uri)?.use { it.write(VoiceEq.exportJson(s).toByteArray()) } }
            .onSuccess { say(Tr.t("voicescreen.exported")) }.onFailure { say(Tr.t("voicescreen.export_failed", "error" to "${it.message}")) }
    }
    val importer = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        runCatching {
            val text = context.contentResolver.openInputStream(uri)?.use { it.readBytes().decodeToString() } ?: error(Tr.t("voicescreen.file_unreadable"))
            require(text.length < 64_000) { Tr.t("voicescreen.file_too_big") }
            VoiceEq.importJson(text)
        }.onSuccess { save(it); say(Tr.t("voicescreen.imported")) }.onFailure { say(Tr.t("voicescreen.import_refused", "error" to "${it.message}")) }
    }

    var naming by remember { mutableStateOf<String?>(null) }       // nom du profil à enregistrer (fenêtre ouverte)
    var deleting by remember { mutableStateOf<String?>(null) }
    naming?.let { name ->
        AlertDialog(
            onDismissRequest = { naming = null },
            title = { Text(Tr.t("voicescreen.save_profile_title")) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(Tr.t("voicescreen.save_profile_hint"),
                        style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(value = name, onValueChange = { naming = it.take(32) }, singleLine = true, label = { Text(Tr.t("voicescreen.profile_name")) })
                }
            },
            confirmButton = {
                TextButton(onClick = { RigHub.saveVoiceProfile(name, s); naming = null },
                    enabled = name.isNotBlank()) { Text(Tr.t("common.save")) }
            },
            dismissButton = { TextButton(onClick = { naming = null }) { Text(Tr.t("common.cancel")) } },
        )
    }
    deleting?.let { name ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text(Tr.t("voicescreen.delete_profile_title", "name" to name)) },
            text = { Text(Tr.t("voicescreen.delete_profile_hint")) },
            confirmButton = { TextButton(onClick = { RigHub.deleteVoiceProfile(name); deleting = null }) { Text(Tr.t("common.delete")) } },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(Tr.t("common.cancel")) } },
        )
    }

    // Voix par Breizh Audio Box : égaliseur et effets contournés par le traitement => leurs commandes sont grisées (réglages
    // gardés pour le retour en direct : « Direct » ou repli) ; gain du micro et porte de bruit restent actifs
    val fx = !ui.breizh
    // « Fonctionnalités mobiles » (étape 300) : rubriques masquables, jamais une fonction en service ; micro toujours visible
    val eqShown = Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.EQ, s.enabled)
    val fxShown = Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.CHORUS_REVERB, s.chorus.on || s.reverb.on)
    if (eqShown || fxShown) panel {
        if (ui.breizh) Text(Tr.t("voicescreen.breizh_bypass"),
            color = WARN, style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppSwitch(checked = s.enabled && fx, onCheckedChange = { save(s.copy(enabled = it)) }, enabled = fx)
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(Tr.t("voicescreen.eq_title"), style = MaterialTheme.typography.titleSmall)
                Text(
                    when {
                        !fx -> Tr.t("voicescreen.eq_breizh")
                        s.enabled -> Tr.t("voicescreen.eq_on")
                        else -> Tr.t("voicescreen.eq_off")
                    },
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((_, preset) in VoiceEq.PRESETS) CompactChip(preset.first, onClick = { save(preset.second().copy(mic = s.mic)) }, enabled = fx)
            // Profils de l'opérateur rangés sur la station, après les trois préréglages ; appui long = supprimer
            for (p in profiles.orEmpty()) CompactChip("★ " + p.name, onClick = { save(p.voiceSettings()); say(Tr.t("voicescreen.profile_applied", "name" to p.name)) },
                onLongClick = { deleting = p.name }, enabled = fx)
        }
        if (profiles != null) {
            TextButton(onClick = { naming = "" }) { Text(Tr.t("voicescreen.save_profile")) }
        }
        // Graphique de l'égaliseur : courbe de toute la chaîne (chaud = renforcé, froid = atténué) et conseils
        VoiceGraph(s)
        for (hint in VoiceEq.hints(s)) Text("• " + hint, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        if (ui.failed.isNotEmpty()) Text(ui.failed, color = WARN, style = MaterialTheme.typography.bodySmall)
        Text(
            Tr.t("voicescreen.limiter", "limit" to VoiceEq.LIMIT_DBFS.toInt()),
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
    }

    panel {
        Text(Tr.t("voicescreen.mic"), style = MaterialTheme.typography.titleSmall)
        Text(
            if (ui.live) Tr.t("voicescreen.mic_level", "level" to dbText(ui.micLevelDb)) else Tr.t("voicescreen.mic_level_hint"),
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
        SliderRow(Tr.t("voicescreen.gain"), s.mic.gainDb, -12.0..20.0, 0.5, "dB") { save(s.copy(mic = s.mic.copy(gainDb = it))) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppSwitch(checked = s.mic.gateOn, onCheckedChange = { save(s.copy(mic = s.mic.copy(gateOn = it))) })
            Spacer(Modifier.width(8.dp))
            Text(Tr.t("voicescreen.gate"), style = MaterialTheme.typography.bodyMedium)
        }
        if (s.mic.gateOn) SliderRow(Tr.t("voicescreen.threshold"), s.mic.gateDb, -80.0..-20.0, 1.0, "dBFS") { save(s.copy(mic = s.mic.copy(gateDb = it))) }
    }

    if (eqShown) panel {
        Text(Tr.t("voicescreen.filters_title"), style = MaterialTheme.typography.titleSmall)
        SliderRow(Tr.t("voicescreen.highpass"), s.highpassHz, 20.0..1000.0, 10.0, "Hz", enabled = fx) { save(s.copy(highpassHz = it)) }
        SliderRow(Tr.t("voicescreen.lowpass"), s.lowpassHz, 1500.0..8000.0, 50.0, "Hz", enabled = fx) { save(s.copy(lowpassHz = it)) }
        var details by remember { mutableStateOf(false) }
        s.bands.forEachIndexed { i, b ->
            val hz = if (b.hz >= 1000) Format.decimal(b.hz / 1000.0, 2) + " kHz" else "${b.hz.roundToInt()} Hz"   // i18n-ok
            val name = if (b.shelf) Tr.t("voicescreen.band_shelf", "band" to hz) else hz
            SliderRow(name, b.gainDb, -VoiceEq.GAIN_MAX_DB..VoiceEq.GAIN_MAX_DB, 0.5, "dB", enabled = fx) { v ->
                save(s.copy(bands = s.bands.mapIndexed { j, x -> if (j == i) x.copy(gainDb = v) else x }))
            }
            if (details) {
                val base = VoiceEq.BANDS_HZ[i]
                SliderRow("   " + Tr.t("voicescreen.band_frequency"), b.hz, base / 1.5..base * 1.5, 5.0, "Hz", enabled = fx) { v ->
                    save(s.copy(bands = s.bands.mapIndexed { j, x -> if (j == i) x.copy(hz = v) else x }))
                }
                SliderRow("   " + Tr.t("voicescreen.band_q"), b.q, VoiceEq.Q_MIN..VoiceEq.Q_MAX, 0.1, "", enabled = fx) { v ->
                    save(s.copy(bands = s.bands.mapIndexed { j, x -> if (j == i) x.copy(q = v) else x }))
                }
            }
        }
        TextButton(onClick = { details = !details }) { Text(if (details) Tr.t("voicescreen.hide_details") else Tr.t("voicescreen.show_details")) }
    }

    if (fxShown) panel {
        Text(Tr.t("voicescreen.fx_title"), style = MaterialTheme.typography.titleSmall)
        Text(Tr.t("voicescreen.fx_warning"),
            color = WARN, style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppSwitch(checked = s.chorus.on, onCheckedChange = { save(s.copy(chorus = s.chorus.copy(on = it))) }, enabled = fx)
            Spacer(Modifier.width(8.dp))
            Text(Tr.t("voicescreen.chorus"), style = MaterialTheme.typography.bodyMedium)
        }
        if (s.chorus.on) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((key, t) in VoiceEq.CHORUS_TYPES) CompactChip(t.label, onClick = { save(s.copy(chorus = s.chorus.copy(type = key))) }, selected = s.chorus.type == key, enabled = fx)
            }
            SliderRow(Tr.t("voicescreen.mix"), s.chorus.mix, 0.0..100.0, 5.0, "%", enabled = fx) { save(s.copy(chorus = s.chorus.copy(mix = it))) }
            SliderRow(Tr.t("voicescreen.rate"), s.chorus.rateHz, 0.1..5.0, 0.1, "Hz", enabled = fx) { save(s.copy(chorus = s.chorus.copy(rateHz = it))) }
            SliderRow(Tr.t("voicescreen.depth"), s.chorus.depthMs, 0.5..8.0, 0.5, "ms", enabled = fx) { save(s.copy(chorus = s.chorus.copy(depthMs = it))) }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppSwitch(checked = s.reverb.on, onCheckedChange = { save(s.copy(reverb = s.reverb.copy(on = it))) }, enabled = fx)
            Spacer(Modifier.width(8.dp))
            Text(Tr.t("voicescreen.reverb"), style = MaterialTheme.typography.bodyMedium)
        }
        if (s.reverb.on) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((key, t) in VoiceEq.REVERB_TYPES) CompactChip(t.label, onClick = {
                    save(s.copy(reverb = s.reverb.copy(type = key, seconds = t.seconds)))
                }, selected = s.reverb.type == key, enabled = fx)
            }
            SliderRow(Tr.t("voicescreen.mix"), s.reverb.mix, 0.0..100.0, 5.0, "%", enabled = fx) { save(s.copy(reverb = s.reverb.copy(mix = it))) }
            SliderRow(Tr.t("voicescreen.duration"), s.reverb.seconds, 0.2..4.0, 0.1, "s", enabled = fx) { save(s.copy(reverb = s.reverb.copy(seconds = it))) }
        }
    }

    // Bips de fin d'émission : produits et émis par la STATION (réglage commun à tous les appareils)
    if (Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.ROGER, beeps?.let { it.rogerEnabled || it.linkLostEnabled } == true)) panel { BeepsSection(beeps, beepsConnected) }

    if (Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.LISTEN, ui.recording || ui.playing)) panel {
        Text(Tr.t("voicescreen.listen_title"), style = MaterialTheme.typography.titleSmall)
        Text(
            Tr.t("voicescreen.listen_hint"),
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { if (ui.recording) VoiceHub.stopRecording() else say(VoiceHub.startRecording()) }, enabled = !transmitting) {
                Text(if (ui.recording) Tr.t("voicescreen.stop_recording", "seconds" to ui.recordedS.roundToInt()) else Tr.t("voicescreen.record"))
            }
            OutlinedButton(onClick = { if (ui.playing) VoiceHub.stopPlayback() else say(VoiceHub.play()) },
                enabled = !transmitting && !ui.recording && ui.recordedS > 0) {
                Text(if (ui.playing) Tr.t("voicescreen.stop_playback")
                    else if (ui.recordedS > 0) Tr.t("voicescreen.replay_seconds", "seconds" to ui.recordedS.roundToInt()) else Tr.t("voicescreen.replay"))
            }
        }
    }

    // Version Google Play : débrouillage de la réception seulement (BuildConfig.SCRAMBLER = brouillage de l'émission)
    if (Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.SCRAMBLER, ui.scrambler.tx || ui.scrambler.rx)) ScramblerPanel(ui.scrambler, panel)

    if (replayAllowed && Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.REPLAY)) ReplayPanel(transmitting, canBroadcast, onBroadcast, panel)

    if (eqShown || fxShown) panel {
        Text(Tr.t("voicescreen.share_title"), style = MaterialTheme.typography.titleSmall)
        Text(Tr.t("voicescreen.share_hint"), color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { exporter.launch("voix-openremotetrx.json") }) { Text(Tr.t("voicescreen.export")) }
            OutlinedButton(onClick = { importer.launch(arrayOf("application/json", "text/plain", "*/*")) }) { Text(Tr.t("voicescreen.import")) }
            TextButton(onClick = { save(VoiceSettings()) }) { Text(Tr.t("voicescreen.reset")) }
        }
    }
}

private fun dbText(db: Double) = if (db <= -119) "—" else "${db.roundToInt()} dBFS"

/** Curseur avec sa valeur ; la valeur n'est enregistrée qu'au relâchement (pas d'écriture à chaque pixel). */
@Composable
private fun SliderRow(label: String, value: Double, range: ClosedFloatingPointRange<Double>, step: Double, unit: String,
                      enabled: Boolean = true, onDone: (Double) -> Unit) {
    var drag by remember { mutableStateOf<Float?>(null) }
    val shown = drag ?: value.toFloat()
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(96.dp))
        Slider(
            value = shown, onValueChange = { drag = it },
            onValueChangeFinished = { drag?.let { v -> onDone((Math.round(v / step) * step).coerceIn(range.start, range.endInclusive)) }; drag = null },
            valueRange = range.start.toFloat()..range.endInclusive.toFloat(), modifier = Modifier.weight(1f), enabled = enabled,
        )
        val v = Math.round(shown / step) * step
        Text(
            (if (step < 1) Format.decimal(v.toDouble(), 1) else v.roundToInt().toString()) + if (unit.isNotEmpty()) " $unit" else "",
            style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(64.dp),
        )
    }
}

/** Texte montré avant toute mise en service (décision de l'utilisateur du 2026-10-29 : message clair et confirmation). */
val SCRAMBLER_WARNING: String get() = Tr.t(if (BuildConfig.SCRAMBLER) "voicescreen.scrambler_warning" else "voicescreen.descrambler_warning")

/** Rubrique « Scrambler » : brouiller l'émission, débrouiller la réception, mode commun avec la page, décalage fin. */
@Composable
private fun ScramblerPanel(scr: ScramblerSettings, panel: @Composable (@Composable ColumnScope.() -> Unit) -> Unit) {
    val context = LocalContext.current
    var asking by remember { mutableStateOf<ScramblerSettings?>(null) }
    fun change(next: ScramblerSettings) {
        val refusedByBreizh = next.tx && !scr.tx && VoiceHub.ui.value.breizh      // refusé par VoiceHub (message) : pas de confirmation
        if (!refusedByBreizh && ((next.tx && !scr.tx) || (next.rx && !scr.rx))) asking = next else VoiceHub.setScrambler(context, next)
    }
    panel {
        Text(Tr.t("voicescreen.scrambler_title"), style = MaterialTheme.typography.titleSmall)
        Text(Tr.t(if (BuildConfig.SCRAMBLER) "voicescreen.scrambler_hint" else "voicescreen.descrambler_hint"), color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        if (BuildConfig.SCRAMBLER) Row(verticalAlignment = Alignment.CenterVertically) {   // absent de la version Google Play
            val breizh = VoiceHub.ui.value.breizh                         // Breizh et scrambler d'émission exclusifs
            AppSwitch(checked = scr.tx, onCheckedChange = { change(scr.copy(tx = it)) }, enabled = !breizh)
            Spacer(Modifier.width(8.dp))
            Text(if (breizh) Tr.t("voicescreen.scramble_tx_breizh") else Tr.t("voicescreen.scramble_tx"),
                style = MaterialTheme.typography.bodyMedium, color = if (scr.tx) WARN else if (breizh) Page.TEXTE_2 else Page.TEXTE)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            AppSwitch(checked = scr.rx, onCheckedChange = { change(scr.copy(rx = it)) })
            Spacer(Modifier.width(8.dp))
            Text(Tr.t("voicescreen.descramble_rx"), style = MaterialTheme.typography.bodyMedium)
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((key, m) in Scramblers.MODES) CompactChip(m.label, onClick = { VoiceHub.setScrambler(context, scr.copy(mode = key)) }, selected = scr.mode == key)
        }
        SliderRow(Tr.t("voicescreen.fine_offset"), scr.offsetHz.toDouble(), -Scramblers.OFFSET_MAX_HZ.toDouble()..Scramblers.OFFSET_MAX_HZ.toDouble(), 5.0, "Hz") {
            VoiceHub.setScrambler(context, scr.copy(offsetHz = it.roundToInt()))
        }
        Text(Tr.t(if (BuildConfig.SCRAMBLER) "voicescreen.scrambler_tuning" else "voicescreen.descrambler_tuning"),
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
    }
    asking?.let { next ->
        AlertDialog(
            onDismissRequest = { asking = null },
            title = { Text(if (next.tx && !scr.tx) Tr.t("voicescreen.confirm_scramble") else Tr.t("voicescreen.confirm_descramble")) },
            text = { Text(SCRAMBLER_WARNING) },
            confirmButton = { TextButton(onClick = { VoiceHub.setScrambler(context, next); asking = null }) { Text(Tr.t("voicescreen.confirm_enable")) } },
            dismissButton = { TextButton(onClick = { asking = null }) { Text(Tr.t("common.cancel")) } },
        )
    }
}

private val HOT = listOf(intArrayOf(255, 216, 74), intArrayOf(255, 42, 42))
private val COLD = listOf(intArrayOf(79, 195, 247), intArrayOf(57, 73, 171))

private fun mix(a: IntArray, b: IntArray, k: Double, alpha: Float) =
    Color((a[0] + (b[0] - a[0]) * k).roundToInt(), (a[1] + (b[1] - a[1]) * k).roundToInt(), (a[2] + (b[2] - a[2]) * k).roundToInt(), (alpha * 255).roundToInt())

/** Graphique « fun » de l'égaliseur (page : drawVoiceGraph) : zone de la parole, parties coupées, courbe colorée, pastilles. */
@Composable
private fun VoiceGraph(s: VoiceSettings) {
    val points = remember(s) { VoiceEq.curve(s, 160) }
    val label = remember { android.graphics.Paint().apply { color = android.graphics.Color.rgb(138, 155, 181); isAntiAlias = true } }
    Canvas(Modifier.fillMaxWidth().height(150.dp)) {
        val w = size.width
        val h = size.height
        fun x(hz: Double) = (VoiceEq.curveX(hz) * w).toFloat()
        fun y(db: Double) = (h * (VoiceEq.CURVE_MAX_DB - db) / (VoiceEq.CURVE_MAX_DB - VoiceEq.CURVE_MIN_DB)).toFloat()
        drawRect(Page.INSTRUMENT)
        drawRect(Color(80, 160, 255, 26), Offset(x(300.0), 0f), Size(x(3000.0) - x(300.0), h))          // la parole
        drawRect(Color(0, 0, 0, 90), Offset.Zero, Size(x(s.highpassHz), h))                              // coupé
        drawRect(Color(0, 0, 0, 90), Offset(x(s.lowpassHz), 0f), Size(w - x(s.lowpassHz), h))
        for (db in listOf(12.0, 6.0, -6.0, -12.0, -18.0)) drawLine(Color(0x22FFFFFF), Offset(0f, y(db)), Offset(w, y(db)))
        for (hz in listOf(100.0, 300.0, 1000.0, 3000.0)) drawLine(Color(0x22FFFFFF), Offset(x(hz), 0f), Offset(x(hz), h))
        val zero = y(0.0)
        val step = w / points.size + 1f
        for (p in points) {
            val k = minOf(1.0, kotlin.math.abs(p.db) / 12)
            val c = if (p.db >= 0) mix(HOT[0], HOT[1], k, 0.25f + 0.5f * k.toFloat()) else mix(COLD[0], COLD[1], k, 0.25f + 0.5f * k.toFloat())
            val top = minOf(y(p.db), zero)
            drawRect(c, Offset(x(p.hz), top), Size(step, maxOf(1f, kotlin.math.abs(zero - y(p.db)))))
        }
        val path = Path()
        points.forEachIndexed { i, p -> if (i == 0) path.moveTo(x(p.hz), y(p.db)) else path.lineTo(x(p.hz), y(p.db)) }
        drawPath(path, Color(0xE6FFFFFF), style = Stroke(width = 2.dp.toPx()))
        s.bands.forEachIndexed { i, b ->
            val near = points.minBy { kotlin.math.abs(it.hz - b.hz) }
            drawCircle(Color.hsl((i * 32f) % 360f, 0.85f, 0.6f), 4.5.dp.toPx(), Offset(x(b.hz), y(near.db)))
        }
        label.textSize = 11.dp.toPx()
        for ((hz, t) in listOf(100.0 to "100", 300.0 to "300", 1000.0 to "1 k", 3000.0 to "3 k Hz")) {   // i18n-ok
            drawContext.canvas.nativeCanvas.drawText(t, x(hz) + 3.dp.toPx(), h - 4.dp.toPx(), label)
        }
        for (db in listOf(12.0, -12.0)) drawContext.canvas.nativeCanvas.drawText((if (db > 0) "+" else "") + db.toInt() + " dB", 3.dp.toPx(), y(db) - 3.dp.toPx(), label)
        val badges = listOfNotNull(if (s.chorus.on) Tr.t("voicescreen.graph_chorus") else null, if (s.reverb.on) Tr.t("voicescreen.graph_reverb") else null)
        label.color = android.graphics.Color.rgb(255, 216, 74)
        badges.forEachIndexed { i, t -> drawContext.canvas.nativeCanvas.drawText(t, w - 80.dp.toPx(), (16 + 15 * i).dp.toPx(), label) }
        label.color = android.graphics.Color.rgb(138, 155, 181)
        if (!s.enabled) {
            drawRect(Color(0, 0, 0, 115))
            label.color = android.graphics.Color.WHITE
            drawContext.canvas.nativeCanvas.drawText(Tr.t("voicescreen.graph_off"), w / 2 - 22.dp.toPx(), h / 2, label)
            label.color = android.graphics.Color.rgb(138, 155, 181)
        }
    }
}

/**
 * Rediffusion d'un enregistrement de l'audio REÇU (accordée sur la station par l'assistant, sous la responsabilité de
 * l'opérateur) : enregistrer (TOT - 5 s au plus), puis diffuser en émission, comme un appui sur le PTT (« Émission
 * autorisée » et toutes les règles de la station). Pendant la diffusion, le micro n'est pas entendu et l'enregistrement
 * passe aussi sur le téléphone ; STOP l'arrête et repasse en réception.
 */
@Composable
private fun ReplayPanel(transmitting: Boolean, canBroadcast: Boolean, onBroadcast: () -> Unit,
                        panel: @Composable (@Composable ColumnScope.() -> Unit) -> Unit) {
    val context = LocalContext.current
    val r by com.rfdiy.openremotetrx.core.ReplayHub.ui.collectAsState()
    fun say(text: String?) { text?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() } }
    panel {
        Text(Tr.t("voicescreen.replay_title"), style = MaterialTheme.typography.titleSmall)
        Text(
            Tr.t("voicescreen.replay_hint", "seconds" to r.maxS),
            color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
        )
        Text(
            when {
                r.recording -> Tr.t("voicescreen.replay_recording", "seconds" to r.recordedS.roundToInt(), "max" to r.maxS, "level" to dbText(r.levelDb))
                r.playing -> Tr.t("voicescreen.replay_playing", "position" to r.positionS.roundToInt(), "seconds" to r.recordedS.roundToInt())
                r.pending -> Tr.t("voicescreen.replay_pending")
                r.recordedS > 0 -> Tr.t("voicescreen.replay_recorded", "seconds" to r.recordedS.roundToInt())
                else -> Tr.t("voicescreen.replay_empty")
            },
            style = MaterialTheme.typography.bodyMedium,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { if (r.recording) com.rfdiy.openremotetrx.core.ReplayHub.stopRecording() else say(com.rfdiy.openremotetrx.core.ReplayHub.startRecording()) },
                enabled = !transmitting && !r.playing && !r.pending,
            ) { Text(if (r.recording) Tr.t("common.stop") else Tr.t("voicescreen.record")) }
            Button(
                onClick = {
                    val refused = com.rfdiy.openremotetrx.core.ReplayHub.broadcast()
                    if (refused == null) onBroadcast() else say(refused)
                },
                enabled = canBroadcast && !transmitting && !r.recording && !r.playing && !r.pending && r.recordedS > 0,
            ) { Text(Tr.t("voicescreen.broadcast")) }
        }
        if (!canBroadcast) Text(Tr.t("voicescreen.armed_needed"), color = WARN, style = MaterialTheme.typography.bodySmall)
    }
}

