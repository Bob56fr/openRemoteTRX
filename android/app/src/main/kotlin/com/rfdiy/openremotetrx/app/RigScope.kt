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

/**
 * Ce que voient les onglets de l'écran de la station (découpage de RigScreen.kt, étape 148) : les MÊMES noms qu'avant
 * (états partagés, valeurs de l'instant, gestes d'accord), pour que le corps des onglets soit repris tel quel. Les états
 * restent créés par RigScreen, au même endroit (rotation, retour du mode conduite : comportement inchangé). Prépare la
 * version tablette (lot A5) : deux onglets côte à côte.
 */
internal class RigScope(
    val ui: RigUi,
    val prefs: SharedPreferences,
    val onDisconnect: () -> Unit,
    keepScreenOnS: MutableState<Boolean>,
    keepTxS: MutableState<Boolean>,
    drivingManualS: MutableState<Boolean>,
    drivingAutoS: MutableState<Boolean>,
    bigPttRequestedS: MutableState<Boolean>,
    pendingHzS: MutableState<Long?>,
    pendingAtS: MutableLongState,
    stepIndexS: MutableState<Int>,
    entryS: MutableState<Boolean>,
    showLogS: MutableState<Boolean>,
    levelsDialogS: MutableState<Boolean>,
    showWaterfallS: MutableState<Boolean>,
    bandsPrefS: MutableState<String>,
    bandsDialogS: MutableState<Boolean>,
    memoryDialogS: MutableState<MemoryEdit?>,
    spotsDialogS: MutableState<Boolean>,
    presenceDialogS: MutableState<Boolean>,
    selcallDialogS: MutableState<Boolean>,
    spatialDialogS: MutableState<Boolean>,
    breizhDialogS: MutableState<Boolean>,
    freedvDialogS: MutableState<Boolean>,
    hostDialogS: MutableState<Boolean>,
    reportOpenS: MutableState<Boolean>,
    swrOpenS: MutableState<Boolean>,
    netOpenS: MutableState<Boolean>,
    netDialogS: MutableState<Boolean>,
    miniWfS: MutableState<Boolean>,
    tabS: MutableState<Tab>,
    squelchDragS: MutableState<Float?>,
    offsetDragS: MutableState<Float?>,
) {
    var keepScreenOn by keepScreenOnS
    var keepTx by keepTxS
    var drivingManual by drivingManualS
    var drivingAuto by drivingAutoS
    var bigPttRequested by bigPttRequestedS
    var pendingHz by pendingHzS
    var pendingAt by pendingAtS
    var stepIndex by stepIndexS
    var entry by entryS
    var showLog by showLogS
    var levelsDialog by levelsDialogS
    var showWaterfall by showWaterfallS
    var bandsPref by bandsPrefS
    var bandsDialog by bandsDialogS
    var memoryDialog by memoryDialogS
    var spotsDialog by spotsDialogS
    var presenceDialog by presenceDialogS
    var selcallDialog by selcallDialogS
    var spatialDialog by spatialDialogS
    var breizhDialog by breizhDialogS
    var freedvDialog by freedvDialogS
    var hostDialog by hostDialogS
    var reportOpen by reportOpenS
    var swrOpen by swrOpenS
    var netOpen by netOpenS
    var netDialog by netDialogS
    var miniWf by miniWfS
    var tab by tabS
    var squelchDrag by squelchDragS
    var offsetDrag by offsetDragS

    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val hello = rig.hello
    val connected = rig.status == LinkStatus.CONNECTED
    // Compte VISITEUR : réception seule, toutes les commandes inertes (la session n'envoie rien, la station refuserait)
    val listener = rig.listener
    // Réglages du poste : seulement en réception (la station les refuse pendant l'émission, comme la page).
    val canSet = connected && rig.protocolOk && !listener && (rig.state?.ptt?.state ?: "RX") == "RX"
    val mineTx = ptt != null && ptt.mine && ptt.transmitting
    val pendingLive = pendingHz?.takeIf { it != radio?.frequencyHz && SystemClock.elapsedRealtime() - pendingAt < 2500 }
    val shownHz = pendingLive ?: radio?.frequencyHz
    val step = Radio.STEPS_HZ[stepIndex]

    fun go(hz: Long) {
        pendingHz = hz
        pendingAt = SystemClock.elapsedRealtime()
        RigHub.setFrequency(hz)
    }

    fun tune(steps: Int) {
        go(Radio.nudge(shownHz ?: return, step, steps))
    }

    @JvmName("changeMiniWf")                  // le setter de `miniWf` porte déjà le nom JVM setMiniWf
    fun setMiniWf(on: Boolean) { miniWf = on; prefs.edit().putBoolean("mini_wf", on).apply() }
}
