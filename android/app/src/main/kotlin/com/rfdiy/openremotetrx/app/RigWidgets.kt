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

// Composants de l'écran de la station (découpés de RigScreen.kt, étape 148 : déplacement sans changement).

private val TX_RED = Page.TX                     // couleurs de la page web (client.css)
private val WARN = Page.ALERTE
private val SQL_OPEN = Page.SUCCES
private val HEALTH = mapOf("green" to Page.SUCCES, "orange" to Page.ALERTE, "red" to Page.TX, "off" to Page.TEXTE_2)
private val DOT_COLORS = mapOf(1 to Page.TEXTE_2, 2 to Page.ALERTE, 3 to Page.TX)    // pastilles des bandes (page : lvl1..3)

/** Anti-rebond du PTT : Android peut livrer un « clic fantôme » juste après un appui (CLAUDE.md, page web). */
internal class Debounce(private val ms: Long = 600) {
    private var last = 0L
    fun pass(): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (now - last < ms) return false
        last = now
        return true
    }
}

/**
 * Paysage : spectre HF du poste en plein écran avec les spots du Cluster DX. En haut, toujours : fréquence, mode,
 * état de l'émission (celui de la station) et STOP. Pour émettre, revenir en portrait (PTT et « Émission autorisée »).
 */
@Composable
internal fun LandscapeScope(ui: RigUi, canSet: Boolean, onTune: (Long) -> Unit, modifier: Modifier) {
    val rig = ui.rig
    val ptt = rig.ptt
    val radio = rig.state?.rig
    val screenH = LocalConfiguration.current.screenHeightDp.dp
    Column(modifier.fillMaxSize().padding(horizontal = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(Radio.formatIcom(radio?.frequencyHz), fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
            Text(Radio.modeLabel(radio?.mode), style = MaterialTheme.typography.titleSmall)
            Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.weight(1f))
            rig.reconnect?.let { Text("LIAISON PERDUE : reconnexion…", color = TX_RED, fontWeight = FontWeight.Bold) }
            if (ptt != null) {
                Text(
                    if (ptt.mine && ptt.transmitting) "ÉMISSION EN COURS" + (ptt.totSeconds?.let { " " + Format.duration(it) } ?: "") else ptt.label,
                    color = if (ptt.transmitting) Color.White else MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(if (ptt.transmitting) TX_RED else Color.Transparent, RoundedCornerShape(6.dp))
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
            Button(
                onClick = { RigHub.stop() }, enabled = rig.status == LinkStatus.CONNECTED,
                colors = ButtonDefaults.buttonColors(containerColor = TX_RED, contentColor = Color.White),
                modifier = Modifier.height(40.dp),
            ) { Text("STOP", fontWeight = FontWeight.Bold) }
        }
        HfScopeView(
            ui, canSet, onTune, onClose = null,
            plotModifier = Modifier.fillMaxWidth().height((screenH - 150.dp).coerceAtLeast(120.dp)),
        )
    }
}

/** Indicateur : libellé, barre, valeur (orange si SWR >= 2 ou ALC >= 90 %). */
@Composable
internal fun MeterRow(meter: Meter, warn: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(meter.label, style = MaterialTheme.typography.labelMedium, modifier = Modifier.width(48.dp))
        LinearProgressIndicator(
            progress = { meter.fraction },
            drawStopIndicator = {},
            color = if (warn) WARN else MaterialTheme.colorScheme.primary,
            modifier = Modifier.weight(1f).height(6.dp),
        )
        Text(meter.text, style = MaterialTheme.typography.labelMedium, modifier = Modifier.width(48.dp), textAlign = TextAlign.End)
    }
}

@Composable
internal fun Banner(text: String, color: Color, big: Boolean = false, textColor: Color = Color.White) {
    Text(
        text,
        color = textColor,
        fontSize = if (big) 17.sp else 13.sp,
        fontWeight = if (big) FontWeight.Bold else FontWeight.Normal,
        modifier = Modifier.fillMaxWidth().background(color, RoundedCornerShape(8.dp)).padding(horizontal = 10.dp, vertical = 8.dp),
    )
}

/** Onglets de l'écran de la station (choix de l'utilisateur, 2026-10-29). */
internal enum class Tab(val symbol: String, val label: String) {
    STATION("◉", "Station"), SPECTRE("≋", "Spectre"), MEMOIRES("★", "Mémoires"),
    /** Présence de groupe : seulement quand la station fait partie d'un groupe (pictogramme dessiné : tête stylisée). */
    AMIS("", "Amis"),
    EQ("♫", "Audio"), REGLAGES("⚙", "Réglages"),
}

/** Pictogramme d'un onglet : le symbole, ou pour « Amis » une tête stylisée (cercle et épaules), comme la pièce jointe
 *  de l'utilisateur ; dessinée (et non un emoji en couleur) pour suivre la couleur de l'onglet. */
@Composable
internal fun TabIcon(tab: Tab, color: Color) {
    if (tab != Tab.AMIS) {
        Text(tab.symbol, fontSize = 16.sp, color = color)
        return
    }
    androidx.compose.foundation.Canvas(Modifier.size(18.dp)) {
        val w = size.width
        drawCircle(color, radius = w * 0.24f, center = androidx.compose.ui.geometry.Offset(w / 2, w * 0.30f))
        drawArc(color, startAngle = 180f, sweepAngle = 180f, useCenter = true,
            topLeft = androidx.compose.ui.geometry.Offset(w * 0.08f, w * 0.60f),
            size = androidx.compose.ui.geometry.Size(w * 0.84f, w * 0.80f))
    }
}

/** Barre d'onglets compacte (52 dp) : l'onglet choisi sur fond « sélection », comme les boutons de la page. */
@Composable
internal fun TabBar(current: Tab, tabs: List<Tab> = Tab.entries, onSelect: (Tab) -> Unit) {
    Row(
        Modifier.fillMaxWidth().background(Page.PANNEAU).padding(horizontal = 8.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        for (item in tabs) {
            val on = item == current
            Column(
                Modifier.weight(1f).height(48.dp).background(if (on) Page.SELECTION else Color.Transparent, RoundedCornerShape(12.dp))
                    .clickable { onSelect(item) },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
            ) {
                TabIcon(item, if (on) Page.MESURE else Page.TEXTE_2)
                Text(item.label, style = MaterialTheme.typography.labelSmall, color = if (on) Page.TEXTE else Page.TEXTE_2,
                    fontWeight = if (on) FontWeight.Bold else FontWeight.Normal)
            }
        }
    }
}

/** Carte d'une rubrique (page : panneaux arrondis à liseré fin). */
@Composable
internal fun Panel(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        shape = RoundedCornerShape(14.dp), color = Page.PANNEAU, contentColor = Page.TEXTE,
        border = BorderStroke(1.dp, Page.LIGNE), modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp), content = content)
    }
}

