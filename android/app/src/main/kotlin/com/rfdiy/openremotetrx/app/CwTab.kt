// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.CwInterface
import com.rfdiy.openremotetrx.logic.CwSettings
import com.rfdiy.openremotetrx.logic.CwUi
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.Paddle
import com.rfdiy.openremotetrx.logic.Tr

/*
 * Onglet CW (branche d'essai exp/cw, docs/exp-cw/cahier-des-charges.md § 7 ; maquette validée le 2026-11-26).
 * Smartphone : STOP et « Quitter » TOUT EN HAUT, synthèse du poste, réglages, sélecteur 1 / 2 palettes et « Armer CW »,
 * manipulateur jusqu'en bas, AUCUNE barre d'onglets (les doigts la heurteraient). Tablette : synthèse en haut,
 * réglages et texte décodé au milieu, « Armer CW » et STOP à gauche des palettes, onglets sur le côté.
 * Quitter l'onglet (bouton, autre onglet, mode conduite) DÉSARME toujours la CW. L'état armé vient de la station.
 */

private const val PREF = "cw_"                                               // i18n-ok

private fun loadSettings(prefs: android.content.SharedPreferences) = CwSettings(
    keyInterface = CwInterface.of(prefs.getString(PREF + "interface", null)),
    wpm = prefs.getInt(PREF + "wpm", 20),
    weight = prefs.getFloat(PREF + "weight", 3.0f).toDouble(),
    toneHz = prefs.getInt(PREF + "tone", 700),
    reversed = prefs.getBoolean(PREF + "reversed", false),
    align = prefs.getBoolean(PREF + "align", false),
    sidetone = prefs.getFloat(PREF + "sidetone", 0.6f).toDouble(),
)

private fun saveSettings(prefs: android.content.SharedPreferences, s: CwSettings) {
    prefs.edit().putString(PREF + "interface", s.keyInterface.wire).putInt(PREF + "wpm", s.wpm)
        .putFloat(PREF + "weight", s.weight.toFloat()).putInt(PREF + "tone", s.toneHz)
        .putBoolean(PREF + "reversed", s.reversed).putBoolean(PREF + "align", s.align)
        .putFloat(PREF + "sidetone", s.sidetone.toFloat()).apply()
}

