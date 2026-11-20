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
import com.rfdiy.openremotetrx.logic.FreeDvLevel
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
import com.rfdiy.openremotetrx.logic.Tr
import com.rfdiy.openremotetrx.protocol.Hello
import java.util.Locale
import kotlin.math.roundToInt
import android.content.SharedPreferences
import androidx.compose.runtime.MutableLongState
import androidx.compose.runtime.MutableState
import com.rfdiy.openremotetrx.core.ReplayUi
import com.rfdiy.openremotetrx.core.SpatialUi
import com.rfdiy.openremotetrx.core.VoiceUi

private val TX_RED = Page.TX                     // couleurs de la page web (client.css)
private val WARN = Page.ALERTE
private val SQL_OPEN = Page.SUCCES
private val HEALTH = mapOf("green" to Page.SUCCES, "orange" to Page.ALERTE, "red" to Page.TX, "off" to Page.TEXTE_2)
private val DOT_COLORS = mapOf(1 to Page.TEXTE_2, 2 to Page.ALERTE, 3 to Page.TX)    // pastilles des bandes (page : lvl1..3)

// Parties communes au téléphone et à la tablette (sorties de RigScreen.kt, étape 149 : mêmes corps).

/** En-tête (station, liaison, pastilles, sourdine) et bandeaux d'alerte (liaison, émission, poste sur place, conduite). */
@Composable
internal fun RigScope.HeaderAndBanners(replay: ReplayUi, driving: DrivingReason, presenceBanner: Boolean = true) {
            // En-tête : station, liaison, sourdine
            Row(verticalAlignment = Alignment.CenterVertically) {
                // Santé de la machine de la station (opérateurs) : petit bargraph à gauche du nom, toucher = synthèse du matériel
                rig.host?.let { h ->
                    HostBar(h, onClick = { hostDialog = true; RigHub.hostInfo() })
                    Spacer(Modifier.width(10.dp))
                }
                Column(Modifier.weight(1f)) {
                    Text(ui.station?.name ?: Tr.t("rigparts.station"), style = MaterialTheme.typography.titleLarge)
                    Text(
                        when (rig.status) {
                            LinkStatus.CONNECTED -> rig.rttMs?.let { Tr.t("rigparts.connected_rtt", "ms" to it) } ?: Tr.t("rigparts.connected")
                            LinkStatus.CONNECTING -> Tr.t("rigparts.connecting")
                            LinkStatus.RECONNECTING -> Tr.t("rigparts.reconnecting")
                            LinkStatus.DISCONNECTED -> Tr.t("rigparts.disconnected")
                        },
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                rig.net?.let { n ->                                                     // sonde réseau : pastille, toucher = détail
                    NetChip(n, onClick = { netDialog = true })
                    Spacer(Modifier.width(6.dp))
                }
                rig.presence?.takeIf { it.label.isNotEmpty() }?.let { p ->             // 🎧 N : visiteurs connectés
                    CompactChip(p.label, onClick = { presenceDialog = true })
                    Spacer(Modifier.width(6.dp))
                }
                Text(Tr.t("rigparts.mute"), style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.width(6.dp))
                AppSwitch(checked = ui.muted, onCheckedChange = { RigHub.setMuted(it) })
            }
            if (listener) Banner(Tr.t("rigparts.visitor"), Page.SELECTION, textColor = Page.TEXTE)
            if (presenceBanner) PresenceBanner()
            RigNoticeBanner()
            PowerBannerRow()
            // Diffusion en direct en cours : bandeau toujours visible (cahier § 8), toucher = sa fenêtre
            rig.diffusion?.let { dif ->
                com.rfdiy.openremotetrx.logic.Diffusions.indicator(dif.status)?.let { ind ->
                    Box(Modifier.clickable { diffusionDialog = true }) { Banner("● " + ind.text, if (ind.live) TX_RED else WARN) }
                }
            }

            rig.reconnect?.let { r ->
                Banner(
                    Tr.t("rigparts.link_lost", "seconds" to r.remainingS, "attempts" to r.attempts) +
                        (if (r.lastError.isNotEmpty()) "\n${r.lastError}" else "") + "\n" + Tr.t("rigparts.link_lost_tx_cut"),
                    TX_RED,
                )
            }
            if (!rig.protocolOk) Banner(Tr.t("rigparts.protocol_unknown"), WARN)

            if (replay.playing || replay.pending) {
                Banner(if (replay.playing) Tr.t("rigparts.replay_playing", "position" to replay.positionS.toInt(), "length" to replay.recordedS.toInt())
                       else Tr.t("rigparts.replay_pending"), TX_RED, textColor = Color.White)
            }
            // Avertissements de l'émission (l'état lui-même est dans l'afficheur)
            if (ptt != null) {
                if (ptt.totWarning) Banner(Tr.t("rigparts.tot_warning"), WARN)
                ptt.local?.let { local ->
                    Banner(local, WARN)
                    if (ptt.canReleaseLocal) OutlinedButton(onClick = { RigHub.releaseLocal() }) { Text(Tr.t("rigparts.release_local")) }
                }
                when (ptt.tempAlert) {
                    "hot" -> Banner(Tr.t("rigparts.too_hot"), TX_RED)
                    "warn" -> Banner(Tr.t("rigparts.hot"), WARN)
                }
                if (ptt.fault.isNotEmpty()) Banner(Tr.t("rigparts.fault", "fault" to ptt.fault), TX_RED)
                if (ptt.lastCut.isNotEmpty() && !ptt.transmitting) Text(Tr.t("rigparts.last_cut", "cut" to ptt.lastCut), style = MaterialTheme.typography.bodySmall)
            }

            if (driving == DrivingReason.PASSENGER) Row(verticalAlignment = Alignment.CenterVertically) {
                Text(Tr.t("rigparts.passenger"), color = WARN, style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.weight(1f))
                TextButton(onClick = { RigHub.setPassenger(false) }) { Text(Tr.t("rigparts.driving_mode")) }
            }
}

/** Gros PTT rond au milieu de l'écran (appui long sur le PTT ; STOP le masque ; jamais en conduite). */
@Composable
internal fun RigScope.BigPttLayer(pttEnabled: Boolean, debounce: Debounce) {
        if (BigPtt.visible(bigPttRequested, connected, driving = false)) {      // conduite : écran à part, sans PTT tactile
            BigPttOverlay(BigPtt.look(ptt, rig.armed, pttEnabled), ptt?.totSeconds, pttEnabled) {
                if (debounce.pass()) RigHub.toggle()
            }
        }
}

/**
 * Toujours visibles : armement, boutons du client (WF, SEL, EQ, ST, BZH, scrambler), PTT (appui simple ; appui long =
 * gros PTT) et STOP. `wfChip` : bouton du petit waterfall (absent sur tablette, où le spectre HF est toujours affiché).
 */
@Composable
internal fun RigScope.ControlBar(pttEnabled: Boolean, voice: VoiceUi, spatial: SpatialUi, debounce: Debounce, context: Context, wfChip: Boolean = true,
                                 compact: Boolean = false, onStop: () -> Unit = {}) {
        // Toujours visibles : armement, PTT (appui simple ; appui long = gros PTT au milieu de l'écran), STOP
        Surface(tonalElevation = 6.dp) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (!compact) Row(verticalAlignment = Alignment.CenterVertically) {
                    AppSwitch(checked = rig.armed, onCheckedChange = { RigHub.setArmed(it) }, enabled = connected && rig.protocolOk && !listener)
                    Spacer(Modifier.width(8.dp))
                    Text(if (!ui.micAllowed) Tr.t("rigparts.armed_no_mic") else Tr.t("rigparts.armed"), modifier = Modifier.weight(1f))
                }
                // Boutons du client sur leur propre ligne (WF, SEL, EQ, ST, voyant du scrambler)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // Tablette (compact) : l'armement sur la même ligne que les boutons du client, place gagnée pour l'afficheur
                    if (compact) {
                        AppSwitch(checked = rig.armed, onCheckedChange = { RigHub.setArmed(it) }, enabled = connected && rig.protocolOk && !listener)
                        Spacer(Modifier.width(6.dp))
                        Text(if (!ui.micAllowed) Tr.t("rigparts.rx_only") else Tr.t("rigparts.armed_short"), style = MaterialTheme.typography.labelMedium)
                        Spacer(Modifier.width(10.dp))
                    }
                    // Petit waterfall de l'onglet Station : affiché ou masqué (station avec spectre HF)
                    if (wfChip && HfScope.configured(hello) && Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.WATERFALL, miniWf)) {
                        CompactChip(if (miniWf) "WF ●" else "WF", onClick = { setMiniWf(!miniWf) }, selected = miniWf, help = com.rfdiy.openremotetrx.logic.Help.client("WF"))
                        Spacer(Modifier.width(6.dp))
                    }
                    // SELCALL de la station : « SEL 4721 » (veille), « SEL OUVERT » (allumé) ; toucher = panneau ; même style que EQ
                    rig.selcall?.takeIf { Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.SELCALL, it.indicator != null) }?.let { sel ->
                        CompactChip(sel.indicator ?: "SEL", onClick = { selcallDialog = true }, selected = sel.open, help = com.rfdiy.openremotetrx.logic.Help.client("SEL"))
                        Spacer(Modifier.width(6.dp))
                    }
                    // Égaliseur : marche/arrêt d'accès direct (réglages dans l'onglet « Audio »)
                    // « Fonctionnalités mobiles » (étape 300) : chaque bouton peut être masqué, jamais s'il est en service
                    val eqOn = voice.settings.enabled && !voice.breizh          // voix par Breizh : EQ coupé, bouton grisé
                    if (Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.EQ, voice.settings.enabled)) {
                        CompactChip(if (eqOn) "EQ ●" else "EQ", onClick = { VoiceHub.setEnabled(context, !voice.settings.enabled) }, selected = eqOn,
                            onLongClick = { tab = Tab.EQ }, enabled = !voice.breizh)
                        Spacer(Modifier.width(6.dp))
                    }
                    // Spatialisation stéréo de la réception : appui = marche / arrêt, appui long = réglages
                    val stOn = spatial.settings.on
                    if (Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.SPATIAL, stOn)) {
                        CompactChip(if (stOn) "ST ●" else "ST", onClick = { com.rfdiy.openremotetrx.core.SpatialHub.setEnabled(context, !stOn) },
                            selected = stOn && spatial.monoReason.isEmpty(), onLongClick = { spatialDialog = true })
                    }
                    // Breizh Audio Box (station qui l'emploie) : voyant BZH vert / orange / gris ; toucher = sa fenêtre
                    rig.breizh?.takeIf { Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.BREIZH, it.level != BreizhLevel.OFF) }?.let { bzh ->
                        Spacer(Modifier.width(6.dp))
                        CompactChip("BZH", onClick = { breizhDialog = true }, selected = bzh.level == BreizhLevel.OK, dot = breizhColor(bzh.level),
                            help = com.rfdiy.openremotetrx.logic.Help.client("BZH"))
                    }
                    // FreeDV (station qui l'offre, TOUS les comptes) : voyant FDV vert / orange / rouge / gris ; toucher = sa fenêtre
                    rig.freedv?.takeIf { Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.FREEDV, it.level != FreeDvLevel.OFF) }?.let { fdv ->
                        Spacer(Modifier.width(6.dp))
                        CompactChip("FDV", onClick = { freedvDialog = true }, selected = fdv.level == FreeDvLevel.OK, dot = freedvColor(fdv.level),
                            help = com.rfdiy.openremotetrx.logic.Help.client("FDV"))
                    }
                    // Diffusion en direct (station qui l'offre, opérateurs) : voyant DIF, rouge en direct ; toucher = sa fenêtre
                    rig.diffusion?.takeIf { Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.DIFFUSION, com.rfdiy.openremotetrx.logic.Diffusions.indicator(it.status) != null) }?.let { dif ->
                        Spacer(Modifier.width(6.dp))
                        val live = com.rfdiy.openremotetrx.logic.Diffusions.indicator(dif.status) != null
                        CompactChip("DIF", onClick = { diffusionDialog = true }, selected = live,
                            dot = if (live) diffusionColor(dif) else null)
                    }
                    // Scrambler en service : voyant permanent (toucher = rubrique dans l'onglet « Audio »)
                    if (voice.scrambler.tx || voice.scrambler.rx) {
                        Spacer(Modifier.width(6.dp))
                        Text(
                            if (voice.scrambler.tx) "SCRAMBLER" else Tr.t("rigparts.descrambling"), color = TX_RED, fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.labelMedium, modifier = Modifier.clickable { tab = Tab.EQ },
                        )
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val canShowBig = !listener && BigPtt.canShow(connected, rig.protocolOk, ui.micAllowed, driving = false) &&
                        Features.shown(com.rfdiy.openremotetrx.logic.MobileFeature.BIG_PTT, bigPttRequested)
                    val pttColors = if (mineTx) ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White) else ButtonDefaults.buttonColors()
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = if (pttEnabled) pttColors.containerColor else pttColors.disabledContainerColor,
                        contentColor = if (pttEnabled) pttColors.contentColor else pttColors.disabledContentColor,
                        modifier = Modifier.weight(2f).height(if (compact) 52.dp else 64.dp).combinedClickable(
                            enabled = pttEnabled || canShowBig,
                            onClick = { if (pttEnabled && debounce.pass()) RigHub.toggle() },
                            onLongClick = { if (canShowBig) bigPttRequested = true },
                        ),
                    ) {
                      Box(contentAlignment = Alignment.Center) {
                        Text(
                            when {
                                mineTx -> Tr.t("rigparts.ptt_end")
                                ptt?.mine == true -> Tr.t("rigparts.ptt_cutting")
                                ptt?.other == true -> Tr.t("rigparts.ptt_other")
                                !rig.armed -> Tr.t("rigparts.ptt_arm_first")
                                else -> Tr.t("rigparts.ptt_transmit")
                            },
                            fontSize = 16.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center,
                        )
                      }
                    }
                    // STOP coupe à l'APPUI, masque le gros PTT (tablette : replie le bloc) ; maintenu 3 s : fenêtre à deux choix
                    StopButton(Modifier.weight(1f).height(if (compact) 52.dp else 64.dp), if (compact) 52.dp else 64.dp) {
                        bigPttRequested = false; onStop()
                    }
                }
            }
        }
}

