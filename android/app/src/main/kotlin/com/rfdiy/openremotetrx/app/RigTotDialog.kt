// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.Tr

/** TOT du poste lu sur OFF à la connexion (docs/tot-poste-cahier-des-charges.md, lot TP3), comme la page : rappel
 *  seulement, l'émission n'est jamais bloquée. « Quitter » = déconnexion (la station est en réception). Cette fenêtre
 *  vit dans l'écran normal : en mode conduite (écran réduit), elle attend le retour à l'écran du téléphone. */
@Composable
internal fun RigScope.RigTotDialog() {
    if (!rig.rigTotOff) return
    AlertDialog(
        onDismissRequest = {},                                 // un choix explicite est demandé
        title = { Text(Tr.t("rigtotdialog.title")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(Tr.t("rigtotdialog.text"))
                Text(Tr.t("rigtotdialog.how"), style = MaterialTheme.typography.bodySmall)
                Text("ORT-5041", style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)   // i18n-ok : code
            }
        },
        confirmButton = {
            Button(onClick = { RigHub.dismissRigTot() }) { Text(Tr.t("rigtotdialog.continue")) }
        },
        dismissButton = {
            OutlinedButton(onClick = { RigHub.dismissRigTot(); onDisconnect() }) { Text(Tr.t("rigtotdialog.quit")) }
        },
    )
}
