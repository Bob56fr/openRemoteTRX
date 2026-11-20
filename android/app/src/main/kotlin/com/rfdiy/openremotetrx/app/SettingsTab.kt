// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import com.rfdiy.openremotetrx.logic.MobileFeature
import com.rfdiy.openremotetrx.logic.FreeDvLevel
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
import androidx.compose.foundation.layout.PaddingValues
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
import com.rfdiy.openremotetrx.core.AppLang
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.Tr
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

/** Noms des langues dans leur propre langue (jamais traduits). */
private val LANG_NAMES = mapOf("fr" to "Français", "en" to "English", "de" to "Deutsch", "es" to "Español") // i18n-ok

/** Drapeau devant chaque langue (anglais britannique, comme les textes) ; "" = langue du téléphone. */
private val LANG_FLAGS = mapOf("" to "📱", "fr" to "🇫🇷", "en" to "🇬🇧", "de" to "🇩🇪", "es" to "🇪🇸", Tr.PSEUDO to "🧪")

/**
 * Réglages > Langue : langue du téléphone ou une langue proposée ; refusée pendant une émission. L'écran se redessine
 * avec la nouvelle langue ; la station envoie ses textes dans cette langue à la connexion suivante.
 */
@Composable
private fun LanguageSection(transmitting: Boolean, stationSetsLang: Boolean) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var chosen by remember { mutableStateOf(AppLang.stored(context)) }
    Text(Tr.t("settings.language"), style = MaterialTheme.typography.titleSmall)
    // Un bouton par langue, renvoyés à la ligne quand la place manque (téléphone en portrait : 6 boutons)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        // Pseudo-langue « xx » (textes allongés, débordements) : version de débogage seulement
        val choices = listOf<String?>(null) + Tr.OFFERED + listOfNotNull(Tr.PSEUDO.takeIf { AppLang.debuggable(context) })
        for (lang in choices) {
            FilterChip(
                selected = chosen == lang, enabled = !transmitting,
                onClick = {
                    // Écrans redessinés dans la nouvelle langue ; la station la reçoit à la prochaine connexion
                    if (lang != chosen && AppLang.choose(context, lang, transmitting)) {
                        chosen = lang
                        RigHub.announceLang(Tr.stationLang)          // station 0.243.0+ : textes de la station aussitôt
                        (context as? android.app.Activity)?.recreate()
                    }
                },
                label = {
                    // Petit drapeau devant le nom (📱 = langue du téléphone ; 🧪 = pseudo-langue d'essai)
                    val name = lang?.let { LANG_NAMES[it] ?: it } ?: Tr.t("settings.language_phone")
                    val flag = LANG_FLAGS[lang.orEmpty()].orEmpty()
                    Text(if (flag.isEmpty()) name else "$flag $name", maxLines = 1)
                },
            )
        }
    }
    val note = when {
        transmitting -> "settings.language_tx"
        stationSetsLang -> "settings.language_now"            // station 0.243.0+ : sans reconnexion
        else -> "settings.language_next"
    }
    Text(Tr.t(note), style = MaterialTheme.typography.bodySmall)
}