/** Fenêtres de l'écran de la station (fréquence, niveaux, bandes, SELCALL, ST, visiteurs, Breizh, TOS, réseau, rapport…). */
@Composable
internal fun RigScope.RigDialogsHost() {
    PowerDialogs()                                                     // alimentation du poste (lot P3)
    HelpDialog()                                                      // aide courte par appui long
    if (entry) FrequencyDialog(shownHz, onDismiss = { entry = false }) { hz ->
        entry = false
        go(hz)
    }
    if (levelsDialog) LevelsDialog(levelRanges(hello, radio?.levels), radio?.levels.orEmpty(), canSet) { levelsDialog = false }
    if (bandsDialog) BandsDialog(Radio.favoriteBands(bandsPref), onDismiss = { bandsDialog = false }) { chosen ->
        bandsPref = Radio.favoriteBandsText(chosen)
        prefs.edit().putString("bands", bandsPref).apply()
        bandsDialog = false
    }
    rig.selcall?.let { st ->
        if (spatialDialog) SpatialDialog(onDismiss = { spatialDialog = false })
        if (selcallDialog) SelcallDialog(st, connected && rig.protocolOk, armed = rig.armed && ui.micAllowed,
            transmitting = ptt?.transmitting == true || (rig.state?.ptt?.state ?: "RX") != "RX", mine = ptt?.mine == true,
            sendOffered = hello?.offers("selcall_send") == true, calibrateOffered = hello?.offers("selcall_calibrate") == true,
            lastMessage = rig.log.lastOrNull()?.text.orEmpty(),
            onDismiss = { selcallDialog = false })
    }
    if (presenceDialog) rig.presence?.let { PresenceDialog(it) { presenceDialog = false } }
    if (breizhDialog) rig.breizh?.let { BreizhDialog(it, rig.breizhEvents) { breizhDialog = false } }
    if (freedvDialog) rig.freedv?.let {
        FreeDvDialog(it, rig.freedvNotice, operator = !listener && connected && rig.protocolOk,
            transmitting = (rig.state?.ptt?.state ?: "RX") != "RX",
            activity = rig.freedvActivity, activityNotice = rig.freedvActivityNotice) { freedvDialog = false }
    }
    if (diffusionDialog) rig.diffusion?.let { DiffusionDialog(it) { diffusionDialog = false } }
    if (swrOpen) SwrScreen(rig) { swrOpen = false }
    if (netOpen) NetScreen(rig) { netOpen = false }
    if (netDialog) rig.net?.let { n -> NetDialog(n, operator = !listener, radio = ui.radio?.text(), onStats = { netDialog = false; netOpen = true }) { netDialog = false } }
    if (reportOpen) ProblemReportDialog { reportOpen = false }
    if (hostDialog) HostDialog(rig.host, rig.hostSections, onRefresh = { RigHub.hostInfo() }) { hostDialog = false }
    if (spotsDialog) RecentSpotsDialog(rig.recentSpots, rig.spots, hello?.spectrum != null, canSet, onDismiss = { spotsDialog = false })
    memoryDialog?.let { edit ->
        MemoryDialog(edit, Radio.orderModes(hello?.capabilities?.modes.orEmpty()), onDismiss = { memoryDialog = null })
    }
}

/** Avis de la station sur le poste (VOX coupé, coupleur, TOS élevé) : bandeau rouge ou orange, toucher = fermer. */
@Composable
internal fun RigScope.RigNoticeBanner() {
    rig.rigNotice.takeIf { it.isNotEmpty() }?.let { text ->
        Box(Modifier.clickable { RigHub.dismissRigNotice() }) { Banner(Tr.t("rigparts.notice_tap_close", "text" to text), if (rig.rigNoticeBad) TX_RED else WARN) }
    }
}

/** Visiteurs suspendus ou attente de l'opérateur (« Station surchargée… ») : bandeau orange. */
@Composable
internal fun RigScope.PresenceBanner() {
    rig.presence?.let { p -> p.suspended.ifEmpty { p.grace }.takeIf { it.isNotEmpty() }?.let { Banner(it, WARN) } }
}
