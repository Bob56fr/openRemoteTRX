// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.content.res.Configuration
import android.os.SystemClock
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.logic.Band
import com.rfdiy.openremotetrx.logic.Controls
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.HfScope
import com.rfdiy.openremotetrx.logic.Indicators
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.LogLevel
import com.rfdiy.openremotetrx.logic.Meter
import com.rfdiy.openremotetrx.logic.Radio
import com.rfdiy.openremotetrx.logic.RigSession
import com.rfdiy.openremotetrx.protocol.Hello
import java.util.Locale
import kotlin.math.roundToInt

private val TX_RED = Color(0xFFC62828)
private val WARN = Color(0xFFEF6C00)
private val SQL_OPEN = Color(0xFF43A047)

/** Anti-rebond du PTT : Android peut livrer un « clic fantôme » juste après un appui (CLAUDE.md, page web). */
private class Debounce(private val ms: Long = 600) {
    private var last = 0L
    fun pass(): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (now - last < ms) return false
        last = now
        return true
    }
}

/**
 * Station connectée. Tout ce qui s'affiche vient de l'état publié par la station (RigUi.rig) : l'émission n'est
 * jamais supposée après un appui. En bas, toujours visibles : « Émission autorisée », PTT (appui simple) et STOP.
 */
@Composable
fun RigScreen(ui: RigUi, modifier: Modifier, onDisconnect: () -> Unit) {
    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val hello = rig.hello
    val connected = rig.status == LinkStatus.CONNECTED
    // Réglages du poste : seulement en réception (la station les refuse pendant l'émission, comme la page).
    val canSet = connected && rig.protocolOk && (rig.state?.ptt?.state ?: "RX") == "RX"
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("ui", Context.MODE_PRIVATE) }
    var keepScreenOn by remember { mutableStateOf(prefs.getBoolean("keep_screen_on", true)) }
    // Écran allumé tant que la station est affichée (comme la page) ; l'écoute continue de toute façon écran éteint.
    val view = LocalView.current
    DisposableEffect(keepScreenOn, rig.status) {
        view.keepScreenOn = keepScreenOn && rig.status != LinkStatus.DISCONNECTED
        onDispose { view.keepScreenOn = false }
    }
    val mineTx = ptt != null && ptt.mine && ptt.transmitting
    val debounce = remember { Debounce() }
    // Fréquence demandée : affichée et prise comme base des crans jusqu'à confirmation du poste (page : PENDING_MAX_MS).
    // L'état de la station arrive plusieurs fois par seconde : l'affichage revient seul à la fréquence du poste.
    var pendingHz by remember { mutableStateOf<Long?>(null) }
    var pendingAt by remember { mutableLongStateOf(0L) }
    var stepIndex by rememberSaveable { mutableStateOf(Radio.STEPS_HZ.indexOf(1000L)) }
    var entry by remember { mutableStateOf(false) }
    var showLog by rememberSaveable { mutableStateOf(false) }
    var levelsDialog by remember { mutableStateOf(false) }
    var showWaterfall by rememberSaveable { mutableStateOf(false) }
    var bandsPref by remember { mutableStateOf(prefs.getString("bands", "") ?: "") }
    var bandsDialog by remember { mutableStateOf(false) }
    var memoryDialog by remember { mutableStateOf<MemoryEdit?>(null) }
    var squelchDrag by remember { mutableStateOf<Float?>(null) }        // valeur suivie pendant que le doigt règle
    val pendingLive = pendingHz?.takeIf { it != radio?.frequencyHz && SystemClock.elapsedRealtime() - pendingAt < 2500 }
    val shownHz = pendingLive ?: radio?.frequencyHz
    val step = Radio.STEPS_HZ[stepIndex]

    fun go(hz: Long) {
        pendingHz = hz
        pendingAt = SystemClock.elapsedRealtime()
        RigHub.setFrequency(hz)
    }

    fun tune(steps: Int) {
        go(Radio.nudge(shownHz ?: return, step, steps))
    }

    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    if (landscape && HfScope.configured(hello) && rig.status != LinkStatus.DISCONNECTED) {
        LandscapeScope(ui, canSet, onTune = { go(it) }, modifier)
        return
    }

    Column(modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // En-tête : station, liaison, sourdine
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(ui.station?.name ?: "Station", style = MaterialTheme.typography.titleLarge)
                    Text(
                        when (rig.status) {
                            LinkStatus.CONNECTED -> "Connecté" + (rig.rttMs?.let { " · $it ms" } ?: "")
                            LinkStatus.CONNECTING -> "Connexion…"
                            LinkStatus.RECONNECTING -> "Reconnexion…"
                            LinkStatus.DISCONNECTED -> "Déconnecté"
                        },
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                Text("Muet", style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.width(6.dp))
                Switch(checked = ui.muted, onCheckedChange = { RigHub.setMuted(it) })
            }

            rig.reconnect?.let { r ->
                Banner(
                    "LIAISON PERDUE : reconnexion encore ${r.remainingS} s (essai ${r.attempts})" +
                        (if (r.lastError.isNotEmpty()) "\n${r.lastError}" else "") + "\nL'émission éventuelle est coupée par la station.",
                    TX_RED,
                )
            }
            if (!rig.protocolOk) Banner("Version de protocole inconnue : réception et STOP seulement.", WARN)

            // Afficheur : fréquence (toucher = saisie), mode, S-mètre
            Surface(shape = RoundedCornerShape(12.dp), tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        Radio.formatIcom(shownHz),
                        fontSize = 34.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace,
                        modifier = Modifier.fillMaxWidth().clickable(enabled = canSet) { entry = true },
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(Radio.modeLabel(radio?.mode), style = MaterialTheme.typography.titleMedium)
                        Radio.bandOf(shownHz)?.let { Text("${it.key} m", style = MaterialTheme.typography.titleMedium) }
                        Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.titleMedium)
                        if (radio != null && !radio.connected) Text("liaison CAT PERDUE", color = WARN)
                    }
                    // Voyants (comme sur un poste) : vert = actif, gris = éteint
                    val lights = Indicators.of(rig.state)
                    if (lights.isNotEmpty()) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            for (light in lights) {
                                Text(
                                    light.label, style = MaterialTheme.typography.labelMedium,
                                    fontWeight = if (light.on) FontWeight.Bold else FontWeight.Normal,
                                    color = if (light.on) SQL_OPEN else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f),
                                )
                            }
                        }
                    }
                    LinearProgressIndicator(
                        progress = { Radio.sMeterFraction(radio?.strengthDb) },
                        drawStopIndicator = {},                       // pas de point en bout de barre : il ferait croire à S9+60
                        modifier = Modifier.fillMaxWidth().height(8.dp),
                    )
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        for (label in listOf("S1", "3", "5", "7", "9", "+20", "+40", "+60")) {
                            Text(label, style = MaterialTheme.typography.labelSmall)
                        }
                    }
                    radio?.levels?.get("SQL")?.let { sql ->
                        // Squelch : une seule commande à la fin du geste (page : pas une par pixel)
                        val shown = squelchDrag ?: sql.toFloat()
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            // Vert : squelch ouvert (le son passe ; estimation par le S-mètre, la station ne donne pas le DCD)
                            Text("SQL", style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(36.dp),
                                color = if (Radio.squelchOpen(sql, radio.strengthDb)) SQL_OPEN else Color.Unspecified,
                                fontWeight = if (Radio.squelchOpen(sql, radio.strengthDb)) FontWeight.Bold else FontWeight.Normal)
                            Slider(
                                value = shown, onValueChange = { squelchDrag = it }, enabled = canSet,
                                onValueChangeFinished = { squelchDrag?.let { RigHub.setSquelch(it.toDouble()) }; squelchDrag = null },
                                modifier = Modifier.weight(1f),
                            )
                            val percent = (shown * 100).roundToInt()
                            Text(if (percent == 0) "ouvert" else "$percent %", style = MaterialTheme.typography.labelLarge,
                                modifier = Modifier.width(56.dp), textAlign = TextAlign.End)
                        }
                    }
                }
            }

            // Portrait : waterfall du son reçu (calculé sur le téléphone, seulement pendant l'affichage). Le spectre HF du
            // poste s'affiche en plein écran en tournant le téléphone (paysage).
            if (showWaterfall) AudioWaterfallView(onClose = { showWaterfall = false })
            else Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = { showWaterfall = true }, enabled = connected) { Text("Spectre audio") }
                if (HfScope.configured(hello)) Text("Spectre HF : tourner le téléphone", style = MaterialTheme.typography.bodySmall)
            }

            // Accord : pas, crans
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { tune(-1) }, enabled = canSet, modifier = Modifier.weight(1f)) { Text("−", fontSize = 20.sp) }
                OutlinedButton(onClick = { stepIndex = (stepIndex + 1) % Radio.STEPS_HZ.size }, modifier = Modifier.weight(1.3f)) {
                    Text("pas ${stepLabel(step)}")
                }
                OutlinedButton(onClick = { tune(1) }, enabled = canSet, modifier = Modifier.weight(1f)) { Text("+", fontSize = 20.sp) }
            }

            // Bandes préférées, dans l'ordre choisi (✎ : choisir et ordonner)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                val current = Radio.bandOf(radio?.frequencyHz)?.key
                for (band in Radio.favoriteBands(bandsPref)) {
                    CompactChip(band.key, onClick = { RigHub.selectBand(band.key) }, enabled = canSet, selected = band.key == current)
                }
                CompactChip("✎", onClick = { bandsDialog = true })
            }

            // Modes du poste (émission : seulement ceux de tx_modes s'ils sont imposés)
            val modes = Radio.orderModes(hello?.capabilities?.modes.orEmpty())
            if (modes.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    for (mode in modes) {
                        CompactChip(Radio.modeLabel(mode), onClick = { RigHub.setMode(mode) }, enabled = canSet, selected = mode == radio?.mode)
                    }
                }
                if (hello?.txModes?.isNotEmpty() == true) {
                    Text("Émission permise en : " + hello.txModes.joinToString(", ") { Radio.modeLabel(it) },
                        style = MaterialTheme.typography.bodySmall)
                }
            }

            // Fonctions du poste (comme la page) : verrouillées pendant l'émission
            val chips = Controls.chips(hello, rig.state)
            if (chips.isNotEmpty()) {
                // Appui : marche / arrêt (comme la page) ; appui LONG sur NR ou NB : niveaux de NR et NB (fenêtre)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    for (chip in chips) {
                        CompactChip(
                            chip.label, onClick = { RigHub.pressControl(chip.key) }, enabled = canSet, selected = chip.on,
                            onLongClick = if (chip.key == "NR" || chip.key == "NB") ({ levelsDialog = true }) else null,
                        )
                    }
                }
            }

            // Indicateurs : Po, SWR, ALC pendant l'émission ; COMP, Vd, température en permanence s'ils existent
            val meters = Controls.meters(rig.state)
            val txMeters = meters.filter { it.key in setOf("PO", "SWR", "ALC") }
            if (ptt?.transmitting == true && txMeters.isNotEmpty()) {
                for (m in txMeters) MeterRow(m, warn = (m.key == "SWR" && m.fraction >= 0.5f) || (m.key == "ALC" && m.fraction >= 0.9f))
            }
            val others = meters.filterNot { it in txMeters }
            if (others.isNotEmpty()) {
                Text(others.joinToString("   ") { "${it.label} ${it.text}" }, style = MaterialTheme.typography.bodySmall)
            }

            // État de l'émission (station)
            if (ptt != null) {
                val text = when {
                    mineTx -> "ÉMISSION EN COURS" + (ptt.totSeconds?.let { " — coupure dans ${Format.duration(it)}" } ?: "")
                    ptt.other -> "${ptt.label} : autre client (${rig.state?.ptt?.owner ?: "?"})"
                    else -> ptt.label
                }
                Banner(
                    text, if (ptt.transmitting) TX_RED else MaterialTheme.colorScheme.secondaryContainer, big = true,
                    textColor = if (ptt.transmitting) Color.White else MaterialTheme.colorScheme.onSecondaryContainer,
                )
                if (ptt.totWarning) Banner("Fin du temps d'émission proche (TOT).", WARN)
                ptt.local?.let { local ->
                    Banner(local, WARN)
                    if (ptt.canReleaseLocal) OutlinedButton(onClick = { RigHub.releaseLocal() }) { Text("Reprendre la main") }
                }
                when (ptt.tempAlert) {
                    "hot" -> Banner("Poste TROP CHAUD : émission refusée.", TX_RED)
                    "warn" -> Banner("Poste chaud : surveille la température.", WARN)
                }
                if (ptt.fault.isNotEmpty()) Banner("DÉFAUT à la station (${ptt.fault}) : intervention nécessaire.", TX_RED)
                if (ptt.lastCut.isNotEmpty() && !ptt.transmitting) Text("Dernière coupure : ${ptt.lastCut}", style = MaterialTheme.typography.bodySmall)
            }

            // Mémoires partagées de la station
            if (hello?.offers("memories") == true || rig.memories.isNotEmpty()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Mémoires", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                    TextButton(onClick = { memoryDialog = MemoryEdit(null, "", shownHz, radio?.mode, false) }, enabled = connected) {
                        Text("+ Mémoriser ici")
                    }
                }
                // Lignes de 40 dp (assez pour le doigt) : ★ favori, nom + fréquence = rappel, ✎ = modifier ; bloc sans
                // l'espacement de l'écran (sinon 8 dp de plus de chaque côté du séparateur)
                Column { for (m in rig.memories) {
                    Row(Modifier.height(40.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            Modifier.size(40.dp).clickable(enabled = connected) { RigHub.saveMemory(m.name, m.hz, m.mode, !m.favorite, m.id) },
                            contentAlignment = Alignment.Center,
                        ) { Text(if (m.favorite) "★" else "☆", color = MaterialTheme.colorScheme.primary) }
                        Row(
                            Modifier.weight(1f).fillMaxHeight().clickable(enabled = canSet) { RigHub.recallMemory(m.id) },
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(m.name, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                            Text("${Radio.formatIcom(m.hz)}  ${Radio.modeLabel(m.mode)}", fontFamily = FontFamily.Monospace,
                                style = MaterialTheme.typography.bodyMedium)
                        }
                        Box(
                            Modifier.size(40.dp).clickable(enabled = connected) { memoryDialog = MemoryEdit(m.id, m.name, m.hz, m.mode, m.favorite) },
                            contentAlignment = Alignment.Center,
                        ) { Text("✎") }
                    }
                    HorizontalDivider()
                } }
            }

            // Journal
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Journal", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                TextButton(onClick = { showLog = !showLog }) { Text(if (showLog) "Réduire" else "Tout voir") }
            }
            for (line in rig.log.asReversed().take(if (showLog) 60 else 3)) {
                Text(
                    line.text, style = MaterialTheme.typography.bodySmall,
                    color = when (line.level) {
                        LogLevel.BAD -> MaterialTheme.colorScheme.error
                        LogLevel.WARN -> WARN
                        LogLevel.INFO -> MaterialTheme.colorScheme.onSurface
                    },
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = keepScreenOn, onCheckedChange = {
                    keepScreenOn = it
                    prefs.edit().putBoolean("keep_screen_on", it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text("Écran toujours allumé pendant la connexion", style = MaterialTheme.typography.bodyMedium)
            }
            OutlinedButton(onClick = onDisconnect) { Text("Déconnecter") }
        }

        // Toujours visibles : armement, PTT (appui simple), STOP
        Surface(tonalElevation = 6.dp) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(checked = rig.armed, onCheckedChange = { RigHub.setArmed(it) }, enabled = connected && rig.protocolOk)
                    Spacer(Modifier.width(8.dp))
                    Text("Émission autorisée" + if (!ui.micAllowed) " (micro refusé : réception seule)" else "")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val pttEnabled = connected && rig.protocolOk && ui.micAllowed && (mineTx || (ptt?.transmitting != true && rig.armed))
                    Button(
                        onClick = { if (debounce.pass()) RigHub.toggle() },
                        enabled = pttEnabled,
                        colors = if (mineTx) ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White) else ButtonDefaults.buttonColors(),
                        shape = RoundedCornerShape(16.dp),
                        modifier = Modifier.weight(2f).height(64.dp),
                    ) {
                        Text(
                            when {
                                mineTx -> "FIN D'ÉMISSION"
                                ptt?.mine == true -> "COUPURE…"
                                ptt?.other == true -> "Autre client en émission"
                                !rig.armed -> "PTT\n(autoriser d'abord)"
                                else -> "ÉMETTRE"
                            },
                            fontSize = 16.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                        )
                    }
                    Button(
                        onClick = { RigHub.stop() },
                        enabled = connected,
                        colors = ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White),
                        shape = RoundedCornerShape(16.dp),
                        modifier = Modifier.weight(1f).height(64.dp),
                    ) { Text("STOP", fontSize = 18.sp, fontWeight = FontWeight.Bold) }
                }
            }
        }
    }

    if (entry) FrequencyDialog(shownHz, onDismiss = { entry = false }) { hz ->
        entry = false
        go(hz)
    }
    if (levelsDialog) LevelsDialog(levelRanges(hello, radio?.levels), radio?.levels.orEmpty(), canSet) { levelsDialog = false }
    if (bandsDialog) BandsDialog(Radio.favoriteBands(bandsPref), onDismiss = { bandsDialog = false }) { chosen ->
        bandsPref = Radio.favoriteBandsText(chosen)
        prefs.edit().putString("bands", bandsPref).apply()
        bandsDialog = false
    }
    memoryDialog?.let { edit ->
        MemoryDialog(edit, Radio.orderModes(hello?.capabilities?.modes.orEmpty()), onDismiss = { memoryDialog = null })
    }
}

