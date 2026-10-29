// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.media.MediaPlayer
import android.os.Environment
import android.provider.MediaStore
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.SelcallStatus
import com.rfdiy.openremotetrx.logic.SelcallTones
import java.io.File
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

private val CALL_TIME = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault())

/**
 * Panneau SELCALL (comme la page) : état, code, historique, Activer / Réarmer / Désactiver, filtrage des tonalités,
 * dernier appel, et fichier de test à PARTAGER (WhatsApp, Signal…) pour qu'un correspondant le joue au micro de son
 * poste. Le fichier est fabriqué sur le téléphone, sans la station.
 */
@Composable
fun SelcallDialog(status: SelcallStatus, connected: Boolean, armed: Boolean, transmitting: Boolean, mine: Boolean, onDismiss: () -> Unit) {
    val context = LocalContext.current
    var code by remember { mutableStateOf(status.code) }
    var testCode by remember { mutableStateOf(status.code) }
    var attDrag by remember { mutableStateOf<Float?>(null) }
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var note by remember { mutableStateOf("") }
    DisposableEffect(Unit) { onDispose { player?.release() } }
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Fermer") } },
        title = { Text("SELCALL") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "Squelch numérique de la station par appel de groupe : armé sur un code, il coupe le son reçu jusqu'à ce " +
                        "qu'une station du groupe envoie ce code, puis le laisse ouvert jusqu'à ce que vous réarmiez.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    "État : " + (SelcallStatus.STATE_LABELS[status.state] ?: status.state) +
                        if (!status.disabled) " (code ${status.code})" else "",
                    style = MaterialTheme.typography.titleSmall,
                )
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        code, { v -> code = v.filter { it.isDigit() }.take(8) }, label = { Text("Code (3 à 8 chiffres)") },
                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                        modifier = Modifier.weight(1f),
                    )
                    Button(onClick = { RigHub.selcallActivate(code) }, enabled = connected && SelcallTones.validCode(code)) { Text("Activer") }
                }
                if (status.history.isNotEmpty()) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (h in status.history) {
                            CompactChip(h, onClick = { code = h; RigHub.selcallActivate(h) }, enabled = connected,
                                selected = h == status.code && !status.disabled)
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { RigHub.selcallRearm() }, enabled = connected && !status.disabled) { Text("Réarmer") }
                    OutlinedButton(onClick = { RigHub.selcallDeactivate() }, enabled = connected && !status.disabled) { Text("Désactiver") }
                }
                Text("Tonalités dans le son reçu", style = MaterialTheme.typography.bodyMedium)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((mode, label) in SelcallStatus.FILTER_MODES) {
                        CompactChip(label, onClick = { RigHub.selcallOptions(filterMode = mode) }, enabled = connected,
                            selected = mode == status.filterMode)
                    }
                }
                if (status.filterMode == "attenuate") {
                    val shown = attDrag ?: status.attenuationDb.toFloat()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Atténuation", style = MaterialTheme.typography.bodySmall)
                        Slider(
                            value = shown, onValueChange = { attDrag = it }, valueRange = 6f..60f, enabled = connected,
                            onValueChangeFinished = { attDrag?.let { RigHub.selcallOptions(attenuationDb = it.roundToInt()) }; attDrag = null },
                            modifier = Modifier.weight(1f),
                        )
                        Text("${shown.roundToInt()} dB", style = MaterialTheme.typography.bodySmall)
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.Switch(
                        checked = status.sendOnTxEnd, enabled = connected,
                        onCheckedChange = { RigHub.selcallOptions(sendOnTxEnd = it) },
                    )
                    Text("  Envoyer la trame en fin d'émission (à la place du roger bip ; émise par la station)",
                        style = MaterialTheme.typography.bodySmall)
                }
                // Appel manuel : une ÉMISSION (« Émission autorisée » exigée) ; pendant l'appel, le bouton annule (STOP)
                val sending = status.sending.isNotEmpty() || (mine && transmitting)
                Button(
                    onClick = { if (sending) RigHub.stop() else RigHub.selcallSend() },
                    enabled = connected && (sending || (!status.disabled && armed && !transmitting)),
                    colors = if (sending) androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = Page.TX) else
                        androidx.compose.material3.ButtonDefaults.buttonColors(),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (sending) "Annuler" + (status.sending.takeIf { it.isNotEmpty() }?.let { " ($it)" } ?: "") else "Envoyer SELCALL") }
                if (!sending && !armed) Text("Activez « Émission autorisée » : l'appel SELCALL est une émission.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
                Text(
                    status.lastCall?.let {
                        "Dernier appel : ${it.code} à ${CALL_TIME.format(Instant.ofEpochMilli((it.at * 1000).toLong()))} " +
                            "(décalage ${if (it.deltaHz > 0) "+" else ""}${it.deltaHz} Hz, SNR ${it.snrDb} dB)"
                    } ?: "Aucun appel reçu.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                HorizontalDivider(color = Page.LIGNE)
                Text("Fichier de test (pour un correspondant)", style = MaterialTheme.typography.titleSmall)
                Text(
                    "Fabriqué ici : 2 s de silence puis la trame 3 fois. À envoyer comme DOCUMENT (pas en message vocal) ; " +
                        "le correspondant le joue au micro de son poste, volume moyen, en émission, et s'identifie.",
                    color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    testCode, { v -> testCode = v.filter { it.isDigit() }.take(8) }, label = { Text("Code du fichier") },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.fillMaxWidth(),
                )
                val ok = SelcallTones.validCode(testCode)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedButton(onClick = {
                        player?.let { it.release(); player = null; return@OutlinedButton }
                        val file = testFile(context, testCode)
                        player = MediaPlayer().apply {
                            setDataSource(file.path)
                            setOnCompletionListener { mp -> mp.release(); player = null }
                            prepare(); start()                         // sur le téléphone seulement, jamais émis
                        }
                    }, enabled = ok) { Text(if (player != null) "Arrêter" else "Écouter") }
                    Button(onClick = { note = share(context, testCode) }, enabled = ok) { Text("Partager") }
                    OutlinedButton(onClick = { note = saveToDownloads(context, testCode) }, enabled = ok) { Text("Téléchargements") }
                }
                if (note.isNotEmpty()) Text(note, color = Page.TEXTE_2, style = MaterialTheme.typography.bodySmall)
            }
        },
    )
}

