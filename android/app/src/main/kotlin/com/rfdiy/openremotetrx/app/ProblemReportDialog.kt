// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.res.Configuration
import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.ProblemReport

/**
 * « Signaler un problème » (lot A3, comme la page) : description, puis le texte COMPLET montré avant l'envoi ; rien ne
 * part sans « Envoyer ». La station range le rapport et le joint au rapport de dépannage (TRX Console, menu 8).
 */
@Composable
fun ProblemReportDialog(onClose: () -> Unit) {
    val report by RigHub.problemText.collectAsState()
    var description by rememberSaveable { mutableStateOf("") }
    val config = LocalConfiguration.current
    val device = "${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}"
    val screen = "${config.screenWidthDp}×${config.screenHeightDp} dp, " +
        if (config.orientation == Configuration.ORIENTATION_LANDSCAPE) "paysage" else "portrait"
    DisposableEffect(Unit) { onDispose { RigHub.problemReportClosed() } }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Signaler un problème") },
        text = {
            Column(Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                val text = report
                if (text == null) {
                    Text("Décris ce qui s'est passé (ce que tu faisais, ce que tu attendais, ce qui est arrivé). " +
                        "Le rapport te sera montré en entier avant l'envoi.", style = MaterialTheme.typography.bodySmall)
                    OutlinedTextField(description, { description = it.take(ProblemReport.DESCRIPTION_MAX) },
                        modifier = Modifier.fillMaxWidth(), minLines = 4, label = { Text("Ce qui s'est passé") })
                } else {
                    Text("Voici EXACTEMENT ce qui sera envoyé à la station (aucun mot de passe) :", style = MaterialTheme.typography.bodySmall)
                    Text(text, fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 14.sp)
                }
            }
        },
        confirmButton = {
            val text = report
            if (text == null) {
                TextButton(onClick = { RigHub.prepareProblemReport(description, device, screen) }) { Text("Voir le rapport") }
            } else {
                TextButton(onClick = { RigHub.sendProblemReport(text); onClose() }) { Text("Envoyer") }
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Annuler") } },
    )
}
