// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Paint
import android.graphics.RectF
import android.provider.MediaStore
import android.widget.Toast
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.FileProvider
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.RigState
import com.rfdiy.openremotetrx.logic.Swr
import com.rfdiy.openremotetrx.logic.SwrPoint
import com.rfdiy.openremotetrx.logic.SwrResult
import com.rfdiy.openremotetrx.logic.SwrUi
import kotlinx.coroutines.delay
import java.io.File
import java.text.DateFormat
import java.util.Date
import kotlin.math.ceil
import kotlin.math.roundToInt

// Couleurs du graphique : mêmes valeurs que la page (swr.js COLORS), lisibles sur l'écran comme sur l'image partagée
private val GOOD = android.graphics.Color.rgb(0x35, 0xc4, 0x7a)
private val FAIR = android.graphics.Color.rgb(0xf0, 0xa8, 0x30)
private val BAD = android.graphics.Color.rgb(0xe5, 0x48, 0x4d)
private val NONE = android.graphics.Color.rgb(0x5a, 0x64, 0x72)
private val GRID = android.graphics.Color.argb(41, 255, 255, 255)
private val GRID_STRONG = android.graphics.Color.argb(82, 255, 255, 255)
private val TEXT = android.graphics.Color.rgb(0xc9, 0xd4, 0xe2)
private val BACKGROUND = android.graphics.Color.rgb(0x0b, 0x12, 0x20)
private val ACCENT = android.graphics.Color.rgb(0x4f, 0xc3, 0xf7)

private fun colorOf(p: SwrPoint): Int {
    val swr = p.swr ?: return NONE
    return when (Swr.level(swr)) { "good" -> GOOD; "fair" -> FAIR; else -> BAD }
}

/** Barres verticales (page : drawSwrChart) : écran et image partagée. `u` = taille d'un « point » en pixels. */
private fun drawChart(canvas: android.graphics.Canvas, x0: Float, y0: Float, w: Float, h: Float, points: List<SwrPoint>, u: Float) {
    val axis = 34 * u
    val bottom = 18 * u
    val top = 12 * u
    val plotX = x0 + axis
    val plotW = w - axis
    val plotH = h - bottom - top
    val baseY = y0 + top + plotH
    fun yOf(swr: Double) = (baseY - Swr.scaleY(swr) * plotH).toFloat()
    val paint = Paint().apply { isAntiAlias = true; textSize = 10 * u }
    for (g in Swr.GRID + listOf(3.0, 5.0)) {
        paint.color = if (g == 2.0 || g == 5.0) GRID_STRONG else GRID
        paint.strokeWidth = maxOf(1f, u / 2)
        canvas.drawLine(plotX, yOf(g), x0 + w, yOf(g), paint)
        paint.color = TEXT
        canvas.drawText(SwrUi.swrText(g).removeSuffix(",00"), x0 + 2 * u, yOf(g) + 3 * u, paint)
    }
    val n = maxOf(1, points.size)
    val slot = plotW / n
    val bar = maxOf(2 * u, slot * 0.7f)
    val best = points.filter { it.swr != null }.minByOrNull { it.swr!! }
    val every = maxOf(1, ceil(n * 52 * u / plotW).toInt())
    points.forEachIndexed { i, p ->
        val x = plotX + i * slot + (slot - bar) / 2
        val swr = p.swr
        val yTop = if (swr != null) minOf(baseY - 2 * u, yOf(swr)) else baseY - 4 * u
        paint.style = Paint.Style.FILL
        paint.color = colorOf(p)
        paint.alpha = if (p.status == "reduced") 128 else 255
        canvas.drawRect(x, yTop, x + bar, baseY, paint)
        paint.alpha = 255
        if (p == best) {
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 2 * u; paint.color = ACCENT
            canvas.drawRect(RectF(x, yTop, x + bar, baseY), paint)
            paint.style = Paint.Style.FILL
        }
        paint.color = TEXT
        if (swr != null && n <= 24) canvas.drawText(SwrUi.swrText(swr), x, yTop - 3 * u, paint)
        if (i % every == 0) canvas.drawText(SwrUi.freqLabel(p.hz), x, baseY + 13 * u, paint)
    }
}