/** Mémoire en cours de création (`id` null) ou de modification. */
private data class MemoryEdit(val id: String?, val name: String, val hz: Long?, val mode: String?, val favorite: Boolean)

/** Niveaux réglables (NR, NB) : plage [min, max, pas] déclarée par le poste ET valeur lue (page : levelRange). */
private fun levelRanges(hello: Hello?, levels: Map<String, Double>?): Map<String, List<Double>> =
    listOf("NR", "NB").mapNotNull { name ->
        val range = hello?.capabilities?.levelRanges?.get(name)
        if (range != null && range.size == 3 && range[1] > range[0] && levels?.containsKey(name) == true) name to range else null
    }.toMap()

private fun levelText(value: Double, range: List<Double>): String =
    if (range[2] > 0) "${((value - range[0]) / range[2]).roundToInt()} / ${((range[1] - range[0]) / range[2]).roundToInt()}"
    else String.format(Locale.ROOT, "%.2f", value)

/** Fenêtre des niveaux NR / NB : une commande à la fin de chaque geste ; verrouillée pendant l'émission. */
@Composable
private fun LevelsDialog(ranges: Map<String, List<Double>>, levels: Map<String, Double>, enabled: Boolean, onDismiss: () -> Unit) {
    val dragging = remember { mutableStateMapOf<String, Float>() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Niveaux du poste") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((name, range) in ranges) {
                    val value = dragging[name] ?: (levels[name] ?: range[0]).toFloat()
                    val steps = if (range[2] > 0) (((range[1] - range[0]) / range[2]).roundToInt() - 1).coerceAtLeast(0) else 0
                    Text("${if (name == "NR") "Réducteur de bruit (NR)" else "Antiparasite (NB)"} : ${levelText(value.toDouble(), range)}")
                    Slider(
                        value = value, onValueChange = { dragging[name] = it }, enabled = enabled,
                        valueRange = range[0].toFloat()..range[1].toFloat(), steps = steps,
                        onValueChangeFinished = { dragging.remove(name)?.let { RigHub.setLevel(name, it.toDouble()) } },
                    )
                }
                if (ranges.isEmpty()) Text("Le poste ne déclare pas de niveau réglable pour NR ni NB.")
                if (!enabled) Text("Réglages verrouillés pendant l'émission.", color = WARN)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
    )
}

