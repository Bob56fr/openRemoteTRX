// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Bouton compact (bandes, modes, fonctions du poste, réglages des spectres) : sa largeur suit le texte, sans la marge
 * des puces Material (demande de l'utilisateur). Appui = action ; appui long facultatif (réglage fin, signalé par « ⋯ »).
 * Hauteur 30 dp : encore assez grande pour le doigt.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CompactChip(
    label: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    selected: Boolean = false,
    onLongClick: (() -> Unit)? = null,
    dot: Color? = null,
    help: String? = null,                    // aide courte (logic/Help.kt) par appui long, si l'appui long n'a pas d'autre rôle
) {
    val colors = MaterialTheme.colorScheme
    val s = LocalUiScale.current
    val long = onLongClick ?: help?.let { text -> { HelpPopup.show(label, text) } }
    Box {
    Surface(
        shape = RoundedCornerShape(7.dp),
        color = if (selected) colors.secondaryContainer else Color.Transparent,
        border = BorderStroke(1.dp, if (selected) colors.secondaryContainer else colors.outline.copy(alpha = 0.7f)),
        modifier = Modifier.height(30.dp * s).defaultMinSize(minWidth = 36.dp * s)
            .combinedClickable(enabled = enabled, onClick = onClick, onLongClick = long),
    ) {
        Box(Modifier.padding(horizontal = 8.dp * s), contentAlignment = Alignment.Center) {
            Text(
                label + if (onLongClick != null) " ⋯" else "",
                style = MaterialTheme.typography.labelLarge,
                color = when {
                    !enabled -> colors.onSurface.copy(alpha = 0.38f)
                    selected -> colors.onSecondaryContainer
                    else -> colors.onSurface
                },
            )
        }
    }
    // Pastille de coin (spots du Cluster DX sur la bande), comme la page
    if (dot != null) Box(Modifier.align(Alignment.TopEnd).offset(x = 3.dp, y = (-3).dp).size(9.dp).background(dot, CircleShape))
    }
}
