// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.ReplayUi
import com.rfdiy.openremotetrx.core.SpatialUi
import com.rfdiy.openremotetrx.core.VoiceUi
import com.rfdiy.openremotetrx.logic.DrivingReason
import com.rfdiy.openremotetrx.logic.HfScope
import com.rfdiy.openremotetrx.logic.ScreenLayouts

/** Rubriques du volet droit de la tablette : celles du téléphone sauf « Station », toujours visible à gauche. */
private val TABLET_SECTIONS = listOf(Tab.MEMOIRES, Tab.SPECTRE, Tab.EQ, Tab.REGLAGES)

/**
 * Tablette, fenêtre LARGE en paysage (lot A5, étape 149 ; modèle : la page PC, docs/android-tablette-cahier-des-charges.md
 * § 4). À gauche, colonne fixe : en-tête et bandeaux, afficheur, bandes, modes, fonctions du poste, puis armement, PTT et
 * STOP TOUJOURS à la même place en bas. À droite : spectre HF du poste en haut (s'il est configuré), puis la rubrique
 * choisie dans le rail (Mémoires et Cluster DX, Spectre audio, Audio, Réglages). Mêmes composants que le téléphone :
 * aucune règle de sécurité ne change (état d'émission relu sur la station, STOP toujours joignable).
 */
@Composable
internal fun RigScope.TabletLayout(
    modifier: Modifier, replay: ReplayUi, driving: DrivingReason, pttEnabled: Boolean, voice: VoiceUi, spatial: SpatialUi,
    debounce: Debounce, context: Context,
) {
    var section by rememberSaveable { mutableStateOf(Tab.MEMOIRES) }
    val screenH = LocalConfiguration.current.screenHeightDp.dp
    Box(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxSize()) {
            Column(Modifier.width(ScreenLayouts.LEFT_COLUMN_DP.dp).fillMaxHeight()) {
                Column(
                    Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    HeaderAndBanners(replay, driving)
                    StationTab(miniWaterfall = false)                 // le grand spectre HF est à droite
                }
                ControlBar(pttEnabled, voice, spatial, debounce, context, wfChip = false)
            }
            VerticalDivider()
            Column(Modifier.weight(1f).fillMaxHeight()) {
                if (connected && HfScope.configured(hello)) {
                    Box(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp)) {
                        HfScopeView(ui, canSet, onTune = { go(it) }, onClose = null,
                            plotModifier = Modifier.fillMaxWidth().height((screenH * 0.42f).coerceAtLeast(160.dp)))
                    }
                }
                Row(Modifier.weight(1f).fillMaxWidth()) {
                    NavigationRail {
                        for (s in TABLET_SECTIONS) {
                            NavigationRailItem(
                                selected = s == section, onClick = { section = s },
                                icon = { Text(s.symbol) },
                                label = { Text(if (s == Tab.SPECTRE) "Son" else s.label) },
                            )
                        }
                    }
                    Column(
                        Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        when (section) {
                            Tab.SPECTRE -> SpectreTab(mini = false, hf = false)      // spectre du son reçu
                            Tab.EQ -> VoiceTab(
                                transmitting = ptt?.transmitting == true, profiles = rig.voiceProfiles,
                                replayAllowed = hello?.replay != null && !listener, canBroadcast = pttEnabled && !mineTx,
                                onBroadcast = {},                               // la diffusion se suit à gauche, toujours visible
                            ) { content -> Panel(content) }
                            Tab.REGLAGES -> SettingsTab()
                            else -> MemoriesTab(mini = false)
                        }
                    }
                }
            }
        }
        BigPttLayer(pttEnabled, debounce)
    }
}