/** Création ou modification d'une mémoire partagée ; suppression confirmée en deux temps (comme la page). */
@Composable
private fun MemoryDialog(edit: MemoryEdit, modes: List<String>, onDismiss: () -> Unit) {
    var name by remember { mutableStateOf(edit.name) }
    var freq by remember { mutableStateOf(edit.hz?.let { Radio.formatIcom(it) } ?: "") }
    var mode by remember { mutableStateOf(edit.mode ?: modes.firstOrNull() ?: "") }
    var favorite by remember { mutableStateOf(edit.favorite) }
    var deleteArmed by remember { mutableStateOf(false) }
    val hz = Radio.parseFrequencyEntry(freq)
    val nameOk = name.isNotBlank() && name.trim().length <= RigSession.MEMORY_NAME_MAX
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (edit.id == null) "Nouvelle mémoire" else "Mémoire") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("Nom") }, singleLine = true)
                OutlinedTextField(
                    freq, { freq = it }, label = { Text("Fréquence (7074 kHz, 14.205 MHz)") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    supportingText = { Text(hz?.let { Format.frequency(it) } ?: "Fréquence invalide") },
                )
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (m in modes.ifEmpty { listOfNotNull(edit.mode) }) {
                        FilterChip(selected = m == mode, onClick = { mode = m }, label = { Text(Radio.modeLabel(m)) })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(checked = favorite, onCheckedChange = { favorite = it })
                    Spacer(Modifier.width(8.dp))
                    Text("Favorite (en tête de liste)")
                }
                if (edit.id != null) {
                    TextButton(onClick = {
                        if (deleteArmed) { RigHub.deleteMemory(edit.id); onDismiss() } else deleteArmed = true
                    }) { Text(if (deleteArmed) "Confirmer la suppression" else "Supprimer", color = MaterialTheme.colorScheme.error) }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                RigHub.saveMemory(name.trim(), hz!!, mode, favorite, edit.id)
                onDismiss()
            }, enabled = nameOk && hz != null && mode.isNotEmpty()) { Text("Enregistrer") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } },
    )
}

