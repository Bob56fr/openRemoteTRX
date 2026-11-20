// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.Power
import com.rfdiy.openremotetrx.logic.Tr
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Allumage et extinction du poste à distance (fonction « power », lot P3) : même fonctionnement que la page.
 * STOP coupe dès l'APPUI ; maintenu 3 s, il ouvre la fenêtre « Se déconnecter » / « Arrêter le TRX à distance ».
 * Jamais en mode conduite ni dans Android Auto (l'écran de conduite a son propre STOP simple).
 */
internal object PowerUi {
    /** Fenêtre de STOP maintenu ouverte (partagée entre le bouton et l'hôte des fenêtres). */
    val stopHoldOpen = mutableStateOf(false)
}

/** Bouton STOP : retour en réception à l'APPUI (jamais retardé), maintien 3 s = fenêtre à deux choix. */
@Composable
internal fun RigScope.StopButton(modifier: Modifier, height: Dp, onStopped: () -> Unit) {
    val enabled = connected && !listener                                   // un visiteur ne coupe pas l'opérateur
    val haptic = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()
    var holdLeft by remember { mutableStateOf<Int?>(null) }
    val sub = holdLeft?.let { Tr.t("powerviews.hold_left", "seconds" to it) }
        ?: if (rig.stopHold.powerOff || hello?.offers("power") == true) Tr.t("powerviews.hold_power") else Tr.t("powerviews.hold_disconnect")
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = if (enabled) TX_COLOR else TX_COLOR.copy(alpha = 0.35f),
        contentColor = Color.White,
        modifier = modifier.padding(0.dp)
            .semantics {
                role = Role.Button
                onClick(label = "STOP") { if (enabled) { RigHub.stop(); onStopped() }; enabled }
            }
            .pointerInput(enabled) {
                if (!enabled) return@pointerInput
                awaitEachGesture {
                    awaitFirstDown(requireUnconsumed = false)
                    RigHub.stop()                                          // STOP tout de suite, à l'appui
                    onStopped()
                    val job = scope.launch {
                        for (left in (Power.STOP_HOLD_MS / 1000).toInt() downTo 1) { holdLeft = left; delay(1000) }
                        holdLeft = null
                        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                        PowerUi.stopHoldOpen.value = true
                    }
                    // Jusqu'au relâchement du doigt, MÊME s'il « sort » du bouton parce que l'écran bouge (voyants qui
                    // arrivent après l'allumage du poste : défaut vu sur la page le 2026-11-20)
                    do {
                        val event = awaitPointerEvent()
                    } while (event.changes.any { it.pressed })
                    job.cancel()
                    holdLeft = null
                }
            },
    ) {
        Box(Modifier.padding(vertical = 4.dp).then(Modifier), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("STOP", fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(sub, fontSize = 10.sp, textAlign = TextAlign.Center)
            }
        }
    }
}

/** Bandeau « POSTE ÉTEINT » et bouton « Allumer le poste » (visiteur : texte seul). */
@Composable
internal fun RigScope.PowerBannerRow() {
    val banner = rig.powerBanner ?: return
    Surface(color = TX_COLOR, contentColor = Color.White, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(banner.text, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            if (banner.canPowerOn || banner.text == Tr.t("power.banner_running")) {
                OutlinedButton(onClick = { RigHub.powerOn() }, enabled = banner.canPowerOn) {
                    Text(Tr.t("powerviews.power_on"), color = Color.White)
                }
            }
        }
    }
}

/** Fenêtres de l'alimentation : STOP maintenu (deux choix puis confirmation) et « Allumage du TRX ». */
@Composable
internal fun RigScope.PowerDialogs() {
    var stopHoldOpen by PowerUi.stopHoldOpen
    if (stopHoldOpen) StopHoldDialog { stopHoldOpen = false; RigHub.clearPowerOffNotice() }
    rig.powerDialog?.let { view ->
        if (view.autoCloseMs > 0) LaunchedEffect(view.text) { delay(view.autoCloseMs); RigHub.powerHide() }
        AlertDialog(
            onDismissRequest = { if (view.canHide) RigHub.powerHide() },
            title = { Text(view.title) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (line in view.lines) {
                        val (mark, color) = when (line.status) {
                            "ok" -> "✓" to Page.SUCCES
                            "error" -> "✗" to Page.TX
                            "running" -> "…" to MaterialTheme.colorScheme.onSurface
                            else -> "·" to Page.TEXTE_2
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(mark, color = color, fontWeight = FontWeight.Bold)
                            Column(Modifier.weight(1f)) {
                                Text(line.label, color = if (line.status == "pending") Page.TEXTE_2 else color,
                                     fontWeight = if (line.status == "error") FontWeight.Bold else FontWeight.Normal)
                                if (line.detail.isNotEmpty()) Text(line.detail, style = MaterialTheme.typography.bodySmall, color = color)
                            }
                        }
                    }
                    Text(view.text, style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                when {
                    view.canRetry -> Button(onClick = { RigHub.powerOn() }) { Text(Tr.t("common.retry")) }
                    view.canHide -> Button(onClick = { RigHub.powerHide() }) { Text(Tr.t("common.hide")) }
                    else -> Button(onClick = { RigHub.powerHide() }) { Text(Tr.t("common.close")) }
                }
            },
            dismissButton = { if (view.canContinue) TextButton(onClick = { RigHub.powerHide() }) { Text(Tr.t("powerviews.continue_without")) } },
        )
    }
}

@Composable
private fun RigScope.StopHoldDialog(onClose: () -> Unit) {
    var confirming by remember { mutableStateOf(false) }
    var sent by remember { mutableStateOf(false) }
    val choices = rig.stopHold
    LaunchedEffect(confirming, sent) { if (!sent) { delay(Power.STOP_HOLD_AUTO_CANCEL_MS); onClose() } }   // Annuler après 15 s
    if (sent && rig.powerBanner != null && rig.powerOffNotice.isEmpty()) { LaunchedEffect(Unit) { onClose() }; return }
    val refused = sent && rig.powerOffNotice.isNotEmpty()
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text(when { refused -> Tr.t("powerviews.off_refused"); confirming -> Power.CONFIRM_TITLE; else -> Tr.t("powerviews.hold_question") }) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                when {
                    refused -> Text(rig.powerOffNotice)
                    sent -> Text(Tr.t("powerviews.off_sent"))
                    confirming -> Text(Power.CONFIRM_TEXT)
                    else -> {
                        Text(Tr.t("powerviews.already_rx"), style = MaterialTheme.typography.bodySmall)
                        OutlinedButton(onClick = { onClose(); RigHub.stop(); onDisconnect() }, modifier = Modifier.fillMaxWidth()) {
                            Text(Tr.t("powerviews.disconnect"))
                        }
                        OutlinedButton(onClick = { confirming = true }, enabled = choices.powerOff, modifier = Modifier.fillMaxWidth()) {
                            Text(Tr.t("powerviews.power_off_remote"))
                        }
                        if (choices.powerReason.isNotEmpty()) Text(choices.powerReason, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
                    }
                }
            }
        },
        confirmButton = {
            if (confirming && !sent) Button(onClick = { sent = true; RigHub.powerOff() },
                colors = ButtonDefaults.buttonColors(containerColor = TX_COLOR, contentColor = Color.White)) { Text(Tr.t("powerviews.power_off")) }
        },
        dismissButton = { Button(onClick = onClose) { Text(if (refused) Tr.t("common.close") else Tr.t("common.cancel")) } },
    )
}

private val TX_COLOR = Page.TX
