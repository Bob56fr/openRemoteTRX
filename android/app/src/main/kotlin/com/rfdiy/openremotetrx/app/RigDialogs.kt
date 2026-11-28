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
import androidx.compose.ui.graphics.lerp
import com.rfdiy.openremotetrx.logic.RecentFreq
import com.rfdiy.openremotetrx.logic.FreqHistory
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.BoxWithConstraints
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
import com.rfdiy.openremotetrx.logic.Tr
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

// Fenêtres de l'écran de la station (découpées de RigScreen.kt, étape 148 : déplacement sans changement).

/** Mémoire en cours de création (`id` null) ou de modification. */
internal data class MemoryEdit(val id: String?, val name: String, val hz: Long?, val mode: String?, val favorite: Boolean)

/** Niveaux réglables (NR, NB) : plage [min, max, pas] déclarée par le poste ET valeur lue (page : levelRange). */
internal fun levelRanges(hello: Hello?, levels: Map<String, Double>?): Map<String, List<Double>> =
    listOf("NR", "NB").mapNotNull { name ->
        val range = hello?.capabilities?.levelRanges?.get(name)
        if (range != null && range.size == 3 && range[1] > range[0] && levels?.containsKey(name) == true) name to range else null
    }.toMap()

internal fun levelText(value: Double, range: List<Double>): String =
    if (range[2] > 0) "${((value - range[0]) / range[2]).roundToInt()} / ${((range[1] - range[0]) / range[2]).roundToInt()}"
    else String.format(Locale.ROOT, "%.2f", value)

/** Fenêtre des niveaux NR / NB : une commande à la fin de chaque geste ; verrouillée pendant l'émission. */
@Composable
internal fun LevelsDialog(ranges: Map<String, List<Double>>, levels: Map<String, Double>, enabled: Boolean, onDismiss: () -> Unit) {
    val dragging = remember { mutableStateMapOf<String, Float>() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(Tr.t("rigdialogs.levels_title")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((name, range) in ranges) {
                    val value = dragging[name] ?: (levels[name] ?: range[0]).toFloat()
                    val steps = if (range[2] > 0) (((range[1] - range[0]) / range[2]).roundToInt() - 1).coerceAtLeast(0) else 0
                    Text(Tr.t("rigdialogs.level_line", "name" to (if (name == "NR") Tr.t("rigdialogs.nr_label") else Tr.t("rigdialogs.nb_label")), "value" to levelText(value.toDouble(), range)))
                    Slider(
                        value = value, onValueChange = { dragging[name] = it }, enabled = enabled,
                        valueRange = range[0].toFloat()..range[1].toFloat(), steps = steps,
                        onValueChangeFinished = { dragging.remove(name)?.let { RigHub.setLevel(name, it.toDouble()) } },
                    )
                }
                if (ranges.isEmpty()) Text(Tr.t("rigdialogs.no_levels"))
                if (!enabled) Text(Tr.t("rigdialogs.locked_tx"), color = WARN)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.close")) } },
    )
}

/** Création ou modification d'une mémoire partagée ; suppression confirmée en deux temps (comme la page). */
@Composable
internal fun MemoryDialog(edit: MemoryEdit, modes: List<String>, onDismiss: () -> Unit) {
    var name by remember { mutableStateOf(edit.name) }
    var freq by remember { mutableStateOf(edit.hz?.let { Radio.formatIcom(it) } ?: "") }
    var mode by remember { mutableStateOf(edit.mode ?: modes.firstOrNull() ?: "") }
    var favorite by remember { mutableStateOf(edit.favorite) }
    var deleteArmed by remember { mutableStateOf(false) }
    val hz = Radio.parseFrequencyEntry(freq)
    val nameOk = name.isNotBlank() && name.trim().length <= RigSession.MEMORY_NAME_MAX
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (edit.id == null) Tr.t("rigdialogs.new_memory") else Tr.t("rigdialogs.memory")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text(Tr.t("rigdialogs.name")) }, singleLine = true)
                OutlinedTextField(
                    freq, { freq = it }, label = { Text(Tr.t("rigdialogs.frequency_label")) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    supportingText = { Text(hz?.let { Format.frequency(it) } ?: Tr.t("rigdialogs.invalid_frequency")) },
                )
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (m in modes.ifEmpty { listOfNotNull(edit.mode) }) {
                        FilterChip(selected = m == mode, onClick = { mode = m }, label = { Text(Radio.modeLabel(m)) })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AppSwitch(checked = favorite, onCheckedChange = { favorite = it })
                    Spacer(Modifier.width(8.dp))
                    Text(Tr.t("rigdialogs.favorite"))
                }
                if (edit.id != null) {
                    TextButton(onClick = {
                        if (deleteArmed) { RigHub.deleteMemory(edit.id); onDismiss() } else deleteArmed = true
                    }) { Text(if (deleteArmed) Tr.t("rigdialogs.confirm_delete") else Tr.t("common.delete"), color = MaterialTheme.colorScheme.error) }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                RigHub.saveMemory(name.trim(), hz!!, mode, favorite, edit.id)
                onDismiss()
            }, enabled = nameOk && hz != null && mode.isNotEmpty()) { Text(Tr.t("common.save")) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.cancel")) } },
    )
}