/** Image ANONYME (ni indicatif ni station) : graphique, nom, date, puissance, mode, meilleur point, logo, www.rf-diy.com. */
private fun swrImage(context: Context, result: SwrResult, name: String): Bitmap {
    val bmp = Bitmap.createBitmap(1200, 760, Bitmap.Config.ARGB_8888)
    val c = android.graphics.Canvas(bmp)
    c.drawColor(BACKGROUND)
    val legend = SwrUi.legendLines(result, name, DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
        .format(Date((if (result.atS > 0) result.atS * 1000 else System.currentTimeMillis().toDouble()).toLong())))
    val paint = Paint().apply { isAntiAlias = true }
    paint.color = android.graphics.Color.WHITE; paint.textSize = 34f; paint.isFakeBoldText = true
    c.drawText(legend[0], 40f, 56f, paint)
    drawChart(c, 30f, 80f, 1140f, 520f, result.points, 2f)
    paint.isFakeBoldText = false; paint.color = TEXT; paint.textSize = 22f
    legend.getOrNull(1)?.let { c.drawText(it, 40f, 650f, paint) }
    BitmapFactory.decodeResource(context.resources, R.drawable.logo_openremotetrx)?.let { logo ->
        c.drawBitmap(Bitmap.createScaledBitmap(logo, 64, 64, true), 40f, 676f, null)
    }
    paint.color = ACCENT; paint.textSize = 24f; paint.isFakeBoldText = true
    c.drawText("www.rf-diy.com", 118f, 718f, paint)
    return bmp
}

private fun fileName(name: String) = "tos-" + name.ifBlank { "mesure" }.replace(Regex("[^\\w.-]+"), "_").take(40) + ".png"

/** Partage par les applications du téléphone (WhatsApp, Signal, courriel…). */
private fun shareImage(context: Context, bmp: Bitmap, name: String) {
    val dir = File(context.cacheDir, "swr").apply { mkdirs() }
    val file = File(dir, fileName(name))
    file.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
    val send = Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, uri)
        .putExtra(Intent.EXTRA_TITLE, name.ifBlank { "Mesure de TOS" }).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, "Partager la mesure de TOS"))
}

/** « Enregistrer dans Images » : Images/OpenRemoteTRX (Android 10+, sans autorisation). */
private fun saveImage(context: Context, bmp: Bitmap, name: String): Boolean {
    val values = ContentValues().apply {
        put(MediaStore.Images.Media.DISPLAY_NAME, fileName(name))
        put(MediaStore.Images.Media.MIME_TYPE, "image/png")
        put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/OpenRemoteTRX")
    }
    val uri = context.contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return false
    return context.contentResolver.openOutputStream(uri)?.use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) } ?: false
}

/**
 * Mesure de TOS (docs/tos-cahier-des-charges.md) : écran plein écran ouvert depuis les Réglages. Chaque point est une
 * prise d'émission NORMALE de ce téléphone (« Émission autorisée », STOP toujours possible) ; la station décide de tout.
 */
