// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import com.rfdiy.openremotetrx.logic.FreeDvActivities
import com.rfdiy.openremotetrx.logic.FreeDvActivityView
import com.rfdiy.openremotetrx.logic.FreeDvLevel
import com.rfdiy.openremotetrx.logic.FreeDvView
import com.rfdiy.openremotetrx.logic.Tr

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
fun FreeDvDialog(view: FreeDvView, notice: String, operator: Boolean, transmitting: Boolean,
                 activity: FreeDvActivityView? = null, activityNotice: String = "", onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.close")) } },
        title = { Text("FreeDV") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    Tr.t("freedvdialog.intro"),
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Text(view.text, color = freedvColor(view.level), fontWeight = FontWeight.Bold)
                if (view.details.isNotEmpty()) Text(view.details, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                if (operator) {
                    OutlinedButton(onClick = { RigHub.freedvSet(!view.on) }, enabled = !transmitting) {
                        Text(if (view.on) Tr.t("freedvdialog.back_to_rig") else Tr.t("freedvdialog.switch_on"))
                    }
                    if (transmitting) Text(Tr.t("freedvdialog.refused_tx"), color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                    if (notice.isNotEmpty()) Text(notice, color = Page.ALERTE, style = MaterialTheme.typography.bodySmall)
                }
                if (activity != null) FreeDvActivitySection(activity, activityNotice, operator)
                Text(Tr.t("freedvdialog.calls_title"), style = MaterialTheme.typography.titleSmall)
                if (view.calls.isEmpty()) Text(Tr.t("freedvdialog.calls_none"), color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                for (c in view.calls) {
                    Text(c.callsign + (if (c.snrText.isNotEmpty()) " · ${c.snrText}" else "") + (if (c.whenText.isNotEmpty()) " · ${c.whenText}" else ""),
                        style = MaterialTheme.typography.bodyMedium)
                }
                Text(Tr.t("freedvdialog.sequences_title"), style = MaterialTheme.typography.titleSmall)
                Text(
                    Tr.t("freedvdialog.sequences_help"),
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                if (view.sequences.isEmpty()) Text(Tr.t("freedvdialog.sequences_none"), color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
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

/**
 * Activité FreeDV (module « freedv_activity ») : stations actives par fréquence, d'après FreeDV Reporter lu par la
 * station en observateur. Comme la liste de la rubrique FreeDV de la page : un OPÉRATEUR touche une ligne = QSY
 * IMMÉDIAT (USB si besoin ; refusé pendant l'émission) ; un visiteur la lit seulement.
 */
@Composable
private fun FreeDvActivitySection(a: FreeDvActivityView, notice: String, operator: Boolean) {
    Text(Tr.t("freedvdialog.activity_title"), style = MaterialTheme.typography.titleSmall)
    Text(
        if (operator) Tr.t("freedvdialog.activity_intro_operator") else Tr.t("freedvdialog.activity_intro"),
        color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
    )
    Text(a.text, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
    if (notice.isNotEmpty()) Text(notice, color = Page.ALERTE, style = MaterialTheme.typography.bodySmall)
    if (a.rows.isEmpty()) {
        Text(if (a.status == "ok") FreeDvActivities.EMPTY else "—", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
    }
    for (r in a.rows) {
        val rowModifier = Modifier.fillMaxWidth().let { if (operator) it.clickable { RigHub.freedvActivityQsy(r.hz) } else it }
        Column(rowModifier.padding(vertical = 3.dp)) {
            Text(buildAnnotatedString {
                withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = if (r.here) Page.SUCCES else Color.Unspecified)) {
                    append(r.freqText + (if (r.here) FreeDvActivities.HERE else ""))
                }
                append(Tr.t("freedvdialog.note", "note" to r.noteText))
            }, style = MaterialTheme.typography.bodyMedium)
            Text(buildAnnotatedString {
                append(Tr.t("freedvdialog.transmitting"))
                if (r.tx.isEmpty()) append("—")
                r.tx.forEachIndexed { i, t ->
                    if (i > 0) append(", ")
                    if (t.on) withStyle(SpanStyle(color = Page.SUCCES, fontWeight = FontWeight.Bold)) { append(t.text) } else append(t.text)
                }
            }, style = MaterialTheme.typography.bodySmall)
            Text(Tr.t("freedvdialog.receiving", "list" to r.rx.joinToString(", ").ifEmpty { "—" }), color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
        }
    }
}