private fun stepLabel(hz: Long): String = when {
    hz >= 1000 && hz % 1000 == 0L -> "${hz / 1000} kHz"
    hz >= 1000 -> "%.1f kHz".format(hz / 1000.0).replace('.', ',')
    else -> "$hz Hz"
}

/** Saisie au clavier, mêmes formats que la page : 7074 (kHz), 14.205 (MHz), 7.074.00 (format du poste). */
@Composable
private fun FrequencyDialog(current: Long?, onDismiss: () -> Unit, onSet: (Long) -> Unit) {
    var text by remember { mutableStateOf("") }
    val parsed = Radio.parseFrequencyEntry(text)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Fréquence") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Actuelle : ${Radio.formatIcom(current)}", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    text, { text = it }, singleLine = true, label = { Text("7074 (kHz) ou 14.205 (MHz)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                )
                Text(
                    if (text.isBlank()) "" else parsed?.let { "= ${Format.frequency(it)}" } ?: "Fréquence invalide",
                    color = if (parsed == null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                )
            }
        },
        confirmButton = { TextButton(onClick = { parsed?.let(onSet) }, enabled = parsed != null) { Text("Aller") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } },
    )
}

/**
 * Bandes affichées : cocher, ordonner (↑ ↓). Réglage de CE téléphone (la page a le sien). Aucune cochée = toutes.
 */
