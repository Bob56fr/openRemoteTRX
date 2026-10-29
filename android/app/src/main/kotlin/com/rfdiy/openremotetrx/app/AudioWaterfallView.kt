// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Paint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.AudioWaterfall
import com.rfdiy.openremotetrx.logic.Palette
import com.rfdiy.openremotetrx.logic.PeakTracker
import com.rfdiy.openremotetrx.logic.WaterfallSettings
import java.util.Locale

private const val WF_W = 512                       // points dessinés sur la largeur (comme la page)
private const val WF_ROWS = 150
private val FILL = Color(0x5962A2EC)              // couleurs du thème par défaut de la page (--spectre-remplissage…)
private val LINE = Color(0xFF7CC0FF)
private val PEAKS = Color(0xFFF0A830)
private val GRID = Color(0x1CFFFFFF)
private val GRID_STRONG = Color(0x3DFFFFFF)

/** Historique du waterfall audio : image de WF_W × WF_ROWS qui descend d'une ligne à chaque ligne poussée. */
private class AudioFall {
    val bitmap: Bitmap = Bitmap.createBitmap(WF_W, WF_ROWS, Bitmap.Config.ARGB_8888)
    private val pixels = IntArray(WF_W * WF_ROWS) { Palette.LUT[0] }

    fun clear() {
        pixels.fill(Palette.LUT[0])
        bitmap.setPixels(pixels, 0, WF_W, 0, 0, WF_W, WF_ROWS)
    }

    fun push(values: FloatArray, gain: Int) {
        System.arraycopy(pixels, 0, pixels, WF_W, WF_W * (WF_ROWS - 1))
        for (x in 0 until WF_W) pixels[x] = Palette.color(AudioWaterfall.levelToT(values[x], gain))
        bitmap.setPixels(pixels, 0, WF_W, 0, 0, WF_W, WF_ROWS)
    }
}

/**
 * Waterfall du son reçu (comme la page : 0 à 5 kHz par défaut, FFT 4096, couleurs de -85 à -30 dBFS). Calcul
 * seulement pendant l'affichage ; aucun effet sur l'écoute. Réglages VIT / LARG / GAIN / PIC gardés sur le téléphone.
 */
