// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.logic.Driving
import com.rfdiy.openremotetrx.logic.DrivingReason
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.Radio

private val TX_RED = Page.TX

/**
 * Écran réduit du mode conduite : lisible d'un coup d'œil, AUCUN PTT tactile ; STOP et sourdine en très grand.
 * Sortie : le réglage (mode à la main) ou « Je suis passager » (appui long, voiture connectée).
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun DrivingScreen(ui: RigUi, reason: DrivingReason, modifier: Modifier, onLeaveManual: () -> Unit) {
    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val connected = rig.status == LinkStatus.CONNECTED
    val mineTx = ptt?.mine == true && ptt.transmitting
    Column(
        modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(Driving.label(reason), color = Page.TEXTE_2, style = MaterialTheme.typography.labelLarge)
        Surface(
            shape = RoundedCornerShape(18.dp), color = if (ptt?.transmitting == true) Page.TX_FOND else Page.INSTRUMENT,
            border = BorderStroke(2.dp, if (ptt?.transmitting == true) TX_RED else Page.LIGNE), contentColor = Page.TEXTE,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(Modifier.padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    when {
                        !connected -> when (rig.status) {
                            LinkStatus.RECONNECTING -> "RECONNEXION…"
                            LinkStatus.CONNECTING -> "CONNEXION…"
                            else -> "DÉCONNECTÉ"
                        }
                        mineTx -> "ÉMISSION" + (ptt?.totSeconds?.let { " " + Format.duration(it) } ?: "")
                        ptt?.transmitting == true -> "ÉMISSION (autre)"
                        else -> "RÉCEPTION"
                    },
                    fontSize = 30.sp, fontWeight = FontWeight.Bold,
                    color = if (ptt?.transmitting == true) TX_RED else Page.SUCCES,
                )
                Text(Radio.formatIcom(radio?.frequencyHz), fontSize = 40.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                Text("${Radio.modeLabel(radio?.mode)}   ${Format.sMeter(radio?.strengthDb)}", fontSize = 22.sp)
                ui.station?.name?.let { Text(it, color = Page.TEXTE_2, style = MaterialTheme.typography.bodyMedium) }
            }
        }
        Button(
            onClick = { RigHub.stop() }, enabled = connected,
            colors = ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White),
            shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth().height(110.dp),
        ) { Text("STOP", fontSize = 40.sp, fontWeight = FontWeight.Bold) }
        OutlinedButton(onClick = { RigHub.setMuted(!ui.muted) }, modifier = Modifier.fillMaxWidth().height(64.dp)) {
            Text(if (ui.muted) "Remettre le son" else "Couper le son", fontSize = 20.sp)
        }
        Text(Driving.PTT_HINT, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall, textAlign = TextAlign.Center)
        Box(Modifier.weight(1f))
        if (reason == DrivingReason.CAR) {
            Surface(
                shape = RoundedCornerShape(12.dp), color = Color.Transparent, border = BorderStroke(1.dp, Page.LIGNE),
                modifier = Modifier.fillMaxWidth().height(48.dp).combinedClickable(onClick = {}, onLongClick = { RigHub.setPassenger(true) }),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("Je suis passager (appui long)", color = Page.TEXTE_2)
                }
            }
        } else {
            OutlinedButton(onClick = onLeaveManual, modifier = Modifier.fillMaxWidth()) { Text("Quitter le mode conduite") }
        }
    }
}