internal fun stepLabel(hz: Long): String = when {
    hz >= 1000 && hz % 1000 == 0L -> "${hz / 1000} kHz"
    hz >= 1000 -> Format.decimal(hz / 1000.0, 1) + " kHz"
    else -> "$hz Hz"
}

/**
 * Saisie de la fréquence (étape 410) : clavier de l'application (pas celui du téléphone), mêmes formats que la page
 * (7074 = kHz, 14.205 = MHz, 7.074.00 = format du poste), et les 10 dernières fréquences où le poste est resté
 * (fréquence + mode, un toucher = QSY). En fenêtre large (paysage) : clavier à gauche, dernières fréquences à droite.
 */
@Composable
internal fun FrequencyDialog(
    current: Long?, recents: List<RecentFreq>, enabled: Boolean,
    onDismiss: () -> Unit, onRecent: (RecentFreq) -> Unit, onSet: (Long) -> Unit,
) {
    var text by remember { mutableStateOf("") }
    val parsed = Radio.parseFrequencyEntry(text)
    // Fond un peu plus clair que les autres fenêtres, filet autour de la fenêtre, de l'affichage et des touches
    val edge = BorderStroke(1.dp, MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f))
    val dialogShape = RoundedCornerShape(24.dp)
    AlertDialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
        shape = dialogShape,
        containerColor = lerp(MaterialTheme.colorScheme.surfaceContainerHigh, Color.White, 0.12f),
        modifier = Modifier.fillMaxWidth(0.94f).border(edge, dialogShape),
        title = { Text(Tr.t("rigdialogs.frequency")) },
        text = {
            BoxWithConstraints {
                val wide = maxWidth >= 520.dp
                val keypad: @Composable (Modifier) -> Unit = { mod ->
                    Column(mod, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(Tr.t("rigdialogs.current", "frequency" to Radio.formatIcom(current)), style = MaterialTheme.typography.bodySmall)
                        Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.surface, border = edge, modifier = Modifier.fillMaxWidth()) {
                            Text(text.ifEmpty { Tr.t("rigdialogs.frequency_hint") }, fontFamily = FontFamily.Monospace,
                                fontSize = if (text.isEmpty()) 14.sp else 26.sp, textAlign = TextAlign.End,
                                color = if (text.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f) else MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp))
                        }
                        Text(
                            if (text.isBlank()) " " else parsed?.let { "= ${Format.frequency(it)}" } ?: Tr.t("rigdialogs.invalid_frequency"),
                            color = if (parsed == null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        for (row in listOf(listOf("1", "2", "3"), listOf("4", "5", "6"), listOf("7", "8", "9"), listOf(".", "0", "⌫"))) { // i18n-ok
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                for (k in row) {
                                    OutlinedButton(onClick = { text = FreqHistory.key(text, k) }, shape = RoundedCornerShape(8.dp), border = edge,
                                        contentPadding = PaddingValues(0.dp), modifier = Modifier.weight(1f).height(46.dp)) {
                                        Text(k, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                                    }
                                }
                            }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedButton(onClick = { text = "" }, border = edge, modifier = Modifier.weight(1f).height(46.dp)) { Text("C", fontSize = 18.sp) } // i18n-ok
                            Button(onClick = { parsed?.let(onSet) }, enabled = parsed != null && enabled,
                                modifier = Modifier.weight(2f).height(46.dp)) { Text(Tr.t("rigdialogs.go") + " ▶", fontWeight = FontWeight.Bold) } // i18n-ok
                        }
                    }
                }
                val recentList: @Composable (Modifier) -> Unit = { mod ->
                    Column(mod, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(Tr.t("rigdialogs.recent_title"), style = MaterialTheme.typography.labelLarge)
                        if (recents.isEmpty()) Text(Tr.t("rigdialogs.recent_none"), style = MaterialTheme.typography.bodySmall)
                        for (pair in recents.chunked(2)) {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                for (r in pair) {
                                    Surface(
                                        shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.secondaryContainer, border = edge,
                                        modifier = Modifier.weight(1f).clickable(enabled = enabled) { onRecent(r) },
                                    ) {
                                        Text(Radio.formatIcom(r.hz) + "  " + Radio.modeLabel(r.mode.ifEmpty { null }), fontFamily = FontFamily.Monospace,
                                            fontSize = 13.sp, maxLines = 1, modifier = Modifier.padding(horizontal = 8.dp, vertical = 9.dp))
                                    }
                                }
                                if (pair.size == 1) Spacer(Modifier.weight(1f))
                            }
                        }
                        if (!enabled) Text(Tr.t("rigdialogs.locked_tx"), color = WARN, style = MaterialTheme.typography.bodySmall)
                    }
                }
                if (wide) Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    keypad(Modifier.weight(1f))
                    recentList(Modifier.weight(1f).verticalScroll(rememberScrollState()))
                } else Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    keypad(Modifier.fillMaxWidth())
                    HorizontalDivider()
                    recentList(Modifier.fillMaxWidth())
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.cancel")) } },
    )
}

