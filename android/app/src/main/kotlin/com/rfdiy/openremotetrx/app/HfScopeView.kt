// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Paint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.logic.HfScope
import com.rfdiy.openremotetrx.logic.Palette
import com.rfdiy.openremotetrx.logic.SpotLabel
import com.rfdiy.openremotetrx.logic.Spots
import java.util.Locale
import com.rfdiy.openremotetrx.protocol.SpectrumFrame

private const val ROWS = 150                      // lignes d'historique du waterfall
private val HEALTH_COLORS = mapOf("green" to Color(0xFF43A047), "orange" to Color(0xFFFB8C00), "red" to Color(0xFFE53935), "off" to Color.Gray)

/**
 * Historique du waterfall : une image d'un pixel par point du poste (la mise à l'échelle lisse l'affichage), qui
 * descend d'une ligne à chaque balayage. Réinitialisée quand l'échelle change (sameScale, comme la page).
 */
private class WaterfallBuffer {
    var bitmap: Bitmap? = null
    private var pixels = IntArray(0)
    private var width = 0
    private var previous: SpectrumFrame? = null
    private var floor: Double? = null
    var line = FloatArray(0)                       // dernier balayage, 0..1 dans la fenêtre de couleurs

    fun push(frame: SpectrumFrame, levelMax: Int, rangeDb: Int, gainDb: Int) {
        if (!HfScope.sameScale(previous, frame) || bitmap == null) {
            width = frame.size
            pixels = IntArray(width * ROWS) { Palette.LUT[0] }
            bitmap = Bitmap.createBitmap(width, ROWS, Bitmap.Config.ARGB_8888)
            floor = null
            line = FloatArray(width)
        }
        previous = frame
        val win = HfScope.colorWindow(frame, levelMax, rangeDb, floor)
        floor = win.floor
        System.arraycopy(pixels, 0, pixels, width, width * (ROWS - 1))
        for (x in 0 until width) {
            val t = HfScope.windowT(frame.level(x).toDouble(), win, gainDb)
            line[x] = t
            pixels[x] = Palette.color(t)
        }
        bitmap!!.setPixels(pixels, 0, width, 0, 0, width, ROWS)
    }
}

private val SPOT_COLORS = mapOf("cluster" to Color(0xFF4FC3F7), "rbn" to Color(0xFFB39DDB), "cb" to Color(0xFFFFB74D))

/**
 * Spectre HF du poste (second port CI-V) : courbe, waterfall, repère de la fréquence, graduations, étiquettes des spots
 * du Cluster DX (appui = fiche avec QSY ; « +N » = liste). Toucher le spectre = accorder ; glisser = tourner le VFO
 * (vers la gauche : fréquence plus haute). Réglages du poste par spectrum_set (réception seulement) ; gain et plage
 * gardés sur le téléphone. Abonnement aux balayages tant que la vue est ouverte. `plotModifier` : taille du dessin
 * (230 dp en portrait, tout l'écran en paysage).
 */
