// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.FileProvider
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.NetUi
import com.rfdiy.openremotetrx.logic.RigState
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private fun netColor(level: String) = when (level) {
    "green" -> Page.SUCCES
    "orange" -> Page.ALERTE
    "red" -> Page.TX
    else -> Page.TEXTE_2
}

/** Pastille de la barre du haut (page : #net-bar) : type de réseau et trois barres (forme lisible sans la couleur). */
@Composable
fun NetChip(view: NetUi.View, onClick: () -> Unit) {
    Row(
        Modifier.border(1.dp, if (view.outage) Page.TX else Page.BORD, RoundedCornerShape(4.dp))
            .background(Page.CHAMP, RoundedCornerShape(4.dp)).clickable(onClick = onClick).padding(horizontal = 5.dp, vertical = 3.dp),
        verticalAlignment = Alignment.Bottom,
    ) {
        Text(view.netType, style = MaterialTheme.typography.labelSmall, color = Page.TEXTE_2)
        Spacer(Modifier.width(4.dp))
        for (i in 0 until 3) {
            Box(Modifier.padding(start = 2.dp).width(4.dp).height((8 + i * 5).dp)
                .background(if (i < view.bars) netColor(view.level) else Page.BORD, RoundedCornerShape(1.dp)))
        }
    }
}

@Composable
private fun Rows(rows: List<Pair<String, String>>, firstBad: Boolean = false) {
    rows.forEachIndexed { i, (label, value) ->
        val bad = firstBad && i == 0
        Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
            Text(label, style = MaterialTheme.typography.bodySmall, color = if (bad) Page.TX else Page.TEXTE_2, modifier = Modifier.width(150.dp))
            Text(value, style = MaterialTheme.typography.bodySmall, color = if (bad) Page.TX else Page.TEXTE, modifier = Modifier.weight(1f))
        }
        HorizontalDivider(color = Page.LIGNE)
    }
}

/** Détail de la liaison (page : accordéon #net-detail). */
@Composable
fun NetDialog(view: NetUi.View, operator: Boolean, onStats: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Liaison avec la station") },
        text = {
            Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(view.title.removeSuffix(". Touche : détail"), style = MaterialTheme.typography.bodySmall, color = netColor(view.level))
                Rows(view.rows, view.outage)
                if (view.probes.isNotEmpty()) {
                    Text("Sondes de la station", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(top = 6.dp))
                    Rows(view.probes)
                }
                for (w in view.vpn) {
                    Column(Modifier.fillMaxWidth().background(Color(0xFF5A4208), RoundedCornerShape(6.dp)).padding(8.dp)) {
                        Text(w.text, style = MaterialTheme.typography.bodySmall, color = Color(0xFFFFD88A))
                        TextButton(onClick = { RigHub.netVpnIgnore(w.address) }) { Text("Ignorer pour cette adresse") }
                    }
                }
                if (view.thresholds.isNotEmpty()) Text(view.thresholds, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        dismissButton = if (operator) ({ TextButton(onClick = onStats) { Text("Statistiques 30 jours") } }) else null,
    )
}

private fun shareZip(context: Context, name: String, bytes: ByteArray) {
    val dir = File(context.cacheDir, "netprobe").apply { mkdirs() }
    dir.listFiles()?.forEach { it.delete() }                       // un seul export gardé
    val file = File(dir, name.replace(Regex("[^\\w.-]"), "_"))
    file.writeBytes(bytes)
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
    val send = Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM, uri)
        .putExtra(Intent.EXTRA_SUBJECT, "Qualité du réseau OpenRemoteTRX (export anonyme)").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, "Envoyer l'export à l'équipe de développement"))
}

