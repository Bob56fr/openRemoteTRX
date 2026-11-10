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
import com.rfdiy.openremotetrx.logic.Friends
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
import com.rfdiy.openremotetrx.logic.ScreenLayout
import com.rfdiy.openremotetrx.logic.ScreenLayouts
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

/**
 * Station connectée. Tout ce qui s'affiche vient de l'état publié par la station (RigUi.rig) : l'émission n'est
 * jamais supposée après un appui. En bas, toujours visibles : « Émission autorisée », PTT (appui simple) et STOP.
 */
@Composable
fun RigScreen(ui: RigUi, modifier: Modifier, onDisconnect: () -> Unit) {
    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val hello = rig.hello
    val connected = rig.status == LinkStatus.CONNECTED
    // Compte VISITEUR : réception seule, toutes les commandes inertes (la session n'envoie rien, la station refuserait)
    val listener = rig.listener
    // Réglages du poste : seulement en réception (la station les refuse pendant l'émission, comme la page).
    val canSet = connected && rig.protocolOk && !listener && (rig.state?.ptt?.state ?: "RX") == "RX"
    val context = LocalContext.current
    val voice by VoiceHub.ui.collectAsState()
    val spatial by com.rfdiy.openremotetrx.core.SpatialHub.ui.collectAsState()
    val prefs = remember { context.getSharedPreferences("ui", Context.MODE_PRIVATE) }
    val keepScreenOnS = remember { mutableStateOf(prefs.getBoolean("keep_screen_on", true)) }
    var keepScreenOn by keepScreenOnS
    val keepTxS = remember { mutableStateOf(prefs.getBoolean("keep_tx_background", false)) }
    var keepTx by keepTxS
    // Mode conduite (logic.Driving) : réglage, ou automatique quand une voiture est connectée (Android Auto, mode voiture)
    val drivingManualS = remember { mutableStateOf(prefs.getBoolean(RigHub.PREF_DRIVING, false)) }
    var drivingManual by drivingManualS
    val drivingAutoS = remember { mutableStateOf(prefs.getBoolean(RigHub.PREF_DRIVING_AUTO, true)) }
    var drivingAuto by drivingAutoS
    val carMode = (LocalConfiguration.current.uiMode and Configuration.UI_MODE_TYPE_MASK) == Configuration.UI_MODE_TYPE_CAR
    val driving = Driving.reason(drivingManual, drivingAuto, ui.carConnected || carMode, ui.passenger)
    if (Driving.active(driving)) {
        DrivingScreen(ui, driving, modifier) { drivingManual = false; prefs.edit().putBoolean(RigHub.PREF_DRIVING, false).apply() }
        return
    }
    // Écran allumé tant que la station est affichée (comme la page) ; l'écoute continue de toute façon écran éteint.
    val view = LocalView.current
    DisposableEffect(keepScreenOn, rig.status) {
        view.keepScreenOn = keepScreenOn && rig.status != LinkStatus.DISCONNECTED
        onDispose { view.keepScreenOn = false }
    }
    val mineTx = ptt != null && ptt.mine && ptt.transmitting
    val debounce = remember { Debounce() }
    // Gros PTT rond (logic.BigPtt) : masqué par défaut, appui long sur le PTT pour l'afficher, STOP pour le masquer
    val bigPttRequestedS = rememberSaveable { mutableStateOf(false) }
    var bigPttRequested by bigPttRequestedS
    LaunchedEffect(connected) { if (!connected) bigPttRequested = false }
    // Fréquence demandée : affichée et prise comme base des crans jusqu'à confirmation du poste (page : PENDING_MAX_MS).
    // L'état de la station arrive plusieurs fois par seconde : l'affichage revient seul à la fréquence du poste.
    val pendingHzS = remember { mutableStateOf<Long?>(null) }
    var pendingHz by pendingHzS
    val pendingAtS = remember { mutableLongStateOf(0L) }
    var pendingAt by pendingAtS
    val stepIndexS = rememberSaveable { mutableStateOf(Radio.STEPS_HZ.indexOf(1000L)) }
    var stepIndex by stepIndexS
    val entryS = remember { mutableStateOf(false) }
    var entry by entryS
    val showLogS = rememberSaveable { mutableStateOf(false) }
    var showLog by showLogS
    val levelsDialogS = remember { mutableStateOf(false) }
    var levelsDialog by levelsDialogS
    val showWaterfallS = rememberSaveable { mutableStateOf(false) }
    var showWaterfall by showWaterfallS
    val bandsPrefS = remember { mutableStateOf(prefs.getString("bands", "") ?: "") }
    var bandsPref by bandsPrefS
    val bandsDialogS = remember { mutableStateOf(false) }
    var bandsDialog by bandsDialogS
    val memoryDialogS = remember { mutableStateOf<MemoryEdit?>(null) }
    var memoryDialog by memoryDialogS
    val spotsDialogS = remember { mutableStateOf(false) }
    var spotsDialog by spotsDialogS
    val presenceDialogS = remember { mutableStateOf(false) }
    var presenceDialog by presenceDialogS
    val selcallDialogS = remember { mutableStateOf(false) }
    var selcallDialog by selcallDialogS
    val spatialDialogS = remember { mutableStateOf(false) }
    var spatialDialog by spatialDialogS
    val breizhDialogS = remember { mutableStateOf(false) }
    var breizhDialog by breizhDialogS
    val hostDialogS = remember { mutableStateOf(false) }
    var hostDialog by hostDialogS
    val reportOpenS = remember { mutableStateOf(false) }                     // « Signaler un problème » (lot A3)
    var reportOpen by reportOpenS
    val swrOpenS = rememberSaveable { mutableStateOf(false) }                // écran de la mesure de TOS
    var swrOpen by swrOpenS
    val netOpenS = rememberSaveable { mutableStateOf(false) }                // écran « Qualité du réseau »
    var netOpen by netOpenS
    val netDialogS = remember { mutableStateOf(false) }                      // détail de la liaison
    var netDialog by netDialogS
    val miniWfS = remember { mutableStateOf(prefs.getBoolean("mini_wf", true)) }     // petit waterfall de l'onglet Station
    var miniWf by miniWfS
    fun setMiniWf(on: Boolean) { miniWf = on; prefs.edit().putBoolean("mini_wf", on).apply() }
    val tabS = rememberSaveable { mutableStateOf(Tab.STATION) }
    var tab by tabS
    val squelchDragS = remember { mutableStateOf<Float?>(null) }        // valeur suivie pendant que le doigt règle
    var squelchDrag by squelchDragS
    val offsetDragS = remember { mutableStateOf<Float?>(null) }
    var offsetDrag by offsetDragS
    val pendingLive = pendingHz?.takeIf { it != radio?.frequencyHz && SystemClock.elapsedRealtime() - pendingAt < 2500 }
    val shownHz = pendingLive ?: radio?.frequencyHz
    val step = Radio.STEPS_HZ[stepIndex]
    val scope = RigScope(ui, prefs, onDisconnect, keepScreenOnS, keepTxS, drivingManualS, drivingAutoS, bigPttRequestedS, pendingHzS, pendingAtS, stepIndexS, entryS, showLogS, levelsDialogS, showWaterfallS, bandsPrefS, bandsDialogS, memoryDialogS, spotsDialogS, presenceDialogS, selcallDialogS, spatialDialogS, breizhDialogS, hostDialogS, reportOpenS, swrOpenS, netOpenS, netDialogS, miniWfS, tabS, squelchDragS, offsetDragS)

    fun go(hz: Long) {
        pendingHz = hz
        pendingAt = SystemClock.elapsedRealtime()
        RigHub.setFrequency(hz)
    }

    fun tune(steps: Int) {
        go(Radio.nudge(shownHz ?: return, step, steps))
    }

    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    val config = LocalConfiguration.current
    val wide = ScreenLayouts.of(config.screenWidthDp, config.screenHeightDp) == ScreenLayout.WIDE   // tablette (lot A5)
    if (landscape && !wide && HfScope.configured(hello) && rig.status != LinkStatus.DISCONNECTED) {
        LandscapeScope(ui, canSet, onTune = { go(it) }, modifier)
        return
    }

    // Rediffusion : durée permise par la station (null = non accordée) ; diffusion suivie sur l'onglet Station
    LaunchedEffect(hello?.replay?.maxS, listener) { com.rfdiy.openremotetrx.core.ReplayHub.setMax(if (listener) null else hello?.replay?.maxS) }
    val replay by com.rfdiy.openremotetrx.core.ReplayHub.ui.collectAsState()
    val pttEnabled = connected && rig.protocolOk && ui.micAllowed && !listener && (mineTx || (ptt?.transmitting != true && rig.armed))
    if (wide) {
        scope.TabletLayout(modifier, replay, driving, pttEnabled, voice, spatial, debounce, context)
        scope.RigDialogsHost()
        return
    }
    if (tab == Tab.AMIS && !Friends.inGroup(rig.friends)) tab = Tab.MEMOIRES
    Column(modifier.fillMaxSize()) {
      Box(Modifier.weight(1f).fillMaxWidth()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            scope.HeaderAndBanners(replay, driving)
            when (tab) {
                Tab.STATION -> {
                    scope.StationTab()
                }
                Tab.SPECTRE -> {
                    scope.SpectreTab()
                }
                Tab.MEMOIRES -> {
                    scope.MemoriesTab()
                }
                Tab.AMIS -> FriendsPanel(rig, scope.canSet, compact = false, prefs = scope.prefs)
                Tab.EQ -> VoiceTab(
                    transmitting = ptt?.transmitting == true, profiles = rig.voiceProfiles,
                    replayAllowed = hello?.replay != null && !listener, canBroadcast = pttEnabled && !mineTx,
                    onBroadcast = { tab = Tab.STATION },                           // la diffusion se suit sur l'onglet Station
                ) { content -> Panel(content) }
                Tab.REGLAGES -> {
                    scope.SettingsTab()
                    }
            }
        }
        scope.BigPttLayer(pttEnabled, debounce)
      }

        scope.ControlBar(pttEnabled, voice, spatial, debounce, context)
        TabBar(tab, phoneTabs(rig)) { tab = it }
    }

    scope.RigDialogsHost()
}

/** Onglets du téléphone : « Amis » seulement quand la station fait partie d'un groupe. */
internal fun phoneTabs(rig: RigState): List<Tab> = Tab.entries.filter { it != Tab.AMIS || Friends.inGroup(rig.friends) }