@Composable
fun HfScopeView(
    ui: RigUi,
    canSet: Boolean,
    onTune: (Long) -> Unit,
    onClose: (() -> Unit)?,
    modifier: Modifier = Modifier,
    plotModifier: Modifier = Modifier.fillMaxWidth().height(230.dp),
) {
    DisposableEffect(Unit) {
        RigHub.watchSpectrum(true)
        onDispose { RigHub.watchSpectrum(false) }
    }
    val frame by RigHub.spectrum.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("ui", Context.MODE_PRIVATE) }
    var gain by remember { mutableIntStateOf(prefs.getInt("scope_gain", 0).takeIf { it in HfScope.GAINS } ?: 0) }
    var range by remember { mutableIntStateOf(prefs.getInt("scope_range", HfScope.DEFAULT_RANGE_DB).takeIf { it in HfScope.RANGES_DB } ?: HfScope.DEFAULT_RANGE_DB) }
    val buffer = remember { WaterfallBuffer() }
    var drawn by remember { mutableIntStateOf(0) }
    val levelMax = ui.rig.hello?.spectrum?.levelMax?.takeIf { it > 0 } ?: 160
    LaunchedEffect(frame) {
        frame?.let { buffer.push(it, levelMax, range, gain); drawn++ }
    }
    val settings = HfScope.settings(ui.rig.state)
    val rigHz = ui.rig.state?.rig?.frequencyHz
    val lineColor = MaterialTheme.colorScheme.primary
    val labelPaint = remember { Paint().apply { color = android.graphics.Color.LTGRAY; isAntiAlias = true } }
    var dragX by remember { mutableStateOf(0f) }
    val labels = remember { mutableListOf<Pair<Rect, SpotLabel>>() }        // étiquettes dessinées, pour l'appui
    var cardId by remember { mutableStateOf<Long?>(null) }
    var listIds by remember { mutableStateOf<List<Long>?>(null) }
    var spotsOn by remember { mutableStateOf(prefs.getBoolean("spots_on", true)) }
    var vfo by remember { mutableStateOf(false) }                  // accord au doigt (glisser), éteint par défaut comme la page
    var listAll by remember { mutableStateOf(false) }
    var sortByAge by remember { mutableStateOf(false) }
    val spots = if (spotsOn) ui.rig.spots else emptyList()
    val now = System.currentTimeMillis()
    val health = ui.rig.clusterHealth

    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Spectre HF", style = MaterialTheme.typography.titleSmall)
            frame?.let { Text(HfScope.spanLabel(it.lowHz, it.highHz) + if (it.outOfRange) " — hors plage" else "", style = MaterialTheme.typography.labelMedium) }
            Spacer(Modifier.weight(1f))
            // Cluster DX (seulement si le module parle) : voyant de santé, spots affichés ou non, liste de la bande
            if (health != null) {
                Box(Modifier.size(12.dp).background(HEALTH_COLORS[health] ?: Color.Gray, CircleShape))
                CompactChip("SPOTS", onClick = { spotsOn = !spotsOn; prefs.edit().putBoolean("spots_on", spotsOn).apply() }, selected = spotsOn)
                CompactChip("LISTE", onClick = { listAll = true })
            }
            CompactChip("VFO", onClick = { vfo = !vfo }, selected = vfo)
        }
        Box(plotModifier) {
            val f = frame
            Canvas(
                Modifier.fillMaxWidth().fillMaxHeight()
                    // Zoom à deux doigts : span du poste (en mode centré ; passe en CENT si besoin). Geste à deux
                    // doigts consommé : il n'accorde pas le poste.
                    .pointerInput(canSet, settings.spanHz, settings.mode) {
                        awaitEachGesture {
                            awaitFirstDown(requireUnconsumed = false)
                            var start = 0f
                            var factor = 1f
                            do {
                                val event = awaitPointerEvent()
                                val down = event.changes.filter { it.pressed }
                                if (down.size >= 2) {
                                    val d = (down[0].position - down[1].position).getDistance()
                                    if (start == 0f) start = d else if (start > 0f) factor = d / start
                                    event.changes.forEach { it.consume() }
                                }
                            } while (event.changes.any { it.pressed })
                            val span = if (start > 0f && canSet) HfScope.zoomSpan(settings.spanHz, factor) else null
                            if (span != null) {
                                if (settings.mode != "center") RigHub.spectrumSet("mode", "center")
                                RigHub.spectrumSet("span", span)
                            }
                        }
                    }
                    .pointerInput(f?.lowHz, f?.highHz, canSet) {
                        detectTapGestures { pos ->
                            labels.firstOrNull { it.first.contains(pos) }?.let { (_, label) ->   // une étiquette : fiche ou liste
                                if (label.ids.size > 1) listIds = label.ids else cardId = label.ids.first()
                                return@detectTapGestures
                            }
                            val fr = frame ?: return@detectTapGestures
                            if (canSet) onTune(HfScope.frequencyAt(pos.x / size.width, fr.lowHz, fr.highHz))
                        }
                    }
                    .pointerInput(f?.lowHz, f?.highHz, canSet, rigHz, vfo) {
                        if (!vfo) return@pointerInput                  // glisser n'accorde que si VFO est allumé (comme la page)
                        detectHorizontalDragGestures(
                            onDragStart = { dragX = 0f },
                            onDragEnd = {
                                val fr = frame
                                if (fr != null && rigHz != null && canSet) {
                                    val span = fr.highHz - fr.lowHz
                                    val step = HfScope.tuneStep(span)
                                    val steps = HfScope.dragSteps(dragX, size.width.toFloat(), span, step)
                                    if (steps != 0) onTune(rigHz + steps * step)
                                }
                                dragX = 0f
                            },
                        ) { _, dx -> dragX += dx }
                    },
            ) {
                drawn.let { }                                   // redessin à chaque balayage
                val top = size.height * 0.35f
                drawRect(Color(Palette.LUT[0]))
                val bmp = buffer.bitmap
                if (f != null && bmp != null) {
                    drawImage(
                        bmp.asImageBitmap(), srcOffset = IntOffset.Zero, srcSize = IntSize(bmp.width, bmp.height),
                        dstOffset = IntOffset(0, top.toInt()), dstSize = IntSize(size.width.toInt(), (size.height - top).toInt()),
                        filterQuality = FilterQuality.Low,
                    )
                    val line = buffer.line
                    if (line.size > 1) {
                        val path = Path()
                        for (i in line.indices) {
                            val x = i * size.width / (line.size - 1)
                            val y = top - line[i] * (top - 4f)
                            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                        }
                        drawPath(path, lineColor, style = Stroke(width = 2f))
                    }
                    labelPaint.textSize = 11.dp.toPx()
                    for (tick in HfScope.ticks(f.lowHz, f.highHz, 6)) {
                        val x = tick.fraction * size.width
                        drawLine(Color(0x55FFFFFF), Offset(x, 0f), Offset(x, top), strokeWidth = 1f)
                        if (x + 3f + labelPaint.measureText(tick.label) <= size.width) {      // pas de libellé coupé au bord
                            drawContext.canvas.nativeCanvas.drawText(tick.label, x + 3f, 12.dp.toPx(), labelPaint)
                        }
                    }
                    HfScope.markerFraction(rigHz, f.lowHz, f.highHz)?.let { m ->
                        val x = m * size.width
                        drawLine(Color(0xFFE53935), Offset(x, 0f), Offset(x, size.height), strokeWidth = 2f)
                    }
                    // Spots du Cluster DX : trait vertical estompé avec l'âge, étiquettes sur 3 rangées puis « +N »
                    labels.clear()
                    val visible = spots.filter { it.hz in f.lowHz..f.highHz }
                    val span = (f.highHz - f.lowHz).toFloat()
                    for (s in visible) {
                        val x = (s.hz - f.lowHz) / span * size.width
                        val alpha = Spots.opacity(Spots.ageSeconds(s, now)) * 0.7f
                        drawLine((SPOT_COLORS[s.kind] ?: SPOT_COLORS.getValue("cluster")).copy(alpha = alpha), Offset(x, 0f), Offset(x, size.height), strokeWidth = 1.5f)
                    }
                    labelPaint.textSize = 12.dp.toPx()
                    val charPx = labelPaint.measureText("M") * 0.8f
                    val rowPx = 18.dp.toPx()
                    val tagTop = 16.dp.toPx()
                    for (label in Spots.layoutLabels(visible, f.lowHz, f.highHz, size.width, charPx = charPx, padPx = 12.dp.toPx())) {
                        val first = visible.firstOrNull { it.id == label.ids.first() }
                        val w = labelPaint.measureText(label.text) + 10.dp.toPx()
                        val left = (label.x - w / 2).coerceIn(0f, size.width - w)
                        val top = tagTop + label.row * rowPx
                        val rect = Rect(left, top, left + w, top + rowPx - 3f)
                        val base = SPOT_COLORS[first?.kind] ?: SPOT_COLORS.getValue("cluster")
                        val alpha = if (label.group || first == null) 1f else Spots.opacity(Spots.ageSeconds(first, now))
                        drawRoundRect(base.copy(alpha = 0.85f * alpha), rect.topLeft, rect.size, CornerRadius(6f, 6f))
                        labelPaint.color = android.graphics.Color.BLACK
                        drawContext.canvas.nativeCanvas.drawText(label.text, left + 5.dp.toPx(), top + rowPx - 8f, labelPaint)
                        labelPaint.color = android.graphics.Color.LTGRAY
                        labels += rect to label
                    }
                }
            }
            if (f == null) {
                Text(HfScope.waitText(ui.rig.state), color = Color.White, style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.align(Alignment.Center).padding(16.dp))
            }
        }
        // Réglages : ceux du poste (station, réception seulement) puis ceux de l'affichage (téléphone)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            CompactChip(HfScope.spanSettingLabel(settings.spanHz), onClick = { RigHub.spectrumSet("span", HfScope.nextSpan(settings.spanHz)) }, enabled = canSet)
            CompactChip(HfScope.modeSettingLabel(settings.mode), onClick = { RigHub.spectrumSet("mode", HfScope.nextMode(settings.mode)) }, enabled = canSet)
            CompactChip(HfScope.speedSettingLabel(settings.speed), onClick = { RigHub.spectrumSet("speed", HfScope.nextSpeed(settings.speed)) }, enabled = canSet)
            CompactChip("REF −", onClick = { HfScope.stepRef(settings.refDb, -1.0)?.let { RigHub.spectrumSet("ref", it) } }, enabled = canSet && settings.refDb != null)
            Text(HfScope.refLabel(settings.refDb), style = MaterialTheme.typography.labelLarge, modifier = Modifier.align(Alignment.CenterVertically))
            CompactChip("REF +", onClick = { HfScope.stepRef(settings.refDb, 1.0)?.let { RigHub.spectrumSet("ref", it) } }, enabled = canSet && settings.refDb != null)
            CompactChip(HfScope.gainLabel(gain), onClick = { gain = HfScope.nextGain(gain); prefs.edit().putInt("scope_gain", gain).apply() })
            CompactChip(HfScope.rangeLabel(range), onClick = { range = HfScope.nextRange(range); prefs.edit().putInt("scope_range", range).apply() })
            if (onClose != null) CompactChip("Fermer", onClick = onClose)
        }
    }

    // Fiche d'un spot (QSY : mode adapté au poste puis fréquence ; refusé pendant l'émission) et liste d'un « +N »
    cardId?.let { id ->
        val s = spots.firstOrNull { it.id == id }
        AlertDialog(
            onDismissRequest = { cardId = null },
            title = { Text(s?.dx ?: "Spot") },
            text = {
                if (s == null) Text("Spot expiré ou hors de la bande.")
                else Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(Spots.kindLabel(s.kind) + if (s.count > 1) " · ${s.count} spotteurs" else "")
                    Text(String.format(Locale.ROOT, "%.1f kHz", s.khz) + " · " + Spots.modeLabel(s), style = MaterialTheme.typography.titleMedium)
                    Text(listOfNotNull(
                        s.country.takeIf { it.isNotEmpty() }?.let { it + if (s.continent.isNotEmpty()) " (${s.continent})" else "" },
                        "de " + s.de.ifEmpty { "?" },
                        s.time.takeIf { it.length == 4 }?.let { it.take(2) + ":" + it.drop(2) + " UTC" },
                        Spots.ageLabel(Spots.ageSeconds(s, System.currentTimeMillis())),
                    ).joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                    if (s.comment.isNotEmpty()) Text(s.comment, style = MaterialTheme.typography.bodySmall)
                    if (!canSet) Text("QSY impossible : émission en cours ou station déconnectée.", color = MaterialTheme.colorScheme.error)
                }
            },
            confirmButton = {
                TextButton(onClick = { RigHub.qsySpot(id); cardId = null }, enabled = s != null && canSet) { Text("QSY") }
            },
            dismissButton = { TextButton(onClick = { cardId = null }) { Text("Fermer") } },
        )
    }
    if (listAll) {
        // Liste des spots de la bande affichée, triée par fréquence ou par âge (comme la page)
        val f = frame
        val band = if (f != null) ui.rig.spots.filter { it.hz in f.lowHz..f.highHz } else ui.rig.spots
        AlertDialog(
            onDismissRequest = { listAll = false },
            title = { Text("Spots de la bande (${band.size})") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (health != null) Text(Spots.healthLabel(health), style = MaterialTheme.typography.bodySmall)
                    TextButton(onClick = { sortByAge = !sortByAge }) { Text("Tri : " + if (sortByAge) "âge" else "fréquence") }
                    if (band.isEmpty()) Text("Aucun spot pour l'instant.")
                    for (s in Spots.sortList(band, sortByAge, System.currentTimeMillis())) {
                        Text(
                            String.format(Locale.ROOT, "%.1f", s.khz) + "  " + s.dx + "  " + s.mode.ifEmpty { "?" } + "  " +
                                Spots.ageLabel(Spots.ageSeconds(s, System.currentTimeMillis())) +
                                if (s.kind != "cluster") "  [" + Spots.kindLabel(s.kind) + "]" else "",
                            modifier = Modifier.fillMaxWidth().clickable { listAll = false; cardId = s.id }.padding(vertical = 8.dp),
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { listAll = false }) { Text("Fermer") } },
        )
    }
    listIds?.let { ids ->
        AlertDialog(
            onDismissRequest = { listIds = null },
            title = { Text("${ids.size} spots proches") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    for (s in spots.filter { it.id in ids }) {
                        Text(
                            s.dx + "   " + String.format(Locale.ROOT, "%.1f", s.khz) + "   " + Spots.modeLabel(s),
                            modifier = Modifier.fillMaxWidth().clickable { listIds = null; cardId = s.id }.padding(vertical = 8.dp),
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { listIds = null }) { Text("Fermer") } },
        )
    }
}