@Composable
private fun Bar(label: String, fraction: Double, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2, modifier = Modifier.width(120.dp))
        Column(Modifier.weight(1f)) {
            Box(Modifier.fillMaxWidth().height(10.dp).background(Page.CHAMP, RoundedCornerShape(2.dp))) {
                Box(Modifier.fillMaxWidth(fraction.toFloat().coerceIn(0f, 1f)).fillMaxHeight().background(Page.ACCENT, RoundedCornerShape(2.dp)))
            }
            Text(value, style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun Title(text: String) {
    Text(text, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 10.dp))
}

/** « Qualité du réseau » (page : rubrique #sec-net) : plein écran ouvert depuis les Réglages ou le détail. */
@Composable
fun NetScreen(rig: RigState, onClose: () -> Unit) {
    val context = LocalContext.current
    var days by remember { mutableIntStateOf(30) }
    var confirmClear by remember { mutableStateOf(false) }
    LaunchedEffect(days) { RigHub.netStats(days) }
    val ready by RigHub.netExportReady.collectAsState()
    LaunchedEffect(ready) {
        ready?.let { (name, bytes) -> RigHub.netExportTaken(); shareZip(context, name, bytes) }
    }
    val m = rig.netStats
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = Page.FOND) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Qualité du réseau", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    TextButton(onClick = onClose) { Text("Fermer") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((d, label) in listOf(1 to "24 h", 7 to "7 jours", 30 to "30 jours")) CompactChip(label, onClick = { days = d }, selected = days == d)
                    CompactChip("Actualiser", onClick = { RigHub.netStats(days) })
                }
                if (rig.netStatus.isNotEmpty()) Text(rig.netStatus, style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
                if (m != null) {
                    Title("Synthèse"); Rows(m.summary)
                    Title("Coupures par jour")
                    if (m.days.isEmpty()) Text("Aucune mesure sur la période.", style = MaterialTheme.typography.bodySmall)
                    for (d in m.days) Bar(d.date, d.fraction, d.short)
                    Title("Heures les plus touchées")
                    for (d in m.days) {
                        Row(Modifier.fillMaxWidth().padding(vertical = 1.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(d.date.takeLast(5), style = MaterialTheme.typography.labelSmall, color = Page.TEXTE_2, modifier = Modifier.width(44.dp))
                            for ((n, f) in d.hours) {
                                Box(Modifier.weight(1f).height(10.dp).padding(horizontal = 1.dp)
                                    .background(if (n == 0) Page.CHAMP else Page.ACCENT.copy(alpha = (0.25 + 0.75 * f).toFloat()), RoundedCornerShape(2.dp)))
                            }
                        }
                    }
                    Text("0 h à 23 h, heure de la station", style = MaterialTheme.typography.labelSmall, color = Page.TEXTE_2)
                    Title("Tronçon probable")
                    if (m.diagnoses.isEmpty()) Text("Aucune coupure.", style = MaterialTheme.typography.bodySmall)
                    for (d in m.diagnoses) Bar(d.label, d.fraction, "${d.count} (${(d.fraction * 100).toInt()} %)")
                    Title("Par réseau"); Rows(m.types.ifEmpty { listOf("—" to "aucune mesure") })
                    Title("Dernières coupures")
                    val fmt = SimpleDateFormat("dd/MM HH:mm:ss", Locale.FRANCE)
                    if (m.outages.isEmpty()) Text("Aucune coupure sur la période.", style = MaterialTheme.typography.bodySmall)
                    for (o in m.outages) {
                        Text(fmt.format(Date(o.whenMs)) + " — ${o.duration} — ${o.diagnosis}" + (if (o.agent.isNotEmpty()) " — ${o.agent}" else "") +
                            (if (o.net.isNotEmpty()) " (${o.net})" else "") + " — ${o.kind}" + (if (o.basis.isNotEmpty()) " ; d'après : ${o.basis}" else ""),
                            style = MaterialTheme.typography.bodySmall)
                        HorizontalDivider(color = Page.LIGNE)
                    }
                    Title("Seuils de l'indicateur")
                    Text("Les seuils ne changent que la couleur de l'indicateur et les alertes, jamais l'émission. Déplacez les curseurs : " +
                        "le texte dit ce qu'ils auraient donné sur l'historique, sans rien changer. « Appliquer » les garde sur la station pour ce type de réseau.",
                        style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
                    if (m.thresholds.isEmpty()) Text("Pas encore de mesures par type de réseau.", style = MaterialTheme.typography.bodySmall)
                    for (t in m.thresholds) ThresholdCard(t, m.rttEdges, m.lossEdges)
                }
                Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { RigHub.netExport() }) { Text("Exporter (anonyme)") }
                    OutlinedButton(onClick = { confirmClear = !confirmClear }) { Text("Tout effacer…") }
                }
                if (confirmClear) {
                    OutlinedButton(onClick = { confirmClear = false; RigHub.netClear() }) {
                        Text("Effacer l'historique réseau", color = Page.TX)
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

@Composable
private fun ThresholdCard(t: NetUi.Thresholds, rttEdges: List<Double>, lossEdges: List<Double>) {
    var rttWarn by remember(t) { mutableFloatStateOf((t.inForce["rtt_warn"] ?: 250.0).toFloat()) }
    var rttAlert by remember(t) { mutableFloatStateOf((t.inForce["rtt_alert"] ?: 600.0).toFloat()) }
    var lossWarn by remember(t) { mutableFloatStateOf((t.inForce["loss_warn"] ?: 2.0).toFloat()) }
    var lossAlert by remember(t) { mutableFloatStateOf((t.inForce["loss_alert"] ?: 10.0).toFloat()) }
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp).border(1.dp, Page.LIGNE, RoundedCornerShape(6.dp)).padding(8.dp)) {
        Text(t.label + if (t.chosen) " — seuils choisis" else " — seuils de station.toml", style = MaterialTheme.typography.titleSmall)
        val pr = t.proposedRtt; val pl = t.proposedLoss
        Text(if (pr != null || pl != null) "Proposé d'après vos mesures : " + listOfNotNull(
                pr?.let { "aller-retour ${it.warn.toInt()} / ${it.alert?.toInt() ?: "—"} ms" }, pl?.let { "perte ${NetUi.number(it.warn, "%")} / ${NetUi.number(it.alert, "%")}" }).joinToString(", ")
             else "Pas encore de proposition (7 jours et 2 000 mesures de 10 s de ce réseau ; ${t.days.toInt()} jour(s) aujourd'hui).",
            style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        @Composable
        fun line(label: String, value: Float, range: ClosedFloatingPointRange<Float>, step: Float, unit: String, set: (Float) -> Unit) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(120.dp))
                Slider(value = value, onValueChange = { set((Math.round(it / step) * step).coerceIn(range)) }, valueRange = range, modifier = Modifier.weight(1f))
                Text(NetUi.number(value.toDouble(), unit), style = MaterialTheme.typography.labelSmall, modifier = Modifier.width(56.dp))
            }
        }
        line("Aller-retour orange", rttWarn, 50f..1500f, 50f, "ms") { rttWarn = it }
        line("Aller-retour rouge", rttAlert, 100f..3000f, 50f, "ms") { rttAlert = it }
        line("Perte orange", lossWarn, 0.5f..20f, 0.5f, "%") { lossWarn = it }
        line("Perte rouge", lossAlert, 1f..50f, 1f, "%") { lossAlert = it }
        Text(NetUi.simulationText(t, rttEdges, lossEdges, rttWarn.toDouble(), rttAlert.toDouble(), lossWarn.toDouble(), lossAlert.toDouble()),
            style = MaterialTheme.typography.bodySmall, color = Page.TEXTE_2)
        val ok = rttWarn < rttAlert && lossWarn < lossAlert
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            if (pr != null || pl != null) CompactChip("Prendre la proposition", onClick = {
                pr?.let { rttWarn = it.warn.toFloat(); it.alert?.let { a -> rttAlert = a.toFloat() } }
                pl?.let { lossWarn = it.warn.toFloat(); it.alert?.let { a -> lossAlert = a.toFloat() } }
            })
            CompactChip("Appliquer", enabled = ok, onClick = {
                RigHub.netThresholds(t.netType, rttWarn.toDouble(), rttAlert.toDouble(), lossWarn.toDouble(), lossAlert.toDouble())
            })
            if (t.chosen) CompactChip("Revenir à station.toml", onClick = { RigHub.netThresholdsReset(t.netType) })
        }
        if (!ok) Text("L'orange doit être plus petit que le rouge.", style = MaterialTheme.typography.labelSmall, color = Page.ALERTE,
            modifier = Modifier.alpha(0.9f))
    }
}