/** Onglet CW plein écran. `onQuit` : retour à l'onglet Station ; `onSection` (tablette) : autre onglet choisi. */
@Composable
internal fun RigScope.CwScreen(modifier: Modifier, tablet: Boolean, onQuit: () -> Unit, onSection: (Tab) -> Unit = { onQuit() }) {
    var settings by remember { mutableStateOf(loadSettings(prefs)) }
    fun change(s: CwSettings) {
        settings = s
        saveSettings(prefs, s)
        RigHub.cwSettings(s)
    }
    LaunchedEffect(Unit) { RigHub.cwSettings(settings) }
    DisposableEffect(Unit) { onDispose { RigHub.cwDisarm() } }               // quitter l'onglet = désarmer, toujours
    val cw = rig.cw
    if (tablet) {
        Row(modifier.fillMaxSize().background(Page.FOND)) {
            Column(Modifier.weight(1f).fillMaxHeight()) {
                CwSummary(cw, settings, wide = true)
                Row(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.weight(1f).fillMaxHeight().card(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        CwSettingsBlock(cw, settings, ::change)
                        CwStats(cw)
                    }
                    Column(Modifier.weight(1f).fillMaxHeight().card()) {
                        Text(Tr.t("cw.decoded_title"), color = Page.TEXTE_2, fontSize = 12.sp)
                        CwDecoded(cw, Modifier.weight(1f).fillMaxWidth().padding(top = 6.dp), big = true)
                        CwNotice(cw)
                    }
                }
                Row(Modifier.height(300.dp).fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 14.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.width(250.dp).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        PadSelector(settings, ::change, Modifier.fillMaxWidth())
                        TxAllowedRow()
                        ArmButton(cw, Modifier.fillMaxWidth().height(64.dp))
                        StopButton(Modifier.fillMaxWidth().weight(1f))
                    }
                    Pads(cw, settings, Modifier.weight(1f).fillMaxHeight())
                }
            }
            Column(Modifier.width(84.dp).fillMaxHeight().background(Page.PANNEAU).padding(vertical = 10.dp),
                   verticalArrangement = Arrangement.spacedBy(4.dp)) {
                for (t in Tab.entries.filter { it != Tab.AMIS || friendsTab(rig) }) {
                    val on = t == Tab.CW
                    Column(Modifier.fillMaxWidth().height(64.dp).background(if (on) Page.SELECTION else Color.Transparent)
                        .clickable { if (!on) onSection(t) },
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                        TabIcon(t, if (on) Page.ACCENT else Page.TEXTE_2)
                        Text(t.label, fontSize = 11.sp, color = if (on) Page.ACCENT else Page.TEXTE_2, maxLines = 1,
                             overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
        return
    }
    Column(modifier.fillMaxSize().background(Page.FOND)) {
        Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, top = 10.dp, bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StopButton(Modifier.weight(1f).height(52.dp))
            Box(Modifier.width(104.dp).height(52.dp).background(Page.COMMANDE, RoundedCornerShape(12.dp))
                .border(1.dp, Page.BORD, RoundedCornerShape(12.dp)).clickable { onQuit() },
                contentAlignment = Alignment.Center) {
                Text(Tr.t("cw.quit"), color = Page.TEXTE, fontWeight = FontWeight.SemiBold)
            }
        }
        CwSummary(cw, settings, wide = false)
        CwDecoded(cw, Modifier.padding(start = 14.dp, end = 14.dp, top = 8.dp).fillMaxWidth().height(34.dp), big = false)
        Column(Modifier.padding(start = 14.dp, end = 14.dp, top = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            CwSettingsBlock(cw, settings, ::change)
            CwNotice(cw)
        }
        Box(Modifier.padding(start = 14.dp, end = 14.dp, top = 6.dp)) { TxAllowedRow() }
        Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 14.dp, top = 6.dp, bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            PadSelector(settings, ::change)
            ArmButton(cw, Modifier.weight(1f).height(46.dp))
        }
        Pads(cw, settings, Modifier.weight(1f).fillMaxWidth().padding(start = 14.dp, end = 14.dp, bottom = 18.dp))
    }
}

private fun Modifier.card() = this.background(Page.PANNEAU, RoundedCornerShape(14.dp))
    .border(1.dp, Page.CADRE, RoundedCornerShape(14.dp)).padding(14.dp)

@Composable
private fun RigScope.CwSummary(cw: CwUi, settings: CwSettings, wide: Boolean) {
    val r = radio
    val tx = ptt?.transmitting == true
    val badge = when {
        cw.armed && cw.keyDown -> Tr.t("cw.badge_tone")
        cw.armed -> Tr.t("cw.badge_armed")
        tx -> Tr.t("cw.badge_tx")
        else -> Tr.t("cw.badge_rx")
    }
    val sign = if (r?.mode?.contains("LSB") == true) -1 else 1                      // i18n-ok
    val carrier = cw.carrierHz ?: r?.frequencyHz?.let { it + sign * settings.toneHz }
    val levels = r?.levels.orEmpty()
    Column(Modifier.fillMaxWidth().background(Page.INSTRUMENT).padding(horizontal = if (wide) 20.dp else 14.dp, vertical = 10.dp),
           verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(badge, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = if (tx || cw.armed) Color.White else Page.SUCCES,
                 modifier = Modifier.background(if (tx || cw.armed) Page.TX else Color(0xFF1D3B2A), RoundedCornerShape(6.dp))
                     .padding(horizontal = 8.dp, vertical = 3.dp))
            Text(listOfNotNull(rig.hello?.capabilities?.modelName, r?.mode).joinToString(" · "), fontSize = 12.sp, color = Page.TEXTE_2,
                 modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            ptt?.totSeconds?.let { Text(Tr.t("cw.tot", "time" to Format.duration(it)), fontSize = 12.sp, color = Page.TEXTE_2) }
        }
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(Format.frequency(carrier), fontSize = if (wide) 44.sp else 32.sp, fontWeight = FontWeight.SemiBold, color = Page.TEXTE)
            Text(Tr.t("cw.carrier"), fontSize = 13.sp, color = Page.TEXTE_2, modifier = Modifier.weight(1f))
            Text(Tr.t("cw.dial", "freq" to Format.frequency(r?.frequencyHz)), fontSize = 12.sp, color = Page.TEXTE_2)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Meter(Tr.t("cw.m_pwr"), levels["RFPOWER"]?.let { "${(it * 100).toInt()} %" }, null)                // i18n-ok
            Meter(Tr.t("cw.m_alc"), null, levels["ALC"]?.toFloat())                                              // i18n-ok
            Meter(Tr.t("cw.m_swr"), if (tx) levels["SWR"]?.let { Format.decimal(it, 1) } else null, null)       // i18n-ok
            if (tx) Meter(Tr.t("cw.m_po"), null, levels["RFPOWER_METER"]?.toFloat())                          // i18n-ok
            else Meter(Tr.t("cw.m_s"), Format.sMeter(r?.strengthDb), null)
        }
    }
}

@Composable
private fun RowScope.Meter(label: String, value: String?, fraction: Float?) {
    Column(Modifier.weight(1f).background(Page.PANNEAU, RoundedCornerShape(8.dp)).border(1.dp, Page.LIGNE, RoundedCornerShape(8.dp))
        .padding(horizontal = 7.dp, vertical = 5.dp)) {
        Text(label, fontSize = 10.sp, color = Page.TEXTE_2)
        if (fraction != null) {
            Box(Modifier.padding(top = 7.dp).fillMaxWidth().height(6.dp).background(Page.LIGNE, RoundedCornerShape(3.dp))) {
                Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).height(6.dp).background(Page.MESURE, RoundedCornerShape(3.dp)))
            }
        } else {
            Text(value ?: "—", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = if (value == null) Page.TEXTE_2 else Page.MESURE)
        }
    }
}