@Composable
fun SwrScreen(rig: RigState, onClose: () -> Unit) {
    val context = LocalContext.current
    val rigHz = rig.state?.rig?.frequencyHz
    val tableBand = rigHz?.let { Swr.bandAt(it) }
    var useBand by remember { mutableStateOf(tableBand != null) }
    var center by remember { mutableStateOf(rigHz?.let { (it / 1000).toString() } ?: "") }
    var width by remember { mutableStateOf("100") }
    var points by remember { mutableStateOf("11") }
    var power by remember { mutableStateOf(15f) }
    var choicesApplied by remember { mutableStateOf(false) }
    var confirmOutside by remember { mutableStateOf(false) }
    var restoredFor by remember { mutableStateOf<SwrResult?>(null) }
    var restoredOpen by remember { mutableStateOf<SwrResult?>(null) }
    var naming by remember { mutableStateOf<Pair<String, Boolean>?>(null) }      // nom de la mesure, true = partager
    var lastName by remember { mutableStateOf("") }
    fun say(text: String) = Toast.makeText(context, text, Toast.LENGTH_SHORT).show()

    LaunchedEffect(Unit) { RigHub.swrLast() }
    LaunchedEffect(rig.swrChoices) {
        val c = rig.swrChoices
        if (c != null && !choicesApplied) { choicesApplied = true; power = c.first.toFloat(); points = c.second.toString() }
    }
    val range: Pair<Long, Long>? = if (useBand) tableBand?.let { it.lowHz to it.highHz } else {
        val cz = center.replace(',', '.').toDoubleOrNull()?.times(1000)?.roundToInt()?.toLong()
        val wd = width.replace(',', '.').toDoubleOrNull()?.times(1000)?.roundToInt()?.toLong()
        if (cz != null && wd != null) Swr.rangeFromCenter(cz, wd) else null
    }
    val wanted = points.toIntOrNull() ?: 0
    val plan = range?.let { Swr.plan(it.first, it.second, wanted) }
    LaunchedEffect(range, wanted, power.roundToInt()) {                      // plan de la station (rien n'est émis)
        delay(300)
        if (range != null && plan?.error == null) RigHub.swrPlan(range.first, range.second, wanted, power.roundToInt().toDouble())
    }
    val progress = rig.swr
    val running = progress?.running == true
    val shown = progress?.result ?: rig.swrLast
    val chartPoints = if (progress != null && (running || progress.result != null)) (progress.result?.points ?: progress.points) else rig.swrLast?.points.orEmpty()
    LaunchedEffect(progress?.result) {                                       // fin de mesure : état du poste remis, tout de suite
        val r = progress?.result
        if (r != null && restoredFor !== r) { restoredFor = r; restoredOpen = r }
    }
    val stationPlan = rig.swrPlan
    val maxPct = (stationPlan?.maxPowerPct?.toFloat() ?: 50f).coerceIn(5f, 50f)
    fun close() {
        val r = shown
        if (r != null && restoredFor !== r) { restoredFor = r; restoredOpen = r }   // en quittant : état remis
        else onClose()
    }

    Dialog(onDismissRequest = { close() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = Page.FOND) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Mesure de TOS", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    TextButton(onClick = { close() }) { Text("Fermer") }
                }
                Text("Une courte porteuse FM par point (émission normale : « Émission autorisée », STOP toujours possible), coupleur arrêté, " +
                    "puis le poste est remis en état.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = useBand, onClick = { useBand = true }, enabled = tableBand != null && !running)
                    Text("Bande du poste" + (tableBand?.let { " (${it.name} : ${SwrUi.freqLabel(it.lowHz)} à ${SwrUi.freqLabel(it.highHz)} MHz)" } ?: " (hors table)"),
                        style = MaterialTheme.typography.bodyMedium)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = !useBand, onClick = { useBand = false }, enabled = !running)
                    Text("Centre et largeur", style = MaterialTheme.typography.bodyMedium)
                }
                if (!useBand) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(center, { center = it }, label = { Text("Centre (kHz)") }, singleLine = true, modifier = Modifier.weight(1f),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), enabled = !running)
                    OutlinedTextField(width, { width = it }, label = { Text("Largeur (kHz)") }, singleLine = true, modifier = Modifier.weight(1f),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), enabled = !running)
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(points, { points = it.filter(Char::isDigit).take(3) }, label = { Text("Points") }, singleLine = true,
                        modifier = Modifier.width(96.dp), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), enabled = !running)
                    Text("Puissance ${power.roundToInt()} %", modifier = Modifier.width(110.dp))
                    Slider(power, { power = it.coerceAtMost(maxPct) }, valueRange = 5f..50f, steps = 44, enabled = !running, modifier = Modifier.weight(1f))
                }
                // Calcul affiché : FreqBasse et FreqHaute, pas lisible, nombre réel de points, puis le plan de la station
                val planText = when {
                    range == null -> "Choisis une plage."
                    plan?.error != null -> com.rfdiy.openremotetrx.logic.Texts.refusal(plan.error!!)
                    else -> (if (!useBand) "$center kHz ± ${(width.replace(',', '.').toDoubleOrNull() ?: 0.0) / 2} kHz = " else "") +
                        "${SwrUi.freqLabel(plan!!.lowHz)} à ${SwrUi.freqLabel(plan.highHz)} MHz, pas de ${plan.stepHz / 1000} kHz, ${plan.freqs.size} points" +
                        (if (plan.amateurOnly) "" else " — HORS des bandes radioamateur") + (stationPlan?.text ?: "")
                }
                Text(planText, style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = { if (plan?.amateurOnly == false) confirmOutside = true else RigHub.swrStart(range!!.first, range.second, wanted, power.roundToInt().toDouble()) },
                        enabled = !running && rig.armed && range != null && plan?.error == null,
                    ) { Text("Lancer la mesure") }
                    if (running) OutlinedButton(onClick = { RigHub.swrCancel() }) { Text("Annuler") }
                }
                if (!rig.armed) Text("« Émission autorisée » doit être allumé (en bas de l'écran principal).", color = Page.ALERTE, style = MaterialTheme.typography.bodySmall)
                progress?.let { p ->
                    val text = when (p.state) {
                        "preparing" -> "Préparation du poste…"
                        "calibrating" -> "Étalonnage du temps de lecture du poste…"
                        "measuring" -> "Point ${p.points.count { it.swr != null }} sur ${p.total}"
                        "restoring" -> "Remise en état du poste…"
                        else -> ""
                    }
                    if (text.isNotEmpty()) Text(text, style = MaterialTheme.typography.bodyMedium)
                }
                Canvas(Modifier.fillMaxWidth().height(230.dp)) {
                    drawIntoCanvas { c ->
                        c.nativeCanvas.drawColor(BACKGROUND)
                        drawChart(c.nativeCanvas, 0f, 0f, size.width, size.height, chartPoints, density)
                    }
                }
                if (shown != null && !running) {
                    Text(SwrUi.summary(shown), style = MaterialTheme.typography.bodyMedium)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { naming = lastName to true }) { Text("Partager") }
                        OutlinedButton(onClick = { naming = lastName to false }) { Text("Enregistrer dans Images") }
                    }
                    TextButton(onClick = { restoredOpen = shown }) { Text("État du poste remis") }
                }
            }
        }
    }

    if (confirmOutside) AlertDialog(
        onDismissRequest = { confirmOutside = false },
        title = { Text("Hors des bandes radioamateur") },
        text = { Text("Cette plage sort des bandes radioamateur : tu vas émettre hors de ces bandes, sous ta seule responsabilité.") },
        confirmButton = { TextButton(onClick = { confirmOutside = false; range?.let { RigHub.swrStart(it.first, it.second, wanted, power.roundToInt().toDouble()) } }) { Text("Continuer") } },
        dismissButton = { TextButton(onClick = { confirmOutside = false }) { Text("Annuler") } },
    )
    restoredOpen?.let { r ->
        val (lines, diffs) = SwrUi.restoredLines(r)
        AlertDialog(
            onDismissRequest = { restoredOpen = null },
            title = { Text("État du poste remis") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    for (l in lines) Text(l)
                    for (d in diffs) Text(d, color = Page.TX)
                    Text("Si un réglage n'a pas été remis, corrige-le à la main.", color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = { restoredOpen = null }) { Text("Fermer") } },
        )
    }
    naming?.let { (name, share) ->
        AlertDialog(
            onDismissRequest = { naming = null },
            title = { Text("Nom de la mesure") },
            text = { OutlinedTextField(name, { naming = it.take(60) to share }, singleLine = true, label = { Text("Légende de l'image") }) },
            confirmButton = {
                TextButton(onClick = {
                    naming = null
                    lastName = name
                    val result = shown ?: return@TextButton
                    val bmp = swrImage(context, result, name)
                    runCatching {
                        if (share) shareImage(context, bmp, name)
                        else say(if (saveImage(context, bmp, name)) "Image enregistrée dans Images/OpenRemoteTRX." else "Enregistrement impossible.")
                    }.onFailure { say("Image impossible : ${it.message}") }
                }) { Text(if (share) "Partager" else "Enregistrer") }
            },
            dismissButton = { TextButton(onClick = { naming = null }) { Text("Annuler") } },
        )
    }
}
