// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import androidx.compose.ui.unit.sp
import com.rfdiy.openremotetrx.logic.BigPtt
import kotlin.math.cos
import kotlin.math.sin

private val CYAN = Color(0xFF38D6FF)                  // anneau « prêt » : dans la famille de Page.MESURE / Page.ACCENT

private fun tint(look: BigPtt.Look): Color = when (look) {
    BigPtt.Look.READY -> CYAN
    BigPtt.Look.MINE_TX, BigPtt.Look.CUTTING -> Page.TX
    BigPtt.Look.OTHER, BigPtt.Look.DISARMED -> Page.ALERTE
    BigPtt.Look.OFF -> Page.TEXTE_2
}

/**
 * Gros PTT rond (BigPtt) : 90 % de la largeur (moins si l'écran est bas), posé sur un voile sombre qui empêche de
 * toucher ce qui est dessous. Un appui = le même toggle que le PTT habituel. Masqué par STOP (barre du bas).
 */
@Composable
fun BigPttOverlay(look: BigPtt.Look, totSeconds: Int?, enabled: Boolean, onToggle: () -> Unit) {
    BoxWithConstraints(
        Modifier.fillMaxSize().background(Page.FOND.copy(alpha = 0.88f)).clickable(
            interactionSource = remember { MutableInteractionSource() }, indication = null) {},   // le voile avale les appuis
        contentAlignment = Alignment.Center,
    ) {
        val side = min(maxWidth * 0.9f, maxHeight * 0.92f)
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            BigPttButton(look, totSeconds, enabled, onToggle, Modifier.size(side))
            Text("STOP masque ce bouton", color = Page.TEXTE_2, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
fun BigPttButton(look: BigPtt.Look, totSeconds: Int?, enabled: Boolean, onToggle: () -> Unit, modifier: Modifier) {
    val color = tint(look)
    val transmitting = look == BigPtt.Look.MINE_TX || look == BigPtt.Look.CUTTING
    val haptic = LocalHapticFeedback.current
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val press by animateFloatAsState(if (pressed && enabled) 0.96f else 1f, tween(90), label = "appui")
    val motion = rememberInfiniteTransition(label = "ptt")
    val spin by motion.animateFloat(0f, 360f, infiniteRepeatable(tween(if (transmitting) 2400 else 9000, easing = LinearEasing)), label = "arcs")
    val pulse by motion.animateFloat(0.35f, 0.85f, infiniteRepeatable(tween(if (transmitting) 520 else 1800), RepeatMode.Reverse), label = "lueur")
    val caption = BigPtt.caption(look)
    val density = LocalDensity.current

    BoxWithConstraints(
        modifier.scale(press).clip(CircleShape)
            .semantics { contentDescription = "PTT : $caption" }
            .clickable(interactionSource = source, indication = null, enabled = enabled, role = Role.Button) {
                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                onToggle()
            },
        contentAlignment = Alignment.Center,
    ) {
        val radiusDp = maxWidth / 2
        Canvas(Modifier.fillMaxSize()) {
            val r = size.minDimension / 2
            val c = Offset(size.width / 2, size.height / 2)
            val glow = if (enabled) pulse else 0.2f
            // halo
            drawCircle(Brush.radialGradient(listOf(color.copy(alpha = 0.45f * glow), Color.Transparent), c, r), r, c)
            // anneau extérieur à reflets
            drawCircle(
                Brush.sweepGradient(listOf(color, color.copy(alpha = 0.25f), Page.ACCENT, color.copy(alpha = 0.25f), color), c),
                r * 0.93f, c, style = Stroke(width = r * 0.035f),
            )
            // graduations : 72 traits, un sur six plus long
            for (i in 0 until 72) {
                val a = Math.toRadians(i * 5.0)
                val long = i % 6 == 0
                val r1 = r * (if (long) 0.79f else 0.82f)
                val r2 = r * 0.86f
                drawLine(
                    color.copy(alpha = if (long) 0.85f else 0.35f),
                    Offset(c.x + r1 * cos(a).toFloat(), c.y + r1 * sin(a).toFloat()),
                    Offset(c.x + r2 * cos(a).toFloat(), c.y + r2 * sin(a).toFloat()),
                    strokeWidth = if (long) r * 0.012f else r * 0.006f, cap = StrokeCap.Round,
                )
            }
            // trois arcs qui tournent (vite pendant l'émission)
            rotate(spin, c) {
                val arc = Size(r * 1.78f, r * 1.78f)
                val topLeft = Offset(c.x - r * 0.89f, c.y - r * 0.89f)
                for (k in 0 until 3) {
                    drawArc(color.copy(alpha = 0.9f), k * 120f, 38f, false, topLeft, arc, style = Stroke(r * 0.02f, cap = StrokeCap.Round))
                }
            }
            // disque central
            drawCircle(Brush.radialGradient(listOf(color.copy(alpha = if (transmitting) 0.55f else 0.22f), Page.INSTRUMENT, Page.FOND),
                c, r * 0.74f), r * 0.74f, c)
            drawCircle(color.copy(alpha = 0.9f), r * 0.74f, c, style = Stroke(width = r * 0.018f))
            drawCircle(color.copy(alpha = 0.25f * glow + 0.1f), r * 0.66f, c, style = Stroke(width = r * 0.008f))
        }
        val big = with(density) { (radiusDp * 0.42f).toSp() }
        val small = with(density) { (radiusDp * 0.085f).toSp() }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text("PTT", color = if (enabled) Page.TEXTE else Page.TEXTE_2, fontSize = big, fontWeight = FontWeight.Black,
                letterSpacing = with(density) { (radiusDp * 0.03f).toSp() })
            Text(caption, color = color, fontSize = small, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
            if (transmitting && totSeconds != null) {
                Text("${totSeconds} s", color = Page.TEXTE, fontSize = small, fontWeight = FontWeight.Medium,
                    modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}