/** Afficheur réduit en tête des autres onglets : fréquence, mode, S-mètre, état de l'émission (celui de la station). */
@Composable
internal fun MiniDisplay(rig: RigState, shownHz: Long?, mineTx: Boolean) {
    val radio = rig.state?.rig
    val ptt = rig.ptt
    Surface(
        shape = RoundedCornerShape(14.dp), color = if (ptt?.transmitting == true) Page.TX_FOND else Page.INSTRUMENT,
        contentColor = Page.TEXTE, border = BorderStroke(1.dp, if (ptt?.transmitting == true) TX_RED else Page.LIGNE),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(Radio.formatIcom(shownHz), fontSize = 22.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
            Text(Radio.modeLabel(radio?.mode), style = MaterialTheme.typography.labelLarge)
            Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f))
            if (ptt != null) Text(
                if (mineTx) "TX" + (ptt.totSeconds?.let { " " + Format.duration(it) } ?: "") else if (ptt.transmitting) "TX autre" else "RX",
                fontWeight = FontWeight.Bold, color = if (ptt.transmitting) TX_RED else Page.SUCCES,
            )
        }
    }
}

/** Touche d'accord de l'afficheur (− / + / pas) : plus grande qu'une puce, même dessin. */
@Composable
internal fun TuneKey(label: String, width: androidx.compose.ui.unit.Dp, height: androidx.compose.ui.unit.Dp,
                    fontSize: androidx.compose.ui.unit.TextUnit, enabled: Boolean = true, onClick: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    Surface(
        shape = RoundedCornerShape(8.dp), color = Color.Transparent,
        border = BorderStroke(1.dp, colors.outline.copy(alpha = 0.7f)),
        modifier = Modifier.size(width = width, height = height).clickable(enabled = enabled, onClick = onClick),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(label, fontSize = fontSize, fontWeight = FontWeight.Bold, maxLines = 1,
                color = if (enabled) colors.onSurface else colors.onSurface.copy(alpha = 0.38f))
        }
    }
}
