// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.FreeDvLevel
import com.rfdiy.openremotetrx.logic.FreeDvView

/** Couleur du voyant FDV et du texte d'état (vert, orange, rouge, gris), comme la page. */
fun freedvColor(level: FreeDvLevel): Color = when (level) {
    FreeDvLevel.OK -> Page.SUCCES
    FreeDvLevel.WARN -> Page.ALERTE
    FreeDvLevel.BAD -> Page.TX
    FreeDvLevel.OFF -> Page.TEXTE_2
}

/**
 * FreeDV RADE V1 en réception (station 0.122.0+) : état, mode de la station (opérateurs seulement, refusé pendant
 * l'émission), 10 derniers indicatifs, 10 dernières séquences notées. Comme la rubrique « FreeDV » de la page. La voix
 * décodée arrive par le son normal de la station : rien à régler sur le téléphone.
 */
@Composable
fun FreeDvDialog(view: FreeDvView, notice: String, operator: Boolean, transmitting: Boolean, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        title = { Text("FreeDV") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "FreeDV RADE V1 : voix numérique décodée par la station. En mode FreeDV, tous les connectés entendent la voix " +
                        "décodée à la place du son du poste, et du silence tant qu'aucun signal FreeDV n'est accroché. Le poste reste " +
                        "réglé comme il l'est : FreeDV se reçoit en BLU supérieure (USB ou PKTUSB), avec un filtre d'au moins 2,4 kHz.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Text(view.text, color = freedvColor(view.level), fontWeight = FontWeight.Bold)
                if (view.details.isNotEmpty()) Text(view.details, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                if (operator) {
                    OutlinedButton(onClick = { RigHub.freedvSet(!view.on) }, enabled = !transmitting) {
                        Text(if (view.on) "Revenir au son du poste" else "Passer en FreeDV")
                    }
                    if (transmitting) Text("Refusé pendant une émission.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                    if (notice.isNotEmpty()) Text(notice, color = Page.ALERTE, style = MaterialTheme.typography.bodySmall)
                }
                Text("Indicatifs décodés", style = MaterialTheme.typography.titleSmall)
                if (view.calls.isEmpty()) Text("aucun pour l'instant", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                for (c in view.calls) {
                    Text(c.callsign + (if (c.snrText.isNotEmpty()) " · ${c.snrText}" else "") + (if (c.whenText.isNotEmpty()) " · ${c.whenText}" else ""),
                        style = MaterialTheme.typography.bodyMedium)
                }
                Text("Séquences reçues", style = MaterialTheme.typography.titleSmall)
                Text(
                    "Qualité probable à l'écoute, de 1 à 5 étoiles : SNR médian pendant la synchro (5 dès +6 dB, 4 dès +3, 3 dès 0, " +
                        "2 dès −3), une étoile de moins si la synchro tient moins de 80 % du temps ou se perd souvent ; 2 au plus sous " +
                        "3 s. La station n'enregistre pas la voix.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                if (view.sequences.isEmpty()) Text("aucune pour l'instant", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                for (s in view.sequences) {
                    Text(buildAnnotatedString {
                        withStyle(SpanStyle(color = if (s.note >= 4) Page.SUCCES else Page.ALERTE)) { append(s.stars) }
                        append(" " + s.duration + (if (s.callsigns.isNotEmpty()) " · ${s.callsigns}" else "") +
                            (if (s.whenText.isNotEmpty()) " · ${s.whenText}" else ""))
                    }, style = MaterialTheme.typography.bodyMedium)
                    if (s.detail.isNotEmpty()) Text(s.detail, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
    )
}
