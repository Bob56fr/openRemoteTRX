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
        title = { Text("Niveaux du poste") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for ((name, range) in ranges) {
                    val value = dragging[name] ?: (levels[name] ?: range[0]).toFloat()
                    val steps = if (range[2] > 0) (((range[1] - range[0]) / range[2]).roundToInt() - 1).coerceAtLeast(0) else 0
                    Text("${if (name == "NR") "Réducteur de bruit (NR)" else "Antiparasite (NB)"} : ${levelText(value.toDouble(), range)}")
                    Slider(
                        value = value, onValueChange = { dragging[name] = it }, enabled = enabled,
                        valueRange = range[0].toFloat()..range[1].toFloat(), steps = steps,
                        onValueChangeFinished = { dragging.remove(name)?.let { RigHub.setLevel(name, it.toDouble()) } },
                    )
                }
                if (ranges.isEmpty()) Text("Le poste ne déclare pas de niveau réglable pour NR ni NB.")
                if (!enabled) Text("Réglages verrouillés pendant l'émission.", color = WARN)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
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
        title = { Text(if (edit.id == null) "Nouvelle mémoire" else "Mémoire") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("Nom") }, singleLine = true)
                OutlinedTextField(
                    freq, { freq = it }, label = { Text("Fréquence (7074 kHz, 14.205 MHz)") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    supportingText = { Text(hz?.let { Format.frequency(it) } ?: "Fréquence invalide") },
                )
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (m in modes.ifEmpty { listOfNotNull(edit.mode) }) {
                        FilterChip(selected = m == mode, onClick = { mode = m }, label = { Text(Radio.modeLabel(m)) })
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AppSwitch(checked = favorite, onCheckedChange = { favorite = it })
                    Spacer(Modifier.width(8.dp))
                    Text("Favorite (en tête de liste)")
                }
                if (edit.id != null) {
                    TextButton(onClick = {
                        if (deleteArmed) { RigHub.deleteMemory(edit.id); onDismiss() } else deleteArmed = true
                    }) { Text(if (deleteArmed) "Confirmer la suppression" else "Supprimer", color = MaterialTheme.colorScheme.error) }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                RigHub.saveMemory(name.trim(), hz!!, mode, favorite, edit.id)
                onDismiss()
            }, enabled = nameOk && hz != null && mode.isNotEmpty()) { Text("Enregistrer") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } },
    )
}

internal fun stepLabel(hz: Long): String = when {
    hz >= 1000 && hz % 1000 == 0L -> "${hz / 1000} kHz"
    hz >= 1000 -> "%.1f kHz".format(hz / 1000.0).replace('.', ',')
    else -> "$hz Hz"
}

/** Saisie au clavier, mêmes formats que la page : 7074 (kHz), 14.205 (MHz), 7.074.00 (format du poste). */
@Composable
internal fun FrequencyDialog(current: Long?, onDismiss: () -> Unit, onSet: (Long) -> Unit) {
    var text by remember { mutableStateOf("") }
    val parsed = Radio.parseFrequencyEntry(text)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Fréquence") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Actuelle : ${Radio.formatIcom(current)}", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    text, { text = it }, singleLine = true, label = { Text("7074 (kHz) ou 14.205 (MHz)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                )
                Text(
                    if (text.isBlank()) "" else parsed?.let { "= ${Format.frequency(it)}" } ?: "Fréquence invalide",
                    color = if (parsed == null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                )
            }
        },
        confirmButton = { TextButton(onClick = { parsed?.let(onSet) }, enabled = parsed != null) { Text("Aller") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } },
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
        title = { Text("Bandes affichées") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("Cochez vos bandes et mettez-les dans l'ordre voulu. Aucune cochée : toutes.", style = MaterialTheme.typography.bodySmall)
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
        confirmButton = { TextButton(onClick = { onSave(order.filter { checked[it.key] == true }) }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } },
    )
}
