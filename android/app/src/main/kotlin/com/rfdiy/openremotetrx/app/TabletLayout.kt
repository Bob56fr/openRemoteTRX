// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.coerceAtLeast
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.ReplayUi
import com.rfdiy.openremotetrx.core.SpatialUi
import com.rfdiy.openremotetrx.core.VoiceUi
import com.rfdiy.openremotetrx.logic.DrivingReason
import com.rfdiy.openremotetrx.logic.Help
import com.rfdiy.openremotetrx.logic.HfScope
import com.rfdiy.openremotetrx.logic.ScreenLayouts

private const val PREF_TEXT_PCT = "tablet_text_pct"
private const val PREF_HF = "tablet_hf_on"
private const val PREF_AUDIO = "tablet_audio_on"
private const val PREF_SPLIT = "tablet_split"
private val SECTIONS = listOf(Tab.MEMOIRES, Tab.EQ, Tab.REGLAGES)

/**
 * Tablette, fenêtre LARGE en paysage (lot A5 ; choix de l'utilisateur du 2026-11-09, étape 152).
 * - EN BAS, toute la largeur : spectre HF du poste et spectre du son reçu CÔTE À CÔTE, séparateur vertical à glisser ;
 *   chacun masquable (le HF consomme de la bande passante : à couper en 4G / 5G ; le son est calculé ici).
 * - AU-DESSUS, trois blocs : afficheur avec armement, PTT et STOP (toujours à la même place) | commandes du poste (le
 *   bandeau « station surchargée » au-dessus) | rubrique choisie dans le rail (Mémoires et Cluster DX, Audio, Réglages).
 * - Le bloc des rubriques S'AGRANDIT par-dessus le spectre dès qu'on y fait défiler ; il se replie par « ▾ Replier »,
 *   par STOP (qui coupe toujours l'émission) ou par un toucher sur le spectre (ce toucher ne fait QUE replier).
 * - Texte réduit (85 % par défaut, réglable dans Réglages) ; boutons compacts et interrupteurs suivent ; PTT et STOP non.
 */
