// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.content.res.Configuration
import android.os.SystemClock
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import com.rfdiy.openremotetrx.logic.BigPtt
import com.rfdiy.openremotetrx.logic.BreizhLevel
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
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
import androidx.compose.ui.graphics.Path
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
import com.rfdiy.openremotetrx.core.VoiceHub
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.logic.Band
import com.rfdiy.openremotetrx.logic.Controls
import com.rfdiy.openremotetrx.logic.Driving
import com.rfdiy.openremotetrx.logic.DrivingReason
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.HfScope
import com.rfdiy.openremotetrx.logic.Indicators
import com.rfdiy.openremotetrx.logic.bandDots
import com.rfdiy.openremotetrx.logic.clusterView
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.LogLevel
import com.rfdiy.openremotetrx.logic.Meter
import com.rfdiy.openremotetrx.logic.Radio
import com.rfdiy.openremotetrx.logic.RigSession
import com.rfdiy.openremotetrx.logic.RigState
import com.rfdiy.openremotetrx.protocol.Hello
import java.util.Locale
import kotlin.math.roundToInt
import android.content.SharedPreferences
import androidx.compose.runtime.MutableLongState
import androidx.compose.runtime.MutableState

private val TX_RED = Page.TX                     // couleurs de la page web (client.css)
private val WARN = Page.ALERTE
private val SQL_OPEN = Page.SUCCES
private val HEALTH = mapOf("green" to Page.SUCCES, "orange" to Page.ALERTE, "red" to Page.TX, "off" to Page.TEXTE_2)
private val DOT_COLORS = mapOf(1 to Page.TEXTE_2, 2 to Page.ALERTE, 3 to Page.TX)    // pastilles des bandes (page : lvl1..3)

/** Onglet Mémoires : mémoires partagées de la station et Cluster DX. */
@Composable
internal fun RigScope.MemoriesTab() {
            MiniDisplay(rig, shownHz, mineTx)
            // Mémoires partagées de la station
            if (hello?.offers("memories") == true || rig.memories.isNotEmpty()) Panel {
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

            // Cluster DX : état des flux reçus par la station (comme la page)
            rig.clusterView(System.currentTimeMillis())?.let { cv -> Panel {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Box(Modifier.size(10.dp).background(HEALTH[cv.health] ?: Page.TEXTE_2, CircleShape))
                    Text("Cluster DX : " + cv.title, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                    TextButton(onClick = { spotsDialog = true }) { Text("Tout afficher") }
                }
                for (line in cv.lines) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Box(Modifier.size(8.dp).background(HEALTH[line.dot] ?: Color.Transparent, CircleShape))
                        Text(line.text, style = MaterialTheme.typography.bodySmall)
                    }
                }
                if (cv.stale) Text(cv.staleText, color = WARN, style = MaterialTheme.typography.bodySmall)
            } }
}