/**
 * Bandes affichées : cocher, ordonner (↑ ↓). Réglage de CE téléphone (la page a le sien). Aucune cochée = toutes.
 */
@Composable
internal fun BandsDialog(current: List<Band>, onDismiss: () -> Unit, onSave: (List<Band>) -> Unit) {
    val order = remember { mutableStateListOf<Band>().apply { addAll(current); addAll(Radio.BANDS.filterNot { it in current }) } }
    val checked = remember { mutableStateMapOf<String, Boolean>().apply { for (b in Radio.BANDS) put(b.key, b in current && current.size < Radio.BANDS.size) } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(Tr.t("rigdialogs.bands_title")) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(Tr.t("rigdialogs.bands_hint"), style = MaterialTheme.typography.bodySmall)
                for ((i, band) in order.withIndex()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = checked[band.key] == true, onCheckedChange = { checked[band.key] = it })
                        Text("${band.key} m", modifier = Modifier.weight(1f))
                        TextButton(onClick = { if (i > 0) { order.removeAt(i); order.add(i - 1, band) } }, enabled = i > 0) { Text("↑") }
                        TextButton(onClick = { if (i < order.size - 1) { order.removeAt(i); order.add(i + 1, band) } }, enabled = i < order.size - 1) { Text("↓") }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { onSave(order.filter { checked[it.key] == true }) }) { Text(Tr.t("common.save")) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(Tr.t("common.cancel")) } },
    )
}
