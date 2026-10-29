// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Paint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AssistChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.geometry.Offset
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
import com.rfdiy.openremotetrx.protocol.SpectrumFrame

private const val ROWS = 150                      // lignes d'historique du waterfall

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

/**
 * Spectre HF du poste (second port CI-V) : courbe, waterfall, repère de la fréquence, graduations. Toucher = accorder ;
 * glisser = tourner le VFO (vers la gauche : fréquence plus haute). Réglages du poste par spectrum_set (réception
 * seulement) ; gain et plage de couleurs gardés sur le téléphone. Abonnement aux balayages tant que la vue est ouverte.
 */
@Composable
fun HfScopeView(ui: RigUi, canSet: Boolean, onTune: (Long) -> Unit, onClose: () -> Unit) {
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

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Spectre HF", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            frame?.let { Text(HfScope.spanLabel(it.lowHz, it.highHz) + if (it.outOfRange) " — hors plage" else "", style = MaterialTheme.typography.labelMedium) }
        }
        Box(Modifier.fillMaxWidth().height(230.dp)) {
            val f = frame
            Canvas(
                Modifier.fillMaxWidth().height(230.dp)
                    .pointerInput(f?.lowHz, f?.highHz, canSet) {
                        detectTapGestures { pos ->
                            val fr = frame ?: return@detectTapGestures
                            if (canSet) onTune(HfScope.frequencyAt(pos.x / size.width, fr.lowHz, fr.highHz))
                        }
                    }
                    .pointerInput(f?.lowHz, f?.highHz, canSet, rigHz) {
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
                }
            }
            if (f == null) {
                Text(HfScope.waitText(ui.rig.state), color = Color.White, style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.align(Alignment.Center).padding(16.dp))
            }
        }
        // Réglages : ceux du poste (station, réception seulement) puis ceux de l'affichage (téléphone)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            AssistChip(onClick = { RigHub.spectrumSet("span", HfScope.nextSpan(settings.spanHz)) },
                enabled = canSet, label = { Text(HfScope.spanSettingLabel(settings.spanHz)) })
            AssistChip(onClick = { RigHub.spectrumSet("mode", HfScope.nextMode(settings.mode)) },
                enabled = canSet, label = { Text(HfScope.modeSettingLabel(settings.mode)) })
            AssistChip(onClick = { RigHub.spectrumSet("speed", HfScope.nextSpeed(settings.speed)) },
                enabled = canSet, label = { Text(HfScope.speedSettingLabel(settings.speed)) })
            AssistChip(onClick = { HfScope.stepRef(settings.refDb, -1.0)?.let { RigHub.spectrumSet("ref", it) } },
                enabled = canSet && settings.refDb != null, label = { Text("REF −") })
            Text(HfScope.refLabel(settings.refDb), style = MaterialTheme.typography.labelLarge, modifier = Modifier.align(Alignment.CenterVertically))
            AssistChip(onClick = { HfScope.stepRef(settings.refDb, 1.0)?.let { RigHub.spectrumSet("ref", it) } },
                enabled = canSet && settings.refDb != null, label = { Text("REF +") })
            AssistChip(onClick = { gain = HfScope.nextGain(gain); prefs.edit().putInt("scope_gain", gain).apply() },
                label = { Text(HfScope.gainLabel(gain)) })
            AssistChip(onClick = { range = HfScope.nextRange(range); prefs.edit().putInt("scope_range", range).apply() },
                label = { Text(HfScope.rangeLabel(range)) })
            AssistChip(onClick = onClose, label = { Text("Fermer") })
        }
    }
}