/** Fichier de test dans le cache de l'application (partagé par FileProvider, jamais lisible par une autre application sans lui). */
private fun testFile(context: Context, code: String): File {
    val dir = File(context.cacheDir, "selcall").apply { mkdirs() }
    return File(dir, "selcall-$code.wav").apply { writeBytes(SelcallTones.testWav(code)) }
}

private fun share(context: Context, code: String): String = try {
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", testFile(context, code))
    val send = Intent(Intent.ACTION_SEND).setType("audio/wav").putExtra(Intent.EXTRA_STREAM, uri)
        .putExtra(Intent.EXTRA_SUBJECT, "SELCALL $code (fichier de test openRemoteTRX)")
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, "Envoyer le fichier SELCALL $code").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    ""
} catch (e: Exception) {
    "Partage impossible : ${e.message}"
}

/** Copie dans Téléchargements (Android 10+, sans autorisation) : retrouvable ensuite par n'importe quelle application. */
private fun saveToDownloads(context: Context, code: String): String = try {
    val values = ContentValues().apply {
        put(MediaStore.Downloads.DISPLAY_NAME, "selcall-$code.wav")
        put(MediaStore.Downloads.MIME_TYPE, "audio/wav")
        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }
    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: error("emplacement refusé")
    resolver.openOutputStream(uri)?.use { it.write(SelcallTones.testWav(code)) } ?: error("écriture refusée")
    "Enregistré dans Téléchargements : selcall-$code.wav"
} catch (e: Exception) {
    "Enregistrement impossible : ${e.message}"
}
