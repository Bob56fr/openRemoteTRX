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

/** Onglet Réglages : journal, préférences, sections du téléphone, outils de la station. */
@Composable
internal fun RigScope.SettingsTab(textPct: Int? = null, onTextPct: (Int) -> Unit = {}) {
            // Tablette : taille du texte (mémorisée sur l'appareil ; le PTT et le STOP gardent leur taille)
            if (textPct != null) Panel {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Taille du texte (tablette)", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    Text("$textPct %", style = MaterialTheme.typography.labelLarge)
                }
                Slider(
                    value = textPct.toFloat(), onValueChange = { onTextPct(com.rfdiy.openremotetrx.logic.ScreenLayouts.fontPct(Math.round(it))) },
                    valueRange = com.rfdiy.openremotetrx.logic.ScreenLayouts.FONT_MIN_PCT.toFloat()..com.rfdiy.openremotetrx.logic.ScreenLayouts.FONT_MAX_PCT.toFloat(),
                    steps = 5,
                )
            }
            // Journal
            Panel {
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
            }
            Panel {
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = keepScreenOn, onCheckedChange = {
                    keepScreenOn = it
                    prefs.edit().putBoolean("keep_screen_on", it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text("Écran toujours allumé pendant la connexion", style = MaterialTheme.typography.bodyMedium)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = keepTx, onCheckedChange = {
                    keepTx = it
                    prefs.edit().putBoolean("keep_tx_background", it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text("Rester en émission en quittant l'application (sinon : retour en réception)", style = MaterialTheme.typography.bodyMedium)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = drivingManual, onCheckedChange = {
                    drivingManual = it
                    prefs.edit().putBoolean(RigHub.PREF_DRIVING, it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text("Mode conduite (écran réduit, PTT tactile désactivé)", style = MaterialTheme.typography.bodyMedium)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = drivingAuto, onCheckedChange = {
                    drivingAuto = it
                    prefs.edit().putBoolean(RigHub.PREF_DRIVING_AUTO, it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text("Mode conduite automatique quand une voiture est connectée (Android Auto)", style = MaterialTheme.typography.bodyMedium)
            }
            }
            Panel { MicSection() }
            Panel { HeadsetSection(ui.headsetMic) }
            if (BuildConfig.CELL_INFO && rig.net != null) Panel { NetCellsSection() }   // absent de la version Google Play
            Panel { BeepsSection(rig.beeps, connected && rig.protocolOk) }
            rig.presence?.takeIf { it.switchShown }?.let { p -> Panel { ListenersSwitch(p) } }   // opérateur seulement
            if (hello?.offers("swr") == true && !listener) {                // mesure de TOS (opérateur, station 0.90.0+)
                OutlinedButton(onClick = { swrOpen = true }) { Text("Mesure de TOS de l'antenne") }
            }
            if (rig.net != null && !listener) {                             // sonde réseau (opérateur, station 0.106.0+)
                OutlinedButton(onClick = { netOpen = true }) { Text("Qualité du réseau (30 jours)") }
            }
            if (rig.host != null) {                                         // opérateur, station 0.83.0+
                OutlinedButton(onClick = { hostDialog = true; RigHub.hostInfo() }) { Text("Synthèse du matériel de la station") }
            }
            if (hello?.offers("bug_report") == true && !listener && connected) {   // comme la page ; jamais un visiteur
                OutlinedButton(onClick = { reportOpen = true }) { Text("Signaler un problème") }
            }
            OutlinedButton(onClick = onDisconnect) { Text("Déconnecter") }
}