@Composable
internal fun RigScope.TabletLayout(
    modifier: Modifier, replay: ReplayUi, driving: DrivingReason, pttEnabled: Boolean, voice: VoiceUi, spatial: SpatialUi,
    debounce: Debounce, context: Context,
) {
    val hf = connected && HfScope.configured(hello)
    var section by rememberSaveable { mutableStateOf(Tab.MEMOIRES) }
    var expanded by rememberSaveable { mutableStateOf(false) }
    var textPct by remember { mutableIntStateOf(ScreenLayouts.fontPct(prefs.getInt(PREF_TEXT_PCT, -1).takeIf { it > 0 })) }
    var showHf by remember { mutableStateOf(prefs.getBoolean(PREF_HF, true)) }
    var showAudio by remember { mutableStateOf(prefs.getBoolean(PREF_AUDIO, true)) }
    var split by remember { mutableFloatStateOf(ScreenLayouts.split(prefs.getFloat(PREF_SPLIT, ScreenLayouts.SPLIT_DEFAULT))) }
    var topPx by remember { mutableIntStateOf(0) }
    val hfShown = hf && showHf
    val audioShown = connected && showAudio
    val base = LocalDensity.current
    val scale = textPct / 100f
    val small = Density(base.density, base.fontScale * scale)
    val sectionScroll = rememberScrollState()
    // Défiler dans la rubrique l'agrandit par-dessus le spectre
    LaunchedEffect(sectionScroll.isScrollInProgress) { if (sectionScroll.isScrollInProgress) expanded = true }

    BoxWithConstraints(modifier.fillMaxSize()) {
        val spectrumH = maxHeight * ScreenLayouts.SPECTRUM_SHARE
        val plotH = (spectrumH - 72.dp).coerceAtLeast(120.dp)
        val sideW = (maxWidth - ScreenLayouts.LEFT_COLUMN_DP.dp - 2.dp) * (1.1f / 2.1f)     // largeur du bloc des rubriques
        val topH = with(LocalDensity.current) { topPx.toDp() }
        CompositionLocalProvider(LocalDensity provides small, LocalUiScale provides scale) {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.weight(1f).fillMaxWidth().onSizeChanged { topPx = it.height }) {
                    // 1. Afficheur ; armement, PTT et STOP en bas du bloc, à taille normale
                    Column(Modifier.width(ScreenLayouts.LEFT_COLUMN_DP.dp).fillMaxHeight()) {
                        Column(
                            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            HeaderAndBanners(replay, driving, presenceBanner = false)
                            StationDisplay()
                        }
                        CompositionLocalProvider(LocalDensity provides base, LocalUiScale provides 1f) {
                            ControlBar(pttEnabled, voice, spatial, debounce, context, wfChip = false, compact = true,
                                onStop = { expanded = false })
                        }
                    }
                    VerticalDivider()
                    // 2. Commandes du poste ; le bandeau « station surchargée » au-dessus (place libre)
                    Column(
                        Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()).padding(horizontal = 10.dp, vertical = 6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        PresenceBanner()
                        StationControls(miniWaterfall = false)
                    }
                    VerticalDivider()
                    Spacer(Modifier.width(sideW))                    // 3. place du bloc des rubriques (dessiné par-dessus)
                }
                HorizontalDivider()
                // Barre des spectres : montrer / masquer (appui long : aide)
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (hf) CompactChip(if (showHf) "HF ●" else "HF", selected = showHf, help = Help.client("HF"), onClick = {
                        showHf = !showHf; prefs.edit().putBoolean(PREF_HF, showHf).apply()
                    })
                    CompactChip(if (showAudio) "Son ●" else "Son", selected = showAudio, help = Help.client("SON"), onClick = {
                        showAudio = !showAudio; prefs.edit().putBoolean(PREF_AUDIO, showAudio).apply()
                    })
                    if (hf && !showHf) Text("Spectre HF masqué : la station ne l'envoie plus (économie de données).",
                        style = MaterialTheme.typography.labelSmall, color = Page.TEXTE_2)
                }
                if (hfShown || audioShown) {
                    BoxWithConstraints(Modifier.fillMaxWidth().height(spectrumH)) {
                        val widthPx = with(LocalDensity.current) { maxWidth.toPx() }
                        Row(Modifier.fillMaxSize()) {
                            if (hfShown) Box(Modifier.weight(if (audioShown) split else 1f).fillMaxHeight().padding(horizontal = 8.dp, vertical = 4.dp)) {
                                HfScopeView(ui, canSet, onTune = { go(it) }, onClose = null,
                                    plotModifier = Modifier.fillMaxWidth().height(plotH))
                            }
                            if (hfShown && audioShown) {
                                // Poignée : ligne verticale, glisser pour agrandir l'un ou l'autre spectre
                                Box(
                                    Modifier.width(18.dp).fillMaxHeight().draggable(
                                        orientation = Orientation.Horizontal,
                                        state = rememberDraggableState { delta -> split = ScreenLayouts.split(split + delta / widthPx) },
                                        onDragStopped = { prefs.edit().putFloat(PREF_SPLIT, split).apply() },
                                    ),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Box(Modifier.width(2.dp).fillMaxHeight().background(Page.LIGNE))
                                    Text("⋮", color = Page.TEXTE_2, modifier = Modifier.background(Page.INSTRUMENT))
                                }
                            }
                            if (audioShown) Box(Modifier.weight(if (hfShown) 1f - split else 1f).fillMaxHeight().padding(horizontal = 8.dp, vertical = 4.dp)) {
                                AudioWaterfallView(onClose = null, plotHeight = plotH)
                            }
                        }
                    }
                }
            }
            // Bloc agrandi : un toucher sous les blocs (spectre) le replie, SANS rien changer au spectre
            if (expanded) Box(
                Modifier.fillMaxSize().padding(top = topH).clickable(
                    interactionSource = remember { MutableInteractionSource() }, indication = null,
                ) { expanded = false },
            )
            // 3. Rubrique choisie dans le rail : hauteur des blocs, ou tout l'écran une fois agrandie
            Surface(
                color = MaterialTheme.colorScheme.background, tonalElevation = if (expanded) 3.dp else 0.dp,
                modifier = Modifier.align(Alignment.TopEnd).width(sideW).height(if (expanded) maxHeight else topH),
            ) {
                Row(Modifier.fillMaxSize()) {
                    NavigationRail {
                        for (s in SECTIONS) {
                            NavigationRailItem(selected = s == section, onClick = { section = s }, icon = { Text(s.symbol) },
                                label = { Text(s.label) })
                        }
                    }
                    Column(Modifier.weight(1f).fillMaxHeight()) {
                        if (expanded) TextButton(onClick = { expanded = false }, modifier = Modifier.align(Alignment.End)) { Text("▾ Replier") }
                        Column(
                            Modifier.weight(1f).fillMaxWidth().verticalScroll(sectionScroll).padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            when (section) {
                                Tab.EQ -> VoiceTab(
                                    transmitting = ptt?.transmitting == true, profiles = rig.voiceProfiles,
                                    replayAllowed = hello?.replay != null && !listener, canBroadcast = pttEnabled && !mineTx,
                                    onBroadcast = {},                       // la diffusion se suit à gauche, toujours visible
                                ) { content -> Panel(content) }
                                Tab.REGLAGES -> SettingsTab(textPct) { pct ->
                                    textPct = pct
                                    prefs.edit().putInt(PREF_TEXT_PCT, pct).apply()
                                }
                                else -> MemoriesTab(mini = false)
                            }
                        }
                    }
                }
            }
        }
        BigPttLayer(pttEnabled, debounce)
    }
}