/** Onglet Réglages : journal, préférences, sections du téléphone, outils de la station. */
@Composable
internal fun RigScope.SettingsTab(textPct: Int? = null, onTextPct: (Int) -> Unit = {}) {
            var monitoringOpen by rememberSaveable { mutableStateOf(false) }   // écran « Monitoring » (opérateur)
            if (monitoringOpen) MonitoringScreen(rig) { monitoringOpen = false }
            // Tablette : taille du texte (mémorisée sur l'appareil ; le PTT et le STOP gardent leur taille)
            if (textPct != null) Panel {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(Tr.t("settingstab.text_size"), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    Text("$textPct %", style = MaterialTheme.typography.labelLarge)
                }
                Slider(
                    value = textPct.toFloat(), onValueChange = { onTextPct(com.rfdiy.openremotetrx.logic.ScreenLayouts.fontPct(Math.round(it))) },
                    valueRange = com.rfdiy.openremotetrx.logic.ScreenLayouts.FONT_MIN_PCT.toFloat()..com.rfdiy.openremotetrx.logic.ScreenLayouts.FONT_MAX_PCT.toFloat(),
                    steps = 5,
                )
            }
            // Langue (lot T2) : montrée dès que l'application en propose plus d'une (lot T5)
            if (Tr.OFFERED.size > 1) Panel { LanguageSection(transmitting = rig.ptt?.transmitting == true, stationSetsLang = rig.stationSetsLang) }
            // Journal
            Panel {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(Tr.t("settingstab.log"), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                TextButton(onClick = { showLog = !showLog }) { Text(if (showLog) Tr.t("settingstab.log_less") else Tr.t("settingstab.log_all")) }
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
                Text(Tr.t("settingstab.keep_screen_on"), style = MaterialTheme.typography.bodyMedium)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = keepTx, onCheckedChange = {
                    keepTx = it
                    prefs.edit().putBoolean("keep_tx_background", it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text(Tr.t("settingstab.keep_tx"), style = MaterialTheme.typography.bodyMedium)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = drivingManual, onCheckedChange = {
                    drivingManual = it
                    prefs.edit().putBoolean(RigHub.PREF_DRIVING, it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text(Tr.t("settingstab.driving"), style = MaterialTheme.typography.bodyMedium)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                AppSwitch(checked = drivingAuto, onCheckedChange = {
                    drivingAuto = it
                    prefs.edit().putBoolean(RigHub.PREF_DRIVING_AUTO, it).apply()
                })
                Spacer(Modifier.width(8.dp))
                Text(Tr.t("settingstab.driving_auto"), style = MaterialTheme.typography.bodyMedium)
            }
            }
            Panel { MicSection() }
            Panel { HeadsetSection(ui.headsetMic) }
            if (BuildConfig.CELL_INFO && rig.net != null) Panel { NetCellsSection() }   // absent de la version Google Play
            rig.presence?.takeIf { it.switchShown }?.let { p -> Panel { ListenersSwitch(p) } }   // opérateur seulement
            // « Fonctionnalités mobiles » (étape 300) : affichage des fonctions ; une fonction en service reste affichée
            val voiceNow by com.rfdiy.openremotetrx.core.VoiceHub.ui.collectAsState()
            val spatialNow by com.rfdiy.openremotetrx.core.SpatialHub.ui.collectAsState()
            Panel {
                FeaturesSection(prefs) { f ->
                    when (f) {
                        MobileFeature.ROGER -> rig.beeps?.let { it.rogerEnabled || it.linkLostEnabled } == true
                        MobileFeature.EQ -> voiceNow.settings.enabled
                        MobileFeature.CHORUS_REVERB -> voiceNow.settings.chorus.on || voiceNow.settings.reverb.on
                        MobileFeature.SELCALL -> rig.selcall?.indicator != null
                        MobileFeature.WATERFALL -> miniWf
                        MobileFeature.SPATIAL -> spatialNow.settings.on
                        MobileFeature.BREIZH -> rig.breizh?.level?.let { it != BreizhLevel.OFF } == true
                        MobileFeature.FREEDV -> rig.freedv?.level?.let { it != FreeDvLevel.OFF } == true
                        MobileFeature.DIFFUSION -> rig.diffusion?.let { com.rfdiy.openremotetrx.logic.Diffusions.indicator(it.status) != null } == true
                        MobileFeature.LISTEN -> voiceNow.recording || voiceNow.playing
                        MobileFeature.SCRAMBLER -> voiceNow.scrambler.tx || voiceNow.scrambler.rx
                        MobileFeature.BIG_PTT -> bigPttRequested
                        MobileFeature.REPLAY, MobileFeature.FRIENDS -> false
                    }
                }
            }
            if (hello?.offers("swr") == true && !listener) {                // mesure de TOS (opérateur, station 0.90.0+)
                SettingsAction(Tr.t("settingstab.swr"), onClick = { swrOpen = true })
            }
            if (rig.net != null && !listener) {                             // sonde réseau (opérateur, station 0.106.0+)
                SettingsAction(Tr.t("settingstab.network"), onClick = { netOpen = true })
            }
            if (rig.monitoring != null && !listener) {                      // monitoring inter-stations (opérateur, 0.164.0+)
                SettingsAction(Tr.t("settingstab.monitoring"), onClick = { monitoringOpen = true })
            }
            if (rig.host != null) {                                         // opérateur, station 0.83.0+
                SettingsAction(Tr.t("settingstab.host"), onClick = { hostDialog = true; RigHub.hostInfo() })
            }
            if (hello?.offers("bug_report") == true && !listener && connected) {   // comme la page ; jamais un visiteur
                SettingsAction(Tr.t("settingstab.report"), onClick = { reportOpen = true })
            }
            SettingsAction(Tr.t("common.disconnect"), onClick = onDisconnect, danger = true)
}

/**
 * Bouton d'action de la fin des Réglages (étape 299) : toute la largeur, fond et liseré visibles, texte à gauche et « › »
 * (avant : OutlinedButton de largeurs différentes, liseré à peine visible sur le thème sombre).
 */
@Composable
private fun SettingsAction(label: String, onClick: () -> Unit, danger: Boolean = false) {
    OutlinedButton(
        onClick = onClick, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp),
        border = BorderStroke(1.dp, if (danger) Page.TX.copy(alpha = 0.8f) else Page.ACCENT.copy(alpha = 0.7f)),
        colors = ButtonDefaults.outlinedButtonColors(containerColor = Page.COMMANDE, contentColor = if (danger) Page.TX else Page.TEXTE),
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Text(label, modifier = Modifier.weight(1f))
        Text("›", color = if (danger) Page.TX else Page.MESURE)
    }
}