@Composable
private fun CwDecoded(cw: CwUi, modifier: Modifier, big: Boolean) {
    Box(modifier.background(Page.CHAMP, RoundedCornerShape(8.dp)).border(1.dp, Page.LIGNE, RoundedCornerShape(8.dp))
        .padding(horizontal = 10.dp, vertical = 6.dp), contentAlignment = if (big) Alignment.TopStart else Alignment.CenterStart) {
        Text(cw.decoded.ifEmpty { Tr.t("cw.decoded_empty") }, fontFamily = FontFamily.Monospace, fontSize = if (big) 18.sp else 15.sp,
             color = if (cw.decoded.isEmpty()) Page.TEXTE_2 else Page.TEXTE, maxLines = if (big) 6 else 1,
             overflow = TextOverflow.Clip)
    }
}

@Composable
private fun CwNotice(cw: CwUi) {
    // place réservée même sans message : un message qui apparaît ne déplace jamais « Armer CW » ni les palettes
    Text(cw.notice, fontSize = 12.sp, color = Page.ALERTE, maxLines = 1, overflow = TextOverflow.Ellipsis,
         modifier = Modifier.fillMaxWidth().height(18.dp))
}

@Composable
private fun CwStats(cw: CwUi) {
    Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(Tr.t("cw.st_delay", "ms" to (cw.delayMs?.toString() ?: "—")), fontSize = 12.sp, color = Page.TEXTE_2)
        Text(Tr.t("cw.st_buffer", "ms" to (cw.bufferMs?.toString() ?: "—")), fontSize = 12.sp,
             color = if ((cw.bufferMs ?: 1) <= 0) Page.TX else Page.TEXTE_2)
        Text(Tr.t("cw.st_jitter", "ms" to (cw.jitterP95Ms?.let { Format.decimal(it, 0) } ?: "—")), fontSize = 12.sp, color = Page.TEXTE_2)
        Text(Tr.t("cw.st_late", "n" to cw.late), fontSize = 12.sp, color = Page.TEXTE_2)
        Text(Tr.t("cw.st_cuts", "n" to cw.leaseCuts), fontSize = 12.sp, color = Page.TEXTE_2)
    }
}