@Composable
fun AudioWaterfallView(onClose: () -> Unit) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("ui", Context.MODE_PRIVATE) }
    var settings by remember {
        mutableStateOf(AudioWaterfall.normalize(prefs.getInt("wf_speed", 12), prefs.getInt("wf_width", 5000),
            prefs.getInt("wf_gain", 0), prefs.getInt("wf_peak", 2)))
    }
    fun save(s: WaterfallSettings) {
        settings = s
        prefs.edit().putInt("wf_speed", s.speed).putInt("wf_width", s.width).putInt("wf_gain", s.gain)
            .putInt("wf_peak", AudioWaterfall.PEAK_TIMES.indexOf(s.peak)).apply()
    }
    val tap = remember { RigHub.startAudioTap() }
    DisposableEffect(Unit) { onDispose { RigHub.stopAudioTap() } }
    val fall = remember { AudioFall() }
    val tracker = remember { PeakTracker() }
    var values by remember { mutableStateOf(FloatArray(WF_W) { -200f }) }
    var peaks by remember { mutableStateOf<FloatArray?>(null) }
    var drawn by remember { mutableIntStateOf(0) }
    val labelPaint = remember { Paint().apply { color = android.graphics.Color.LTGRAY; isAntiAlias = true } }

    LaunchedEffect(settings.width) {                     // nouvelle largeur : historique effacé (autre échelle)
        fall.clear()
        tracker.reset()
        var lastFrame = 0L
        var lastLine = 0L
        var lastAnalysis = 0L
        while (true) {
            withFrameNanos { now ->
                if (now - lastAnalysis < 33_000_000L) return@withFrameNanos          // environ 30 analyses par seconde
                lastAnalysis = now
                val s = settings
                val db = tap.analyser.analyse()
                val v = AudioWaterfall.resample(db, tap.sampleRate, tap.analyser.fftSize, s.width, WF_W)
                val interval = 1_000_000_000L / s.speed
                if (lastFrame == 0L) { lastFrame = now; lastLine = now - interval }
                val dt = (now - lastFrame) / 1e9
                lastFrame = now
                peaks = tracker.update(v, dt, s.peak)?.copyOf()
                var n = 0
                while (n < 3 && now - lastLine >= interval) { fall.push(v, s.gain); lastLine += interval; n++ }
                if (now - lastLine > 1_000_000_000L) lastLine = now                 // retard important : sans rafale
                values = v
                drawn++
            }
        }
    }

    val top = AudioWaterfall.strongest(peaks ?: values, settings.width)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Waterfall audio", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            Text(top?.let { "pic " + String.format(Locale.ROOT, "%.2f", it.hz / 1000.0) } ?: "", style = MaterialTheme.typography.labelMedium)
        }
        Canvas(Modifier.fillMaxWidth().height(210.dp)) {
            drawn.let { }                                          // redessin à chaque analyse
            val specH = size.height * 0.38f
            val axisH = 14.dp.toPx()
            drawRect(Color(Palette.LUT[0]))
            drawImage(
                fall.bitmap.asImageBitmap(), srcOffset = IntOffset.Zero, srcSize = IntSize(WF_W, WF_ROWS),
                dstOffset = IntOffset(0, specH.toInt()), dstSize = IntSize(size.width.toInt(), (size.height - specH - axisH).toInt()),
                filterQuality = FilterQuality.Low,
            )
            labelPaint.textSize = 11.dp.toPx()
            for (tick in AudioWaterfall.axisTicks(settings.width)) {
                val x = tick.fraction * (size.width - 1)
                drawLine(if (tick.hz % 1000 == 0) GRID_STRONG else GRID, Offset(x, 0f), Offset(x, size.height - axisH), strokeWidth = 1f)
                val w = labelPaint.measureText(tick.label)
                val lx = (x - w / 2).coerceIn(0f, size.width - w)
                drawContext.canvas.nativeCanvas.drawText(tick.label, lx, size.height - 2f, labelPaint)
            }
            fun y(db: Float) = specH - 1 - AudioWaterfall.levelToT(db, settings.gain) * (specH - 2)
            val v = values
            val fill = Path().apply {
                moveTo(0f, specH)
                for (i in v.indices) lineTo(i * size.width / (v.size - 1), y(v[i]))
                lineTo(size.width, specH); close()
            }
            drawPath(fill, FILL)
            val line = Path().apply { for (i in v.indices) { val x = i * size.width / (v.size - 1); if (i == 0) moveTo(x, y(v[i])) else lineTo(x, y(v[i])) } }
            drawPath(line, LINE, style = Stroke(width = 1.5f))
            peaks?.let { p ->
                val pl = Path().apply { for (i in p.indices) { val x = i * size.width / (p.size - 1); if (i == 0) moveTo(x, y(p[i])) else lineTo(x, y(p[i])) } }
                drawPath(pl, PEAKS, style = Stroke(width = 1f))
            }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            AssistChip(onClick = { save(AudioWaterfall.nextSpeed(settings)) }, label = { Text(AudioWaterfall.speedLabel(settings.speed)) })
            AssistChip(onClick = { save(AudioWaterfall.nextWidth(settings)) }, label = { Text(AudioWaterfall.widthLabel(settings.width)) })
            AssistChip(onClick = { save(AudioWaterfall.nextGain(settings)) }, label = { Text(AudioWaterfall.gainLabel(settings.gain)) })
            AssistChip(onClick = { save(AudioWaterfall.nextPeak(settings)) }, label = { Text(AudioWaterfall.peakLabel(settings.peak)) })
            AssistChip(onClick = onClose, label = { Text("Fermer") })
        }
    }
}
