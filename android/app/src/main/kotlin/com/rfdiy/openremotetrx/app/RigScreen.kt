// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.LogLevel

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
 * jamais supposée après un appui. PTT = appui simple (toggle) ; STOP toujours présent.
 */
@Composable
fun RigScreen(ui: RigUi, modifier: Modifier, onDisconnect: () -> Unit) {
    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val connected = rig.status == LinkStatus.CONNECTED
    val mineTx = ptt != null && ptt.mine && ptt.transmitting
    val debounce = remember { Debounce() }

    Column(
        modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(ui.station?.name ?: "Station", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            Text(
                when (rig.status) {
                    LinkStatus.CONNECTED -> "Connecté" + (rig.rttMs?.let { " · $it ms" } ?: "")
                    LinkStatus.CONNECTING -> "Connexion…"
                    LinkStatus.RECONNECTING -> "Reconnexion…"
                    LinkStatus.DISCONNECTED -> "Déconnecté"
                },
                style = MaterialTheme.typography.labelLarge,
            )
        }

        rig.reconnect?.let { r ->
            Banner(
                "LIAISON PERDUE : reconnexion encore ${r.remainingS} s (essai ${r.attempts})" +
                    (if (r.lastError.isNotEmpty()) "\n${r.lastError}" else "") + "\nL'émission éventuelle est coupée par la station.",
                TX_RED,
            )
        }
        if (!rig.protocolOk) Banner("Version de protocole inconnue : réception et STOP seulement.", WARN)

        // Radio
        Text(Format.frequency(radio?.frequencyHz), fontSize = 34.sp, fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(radio?.mode ?: "—", style = MaterialTheme.typography.titleMedium)
            Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.titleMedium)
            if (radio != null && !radio.connected) Text("liaison CAT PERDUE", color = WARN)
        }

        // État de l'émission (station)
        if (ptt != null) {
            val text = when {
                mineTx -> "ÉMISSION EN COURS" + (ptt.totSeconds?.let { " — coupure dans ${Format.duration(it)}" } ?: "")
                ptt.other -> "${ptt.label} : autre client (${rig.state?.ptt?.owner ?: "?"})"
                else -> ptt.label
            }
            Banner(text, if (ptt.transmitting) TX_RED else MaterialTheme.colorScheme.secondaryContainer, big = true,
                textColor = if (ptt.transmitting) Color.White else MaterialTheme.colorScheme.onSecondaryContainer)
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

        // Émission
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = rig.armed, onCheckedChange = { RigHub.setArmed(it) }, enabled = connected && rig.protocolOk)
            Spacer(Modifier.padding(4.dp))
            Text("Émission autorisée" + if (!ui.micAllowed) " (micro refusé : réception seule)" else "")
        }
        val pttEnabled = connected && rig.protocolOk && ui.micAllowed && (mineTx || (ptt?.transmitting != true && rig.armed))
        Button(
            onClick = { if (debounce.pass()) RigHub.toggle() },
            enabled = pttEnabled,
            colors = if (mineTx) ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White) else ButtonDefaults.buttonColors(),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth().height(96.dp),
        ) {
            Text(
                when {
                    mineTx -> "FIN D'ÉMISSION"
                    ptt?.mine == true -> "COUPURE…"
                    ptt?.other == true -> "Émission d'un autre client"
                    !rig.armed -> "PTT (active « Émission autorisée »)"
                    else -> "ÉMETTRE"
                },
                fontSize = 22.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
            )
        }
        Button(
            onClick = { RigHub.stop() },
            enabled = connected,
            colors = ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White),
            modifier = Modifier.fillMaxWidth().height(56.dp),
        ) { Text("STOP", fontSize = 20.sp, fontWeight = FontWeight.Bold) }

        // Réception
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = ui.muted, onCheckedChange = { RigHub.setMuted(it) })
            Spacer(Modifier.padding(4.dp))
            Text("Sourdine (volume : touches du téléphone)")
        }

        OutlinedButton(onClick = onDisconnect) { Text("Déconnecter") }

        Text("Journal", style = MaterialTheme.typography.titleSmall)
        for (line in rig.log.takeLast(12).asReversed()) {
            Text(
                line.text,
                style = MaterialTheme.typography.bodySmall,
                color = when (line.level) {
                    LogLevel.BAD -> MaterialTheme.colorScheme.error
                    LogLevel.WARN -> WARN
                    LogLevel.INFO -> MaterialTheme.colorScheme.onSurface
                },
            )
        }
    }
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