@Composable
private fun ColumnScope.CwSettingsBlock(cw: CwUi, s: CwSettings, change: (CwSettings) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Setting(Tr.t("cw.s_wpm")) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()) {
                SmallKey("−") { change(s.copy(wpm = (s.wpm - 1).coerceAtLeast(5))) }                              // i18n-ok
                Text("${s.wpm}", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Page.TEXTE)
                SmallKey("+") { change(s.copy(wpm = (s.wpm + 1).coerceAtMost(40))) }                              // i18n-ok
            }
        }
        if (s.keyInterface != CwInterface.STRAIGHT) {
            Setting(Tr.t("cw.s_weight"), onClick = { change(s.copy(weight = if (s.weight >= 4.5) 2.5 else s.weight + 0.5)) }) {
                Text(Format.decimal(s.weight, 1), fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Page.TEXTE)
            }
        }
        Setting(Tr.t("cw.s_tone"), enabled = !cw.armed, onClick = { change(s.copy(toneHz = if (s.toneHz >= 900) 500 else s.toneHz + 50)) }) {
            Text(Tr.t("cw.hz", "hz" to s.toneHz), fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Page.TEXTE)
        }
        Setting(Tr.t("cw.s_sidetone"), onClick = {
            change(s.copy(sidetone = when { s.sidetone < 0.15 -> 0.3; s.sidetone < 0.45 -> 0.6; s.sidetone < 0.8 -> 1.0; else -> 0.0 }))
        }) {
            Text("${(s.sidetone * 100).toInt()} %", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Page.TEXTE)  // i18n-ok
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        val choices = if (s.pads == 2) listOf(CwInterface.IAMBIC_A, CwInterface.IAMBIC_B, CwInterface.SINGLE_LEVER)
                      else listOf(CwInterface.STRAIGHT)
        for (i in choices) {
            val on = i == s.keyInterface
            Box(Modifier.weight(1f).height(34.dp)
                .background(if (on) Page.SELECTION else Page.COMMANDE, RoundedCornerShape(17.dp))
                .border(1.dp, if (on) Page.ACCENT else Page.BORD, RoundedCornerShape(17.dp))
                .clickable(enabled = !cw.armed) { change(s.copy(keyInterface = i)) }, contentAlignment = Alignment.Center) {
                Text(Tr.t("cw.if_" + i.wire), fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                     color = if (on) Page.TEXTE else Page.TEXTE_2, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (s.pads == 2) {
            Box(Modifier.width(48.dp).height(34.dp).background(if (s.reversed) Page.SELECTION else Page.COMMANDE, RoundedCornerShape(17.dp))
                .border(1.dp, Page.BORD, RoundedCornerShape(17.dp)).clickable { change(s.copy(reversed = !s.reversed)) },
                contentAlignment = Alignment.Center) { Text("·⇄–", color = Page.TEXTE, fontSize = 13.sp) }          // i18n-ok
        }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = s.align, enabled = !cw.armed, onCheckedChange = { change(s.copy(align = it)) })
        Text(Tr.t("cw.align"), fontSize = 12.sp, color = Page.TEXTE)
    }
}

@Composable
private fun RowScope.Setting(label: String, enabled: Boolean = true, onClick: (() -> Unit)? = null,
                             content: @Composable () -> Unit) {
    var m = Modifier.weight(1f).background(Page.PANNEAU, RoundedCornerShape(10.dp)).border(1.dp, Page.CADRE, RoundedCornerShape(10.dp))
    if (onClick != null) m = m.clickable(enabled = enabled) { onClick() }
    Column(m.padding(horizontal = 8.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, fontSize = 10.sp, color = Page.TEXTE_2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Box(Modifier.height(32.dp), contentAlignment = Alignment.CenterStart) { content() }
    }
}

@Composable
private fun SmallKey(text: String, onClick: () -> Unit) {
    Box(Modifier.width(32.dp).height(32.dp).background(Page.COMMANDE, RoundedCornerShape(8.dp))
        .border(1.dp, Page.BORD, RoundedCornerShape(8.dp)).clickable { onClick() }, contentAlignment = Alignment.Center) {
        Text(text, fontSize = 18.sp, color = Page.TEXTE)
    }
}

@Composable
private fun PadSelector(s: CwSettings, change: (CwSettings) -> Unit, modifier: Modifier = Modifier) {
    Row(modifier.background(Page.CHAMP, RoundedCornerShape(10.dp)).border(1.dp, Page.BORD, RoundedCornerShape(10.dp)).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        for (pads in listOf(1, 2)) {
            val on = s.pads == pads
            Box(Modifier.height(40.dp).background(if (on) Page.ACCENT else Color.Transparent, RoundedCornerShape(8.dp))
                .clickable { if (!on) change(s.copy(keyInterface = if (pads == 1) CwInterface.STRAIGHT else CwInterface.IAMBIC_B)) }
                .padding(horizontal = 12.dp), contentAlignment = Alignment.Center) {
                Text(Tr.plural("cw.pads", pads), fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                     color = if (on) Color.White else Page.TEXTE_2)
            }
        }
    }
}

@Composable
private fun RigScope.ArmButton(cw: CwUi, modifier: Modifier) {
    val (label, bg, fg) = when {
        cw.armed -> Triple(Tr.t("cw.disarm"), Page.TX, Color.White)
        cw.requested -> Triple(Tr.t("cw.arming"), Page.SELECTION, Page.TEXTE_2)
        !rig.armed -> Triple(Tr.t("cw.arm"), Page.COMMANDE, Page.TEXTE_2)     // « Émission autorisée » d'abord : terne
        else -> Triple(Tr.t("cw.arm"), Page.SELECTION, Page.TEXTE)
    }
    val usable = connected && rig.protocolOk && !listener &&
        (cw.armed || (!cw.requested && ptt?.transmitting != true))
    Box(modifier.background(bg, RoundedCornerShape(12.dp)).border(1.dp, if (cw.armed) Page.TX else Page.ACCENT, RoundedCornerShape(12.dp))
        .clickable(enabled = usable) { if (cw.armed) RigHub.cwDisarm() else RigHub.cwArm() }, contentAlignment = Alignment.Center) {
        Text(label, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = fg)
    }
}

/** « Émission autorisée » dans l'onglet même (le smartphone n'y a pas de barre d'onglets) : exigée pour armer la CW,
 *  comme pour le PTT ; la retirer désarme la CW. */
@Composable
private fun RigScope.TxAllowedRow() {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        AppSwitch(checked = rig.armed, onCheckedChange = { RigHub.setArmed(it) }, enabled = connected && rig.protocolOk && !listener)
        Spacer(Modifier.width(8.dp))
        Text(Tr.t("rigparts.armed"), color = Page.TEXTE, fontSize = 14.sp, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun StopButton(modifier: Modifier) {
    Box(modifier.background(Page.TX_FOND, RoundedCornerShape(12.dp)).border(1.dp, Page.TX, RoundedCornerShape(12.dp))
        .clickable { RigHub.stop() }, contentAlignment = Alignment.Center) {
        Text(Tr.t("cw.stop"), color = Page.TX, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 2.sp)
    }
}

/** Palettes tactiles : chaque palette suit SON doigt (multitouche), instant relevé au toucher (horloge du service). */
@Composable
private fun Pads(cw: CwUi, s: CwSettings, modifier: Modifier) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        if (s.pads == 2) {
            Pad(Paddle.DOT, "·", Tr.t("cw.pad_dots"), cw.armed, Modifier.weight(1f).fillMaxHeight())           // i18n-ok
            Pad(Paddle.DASH, "–", Tr.t("cw.pad_dashes"), cw.armed, Modifier.weight(1f).fillMaxHeight())        // i18n-ok
        } else {
            Pad(Paddle.DOT, Tr.t("cw.key"), Tr.t(if (cw.armed) "cw.key_hint" else "cw.key_disarmed"), cw.armed,
                Modifier.weight(1f).fillMaxHeight())
        }
    }
}

@Composable
private fun Pad(paddle: Paddle, symbol: String, hint: String, armed: Boolean, modifier: Modifier) {
    var pressed by remember { mutableStateOf(false) }
    val haptic = LocalHapticFeedback.current
    val border = when { !armed -> Page.BORD; pressed -> Page.TX; else -> Page.BORD }
    Box(modifier.background(if (pressed && armed) Page.TX_FOND else if (armed) Page.CHAMP else Page.PANNEAU, RoundedCornerShape(18.dp))
        .border(2.dp, border, RoundedCornerShape(18.dp))
        .pointerInput(paddle, armed) {
            if (!armed) {
                pressed = false                                    // désarmée pendant un appui : la palette se relâche
                return@pointerInput
            }
            awaitEachGesture {
                val down = awaitFirstDown(requireUnconsumed = false)
                val offset = SystemClock.elapsedRealtime() - SystemClock.uptimeMillis()   // même horloge que le service
                pressed = true
                RigHub.cwPress(paddle, true, (down.uptimeMillis + offset).toDouble())
                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                var upAt = down.uptimeMillis
                while (true) {
                    val event = awaitPointerEvent()
                    val change = event.changes.firstOrNull { it.id == down.id } ?: break
                    upAt = change.uptimeMillis
                    change.consume()
                    if (!change.pressed) break
                }
                pressed = false
                RigHub.cwPress(paddle, false, (upAt + offset).toDouble())
            }
        }, contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(symbol, fontSize = if (symbol.length <= 1) 48.sp else 20.sp, fontWeight = FontWeight.Bold,
                 color = if (armed) Page.TEXTE else Page.TEXTE_2)
            Text(hint, fontSize = 12.sp, color = Page.TEXTE_2)
        }
    }
}