@Composable
private fun BandsDialog(current: List<Band>, onDismiss: () -> Unit, onSave: (List<Band>) -> Unit) {
    val order = remember { mutableStateListOf<Band>().apply { addAll(current); addAll(Radio.BANDS.filterNot { it in current }) } }
    val checked = remember { mutableStateMapOf<String, Boolean>().apply { for (b in Radio.BANDS) put(b.key, b in current && current.size < Radio.BANDS.size) } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Bandes affichées") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("Cochez vos bandes et mettez-les dans l'ordre voulu. Aucune cochée : toutes.", style = MaterialTheme.typography.bodySmall)
                for ((i, band) in order.withIndex()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = checked[band.key] == true, onCheckedChange = { checked[band.key] = it })
                        Text("${band.key} m", modifier = Modifier.weight(1f))
                        TextButton(onClick = { if (i > 0) { order.removeAt(i); order.add(i - 1, band) } }, enabled = i > 0) { Text("↑") }
                        TextButton(onClick = { if (i < order.size - 1) { order.removeAt(i); order.add(i + 1, band) } }, enabled = i < order.size - 1) { Text("↓") }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onSave(order.filter { checked[it.key] == true }) }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } },
    )
}

/**
 * Paysage : spectre HF du poste en plein écran avec les spots du Cluster DX. En haut, toujours : fréquence, mode,
 * état de l'émission (celui de la station) et STOP. Pour émettre, revenir en portrait (PTT et « Émission autorisée »).
 */
