// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.LogLevel
import com.rfdiy.openremotetrx.logic.Radio

private val TX_RED = Color(0xFFC62828)
private val WARN = Color(0xFFEF6C00)

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
    val canSet = connected && rig.protocolOk
    val mineTx = ptt != null && ptt.mine && ptt.transmitting
    val debounce = remember { Debounce() }
    // Fréquence demandée : affichée et prise comme base des crans jusqu'à confirmation du poste (page : PENDING_MAX_MS).
    // L'état de la station arrive plusieurs fois par seconde : l'affichage revient seul à la fréquence du poste.
    var pendingHz by remember { mutableStateOf<Long?>(null) }
    var pendingAt by remember { mutableLongStateOf(0L) }
    var stepIndex by rememberSaveable { mutableStateOf(Radio.STEPS_HZ.indexOf(1000L)) }
    var entry by remember { mutableStateOf(false) }
    var showLog by rememberSaveable { mutableStateOf(false) }
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

    Column(modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
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
            Surface(shape = RoundedCornerShape(14.dp), tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        Radio.formatIcom(shownHz),
                        fontSize = 44.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace,
                        modifier = Modifier.fillMaxWidth().clickable(enabled = canSet) { entry = true },
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(Radio.modeLabel(radio?.mode), style = MaterialTheme.typography.titleMedium)
                        Radio.bandOf(shownHz)?.let { Text("${it.key} m", style = MaterialTheme.typography.titleMedium) }
                        Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.titleMedium)
                        if (radio != null && !radio.connected) Text("liaison CAT PERDUE", color = WARN)
                    }
                    LinearProgressIndicator(
                        progress = { Radio.sMeterFraction(radio?.strengthDb) },
                        modifier = Modifier.fillMaxWidth().height(10.dp),
                    )
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        for (label in listOf("S1", "3", "5", "7", "9", "+20", "+40", "+60")) {
                            Text(label, style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
            }

            // Accord : pas, crans
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { tune(-1) }, enabled = canSet, modifier = Modifier.weight(1f)) { Text("−", fontSize = 26.sp) }
                OutlinedButton(onClick = { stepIndex = (stepIndex + 1) % Radio.STEPS_HZ.size }, modifier = Modifier.weight(1.3f)) {
                    Text("pas ${stepLabel(step)}")
                }
                OutlinedButton(onClick = { tune(1) }, enabled = canSet, modifier = Modifier.weight(1f)) { Text("+", fontSize = 26.sp) }
            }

            // Bandes
            Section("Bandes")
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                val current = Radio.bandOf(radio?.frequencyHz)?.key
                for (band in Radio.BANDS) {
                    FilterChip(
                        selected = band.key == current, enabled = canSet,
                        onClick = { RigHub.selectBand(band.key) }, label = { Text(band.key) },
                    )
                }
            }

            // Modes du poste (émission : seulement ceux de tx_modes s'ils sont imposés)
            val modes = Radio.orderModes(hello?.capabilities?.modes.orEmpty())
            if (modes.isNotEmpty()) {
                Section("Mode")
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (mode in modes) {
                        FilterChip(
                            selected = mode == radio?.mode, enabled = canSet,
                            onClick = { RigHub.setMode(mode) }, label = { Text(Radio.modeLabel(mode)) },
                        )
                    }
                }
                if (hello?.txModes?.isNotEmpty() == true) {
                    Text("Émission permise en : " + hello.txModes.joinToString(", ") { Radio.modeLabel(it) },
                        style = MaterialTheme.typography.bodySmall)
                }
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
            if (rig.memories.isNotEmpty()) {
                Section("Mémoires")
                for (m in rig.memories) {
                    Row(
                        Modifier.fillMaxWidth().clickable(enabled = canSet) { RigHub.recallMemory(m.id) }.padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text((if (m.favorite) "★ " else "") + m.name, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                        Text("${Radio.formatIcom(m.hz)}  ${Radio.modeLabel(m.mode)}", fontFamily = FontFamily.Monospace,
                            style = MaterialTheme.typography.bodyMedium)
                    }
                    HorizontalDivider()
                }
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
            OutlinedButton(onClick = onDisconnect) { Text("Déconnecter") }
        }

        // Toujours visibles : armement, PTT (appui simple), STOP
        Surface(tonalElevation = 6.dp) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
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
                        modifier = Modifier.weight(2f).height(80.dp),
                    ) {
                        Text(
                            when {
                                mineTx -> "FIN D'ÉMISSION"
                                ptt?.mine == true -> "COUPURE…"
                                ptt?.other == true -> "Autre client en émission"
                                !rig.armed -> "PTT\n(autoriser d'abord)"
                                else -> "ÉMETTRE"
                            },
                            fontSize = 20.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                        )
                    }
                    Button(
                        onClick = { RigHub.stop() },
                        enabled = connected,
                        colors = ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White),
                        shape = RoundedCornerShape(16.dp),
                        modifier = Modifier.weight(1f).height(80.dp),
                    ) { Text("STOP", fontSize = 22.sp, fontWeight = FontWeight.Bold) }
                }
            }
        }
    }

    if (entry) FrequencyDialog(shownHz, onDismiss = { entry = false }) { hz ->
        entry = false
        go(hz)
    }
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

@Composable
private fun Section(title: String) {
    Text(title, style = MaterialTheme.typography.titleSmall)
}

@Composable
private fun Banner(text: String, color: Color, big: Boolean = false, textColor: Color = Color.White) {
    Text(
        text,
        color = textColor,
        fontSize = if (big) 22.sp else 15.sp,
        fontWeight = if (big) FontWeight.Bold else FontWeight.Normal,
        modifier = Modifier.fillMaxWidth().background(color, RoundedCornerShape(10.dp)).padding(12.dp),
    )
}
