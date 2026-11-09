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

/** Onglet Station : afficheur, squelch, clarifieur, petit waterfall, bandes, modes, fonctions du poste. */
@Composable
internal fun RigScope.StationTab(miniWaterfall: Boolean = true) {
            // Afficheur : fréquence (toucher = saisie), mode, S-mètre
            Surface(shape = RoundedCornerShape(12.dp), color = Page.INSTRUMENT, contentColor = Page.TEXTE, border = BorderStroke(1.dp, Page.LIGNE), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            Radio.formatIcom(shownHz),
                            fontSize = 34.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace, maxLines = 1, softWrap = false,
                            modifier = Modifier.weight(1f).clickable(enabled = canSet) { entry = true },
                        )
                        // Accord à droite de la fréquence (étape 97, place gagnée pour le petit waterfall) : − et + d'un pas,
                        // pas dessous (toucher = pas suivant)
                        Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(5.dp)) {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                TuneKey("−", width = 54.dp, height = 40.dp, fontSize = 24.sp, enabled = canSet) { tune(-1) }
                                TuneKey("+", width = 54.dp, height = 40.dp, fontSize = 24.sp, enabled = canSet) { tune(1) }
                            }
                            TuneKey(stepLabel(step), width = 114.dp, height = 32.dp, fontSize = 15.sp) {
                                stepIndex = (stepIndex + 1) % Radio.STEPS_HZ.size
                            }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(Radio.modeLabel(radio?.mode), style = MaterialTheme.typography.titleMedium)
                        Radio.bandOf(shownHz)?.let { Text("${it.key} m", style = MaterialTheme.typography.titleMedium) }
                        Text(Format.sMeter(radio?.strengthDb), style = MaterialTheme.typography.titleMedium)
                        if (radio != null && !radio.connected) Text("liaison CAT PERDUE", color = WARN)
                    }
                    // Voyants (comme sur un poste) : vert = actif, gris = éteint
                    val lights = Indicators.of(hello, rig.state)
                    if (lights.isNotEmpty()) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            for (light in lights) {
                                Text(
                                    light.label, style = MaterialTheme.typography.labelMedium,
                                    fontWeight = if (light.on) FontWeight.Bold else FontWeight.Normal,
                                    color = when {
                                        light.alert -> TX_RED                                   // OVERLOAD ALC
                                        light.on -> SQL_OPEN
                                        else -> MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f)
                                    },
                                )
                            }
                        }
                    }
                    // Repère du squelch (page : barre orange sur le S-mètre) : petit triangle orange au-dessus de la barre,
                    // suit le curseur pendant le réglage ; absent si le squelch est ouvert (0)
                    val sqlMark = Radio.squelchMarkerFraction(squelchDrag?.toDouble() ?: radio?.levels?.get("SQL"))
                    Box(Modifier.fillMaxWidth().height(15.dp)) {
                        LinearProgressIndicator(
                            progress = { Radio.sMeterFraction(radio?.strengthDb) },
                            drawStopIndicator = {},                       // pas de point en bout de barre : il ferait croire à S9+60
                            modifier = Modifier.fillMaxWidth().height(8.dp).align(Alignment.BottomStart),
                        )
                        if (sqlMark != null) {
                            Canvas(Modifier.fillMaxSize()) {
                                val x = sqlMark * size.width
                                val half = 5.dp.toPx()
                                val tip = size.height - 8.dp.toPx() + 2.dp.toPx()     // pointe posée sur le haut de la barre
                                drawPath(Path().apply { moveTo(x - half, 0f); lineTo(x + half, 0f); lineTo(x, tip); close() }, Page.ALERTE)
                            }
                        }
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        for (label in listOf("S1", "3", "5", "7", "9", "+20", "+40", "+60")) {
                            Text(label, style = MaterialTheme.typography.labelSmall)
                        }
                    }
                    // Bargraphs POWER, SWR, ALC toujours visibles (comme sur un poste ; à zéro en réception)
                    for (m in Indicators.txMeters(rig.state)) {
                        MeterRow(m, warn = (m.key == "SWR" && m.fraction >= 0.5f) || (m.key == "ALC" && m.fraction >= 0.9f))
                    }
                    // État de l'émission (station), bien visible dans l'afficheur, au-dessus du squelch
                    if (ptt != null) {
                        Banner(
                            when {
                                mineTx -> "ÉMISSION EN COURS" + (ptt.totSeconds?.let { " — coupure dans ${Format.duration(it)}" } ?: "")
                                ptt.other -> "${ptt.label} : autre client (${rig.state?.ptt?.owner ?: "?"})"
                                else -> ptt.label
                            },
                            if (ptt.transmitting) TX_RED else Page.SELECTION, big = true,
                            textColor = Color.White,
                        )
                    }
                    radio?.levels?.get("SQL")?.let { sql ->
                        // Squelch : une seule commande à la fin du geste (page : pas une par pixel)
                        val shown = squelchDrag ?: sql.toFloat()
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            // Vert : squelch ouvert (le son passe ; estimation par le S-mètre, la station ne donne pas le DCD)
                            Text("SQL", style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(36.dp),
                                color = if (Radio.squelchOpen(sql, radio.strengthDb)) SQL_OPEN else Color.Unspecified,
                                fontWeight = if (Radio.squelchOpen(sql, radio.strengthDb)) FontWeight.Bold else FontWeight.Normal)
                            Slider(
                                value = shown, onValueChange = { squelchDrag = it }, enabled = canSet,
                                onValueChangeFinished = { squelchDrag?.let { RigHub.setSquelch(it.toDouble()) }; squelchDrag = null },
                                modifier = Modifier.weight(1f),
                            )
                            val percent = (shown * 100).roundToInt()
                            Text(if (percent == 0) "ouvert" else "$percent %", style = MaterialTheme.typography.labelLarge,
                                modifier = Modifier.width(56.dp), textAlign = TextAlign.End)
                        }
                    }
                    // Clarifieur : ΔTX (XIT) ou RIT en service => curseur du décalage (commun aux deux sur l'IC-7300), pas de 10 Hz
                    val clar = when {
                        radio?.functions?.get("XIT") == true -> "XIT"
                        radio?.functions?.get("RIT") == true -> "RIT"
                        else -> null
                    }
                    if (clar != null) {
                        val max = Radio.clarifierMax(clar, if (clar == "XIT") hello?.capabilities?.maxXitHz else hello?.capabilities?.maxRitHz)
                        val current = (radio?.offsets?.get(clar) ?: 0).coerceIn(-max, max)
                        val shown = offsetDrag ?: current.toFloat()
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(if (clar == "XIT") "ΔTX" else "RIT", style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(36.dp))
                            Slider(
                                value = shown, onValueChange = { offsetDrag = it }, enabled = canSet,
                                valueRange = -max.toFloat()..max.toFloat(),
                                onValueChangeFinished = { offsetDrag?.let { RigHub.setOffset(clar, it.roundToInt()) }; offsetDrag = null },
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                (if (shown >= 0) "+" else "") + (Math.round(shown / 10.0) * 10) + " Hz",
                                style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(72.dp).clickable(enabled = canSet) {
                                    RigHub.setOffset(clar, 0)                                       // toucher la valeur : remise à zéro
                                }, textAlign = TextAlign.End,
                            )
                        }
                    }
                }
            }

            // Petit waterfall HF juste avant les bandes (toucher = réglages) ; « WF » en bas de l'écran l'affiche ou le masque
            if (miniWaterfall && miniWf && connected && HfScope.configured(hello)) Panel { MiniWaterfall(ui, canSet, onHide = { setMiniWf(false) }) }
            Panel {
            // Bandes préférées, dans l'ordre choisi (✎ : choisir et ordonner) ; pastille = spots actifs (Cluster DX)
            val dots = rig.bandDots(System.currentTimeMillis())
            FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                val current = Radio.bandOf(radio?.frequencyHz)?.key
                for (band in Radio.favoriteBands(bandsPref)) {
                    CompactChip(band.key, onClick = { RigHub.selectBand(band.key) }, enabled = canSet, selected = band.key == current,
                        dot = dots[band.key]?.let { DOT_COLORS[it.level] })
                }
                CompactChip("✎", onClick = { bandsDialog = true })
            }

            }
            Panel {
            // Modes du poste (émission : seulement ceux de tx_modes s'ils sont imposés)
            val modes = Radio.orderModes(hello?.capabilities?.modes.orEmpty())
            if (modes.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    for (mode in modes) {
                        CompactChip(Radio.modeLabel(mode), onClick = { RigHub.setMode(mode) }, enabled = canSet, selected = mode == radio?.mode)
                    }
                }
                if (hello?.txModes?.isNotEmpty() == true) {
                    Text("Émission permise en : " + hello.txModes.joinToString(", ") { Radio.modeLabel(it) },
                        style = MaterialTheme.typography.bodySmall)
                }
            }

            }
            Panel {

            // Fonctions du poste (comme la page) : verrouillées pendant l'émission
            val chips = Controls.chips(hello, rig.state)
            if (chips.isNotEmpty()) {
                // Appui : marche / arrêt (comme la page) ; appui LONG sur NR ou NB : niveaux de NR et NB (fenêtre)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    for (chip in chips) {
                        CompactChip(
                            chip.label, onClick = { RigHub.pressControl(chip.key) }, enabled = canSet, selected = chip.on,
                            onLongClick = if (chip.key == "NR" || chip.key == "NB") ({ levelsDialog = true }) else null,
                        )
                    }
                }
            }

            // Autres mesures (COMP) en une ligne, s'il y en a ; POWER, SWR, ALC, Vd et température sont dans l'afficheur
            val others = Controls.meters(rig.state).filterNot { it.key in setOf("PO", "SWR", "ALC", "VD", "TEMP") }
            if (others.isNotEmpty()) {
                Text(others.joinToString("   ") { "${it.label} ${it.text}" }, style = MaterialTheme.typography.bodySmall)
            }

            }
}