@Composable
private fun LandscapeScope(ui: RigUi, canSet: Boolean, onTune: (Long) -> Unit, modifier: Modifier) {
    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val screenH = LocalConfiguration.current.screenHeightDp.dp
    Column(modifier.fillMaxSize().padding(horizontal = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(Radio.formatIcom(radio?.frequencyHz), fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
            Text(Radio.modeLabel(radio?.mode), style = MaterialTheme.typography.titleSmall)
            Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.weight(1f))
            rig.reconnect?.let { Text("LIAISON PERDUE : reconnexion…", color = TX_RED, fontWeight = FontWeight.Bold) }
            if (ptt != null) {
                Text(
                    if (ptt.mine && ptt.transmitting) "ÉMISSION EN COURS" + (ptt.totSeconds?.let { " " + Format.duration(it) } ?: "") else ptt.label,
                    color = if (ptt.transmitting) Color.White else MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(if (ptt.transmitting) TX_RED else Color.Transparent, RoundedCornerShape(6.dp))
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
            Button(
                onClick = { RigHub.stop() }, enabled = rig.status == LinkStatus.CONNECTED,
                colors = ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White),
                modifier = Modifier.height(40.dp),
            ) { Text("STOP", fontWeight = FontWeight.Bold) }
        }
        HfScopeView(
            ui, canSet, onTune, onClose = null,
            plotModifier = Modifier.fillMaxWidth().height((screenH - 150.dp).coerceAtLeast(120.dp)),
        )
    }
}

/** Indicateur : libellé, barre, valeur (orange si SWR >= 2 ou ALC >= 90 %). */
@Composable
private fun MeterRow(meter: Meter, warn: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(meter.label, style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(36.dp))
        LinearProgressIndicator(
            progress = { meter.fraction },
            drawStopIndicator = {},
            color = if (warn) WARN else MaterialTheme.colorScheme.primary,
            modifier = Modifier.weight(1f).height(8.dp),
        )
        Text(meter.text, style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(56.dp), textAlign = TextAlign.End)
    }
}

@Composable
private fun Banner(text: String, color: Color, big: Boolean = false, textColor: Color = Color.White) {
    Text(
        text,
        color = textColor,
        fontSize = if (big) 17.sp else 13.sp,
        fontWeight = if (big) FontWeight.Bold else FontWeight.Normal,
        modifier = Modifier.fillMaxWidth().background(color, RoundedCornerShape(8.dp)).padding(horizontal = 10.dp, vertical = 8.dp),
    )
}
