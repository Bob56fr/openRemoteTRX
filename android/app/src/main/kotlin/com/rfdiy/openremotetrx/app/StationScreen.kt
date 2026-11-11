// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.core.AccountStore
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.rfdiy.openremotetrx.protocol.Fingerprint
import com.rfdiy.openremotetrx.protocol.PairingCode
import com.rfdiy.openremotetrx.core.RigUi
import com.rfdiy.openremotetrx.core.StationAccount
import com.rfdiy.openremotetrx.logic.QrImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import com.rfdiy.openremotetrx.protocol.StationAddress

private val WINDOWS = listOf(0, 30, 60, 120, 300)

/**
 * Choix ou appairage d'une station : adresse, identifiant, mot de passe et empreinte du certificat
 * (TRX Console menu 4.1). La dernière cause de déconnexion reste affichée.
 */
@Composable
fun StationScreen(
    store: AccountStore,
    ui: RigUi,
    modifier: Modifier,
    typedPassword: String,
    onTyped: (String) -> Unit,
    onConnect: (StationAccount, String) -> Unit,
) {
    var accounts by remember { mutableStateOf(store.list()) }
    val context = LocalContext.current
    val version = remember { runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: "?" }
    val initial = accounts.firstOrNull { it.id == store.lastId } ?: accounts.firstOrNull()
    var editing by remember { mutableStateOf(initial) }
    var name by remember { mutableStateOf(initial?.name ?: "") }
    var address by remember { mutableStateOf(initial?.url ?: "") }
    var user by remember { mutableStateOf(initial?.user ?: "") }
    // Mot de passe non mémorisé : gardé en mémoire tant que l'application est ouverte (comme la page), pour réessayer.
    var password by remember { mutableStateOf(initial?.let { store.password(it) } ?: typedPassword) }
    var keepPassword by remember { mutableStateOf(initial?.secret?.isNotEmpty() ?: false) }
    var fingerprint by remember { mutableStateOf(initial?.fingerprint ?: "") }
    var window by remember { mutableStateOf(initial?.reconnectWindowS ?: 60) }
    var error by remember { mutableStateOf("") }

    fun select(a: StationAccount?) {
        editing = a
        name = a?.name ?: ""; address = a?.url ?: ""; user = a?.user ?: ""
        password = a?.let { store.password(it) } ?: ""; keepPassword = a?.secret?.isNotEmpty() ?: false
        fingerprint = a?.fingerprint ?: ""; window = a?.reconnectWindowS ?: 60; error = ""
    }

    // QR code du menu 4.1 de TRX Console : adresse, identifiant, empreinte. Le mot de passe reste à saisir.
    // Lu par l'appareil photo, ou dans une image de la bibliothèque (photo, capture d'écran reçue par message…).
    var notice by remember { mutableStateOf("") }
    fun applyPairing(text: String) {
        val pairing = PairingCode.parse(text)
        if (pairing == null) {
            notice = ""
            error = "Ce QR code n'est pas un QR code d'appairage openRemoteTRX (TRX Console, menu 4.1)."
            return
        }
        val known = accounts.firstOrNull { it.url == pairing.url && (pairing.user.isEmpty() || it.user == pairing.user) }
        select(known)
        notice = when {
            known == null -> "Station lue sur le QR code : saisis le mot de passe puis « Connecter »."
            known.fingerprint != pairing.fingerprint -> "Station déjà connue : empreinte du certificat MISE À JOUR depuis le QR code."
            else -> "Station déjà connue : rien n'a changé."
        }
        name = known?.name ?: pairing.name
        address = pairing.url
        if (pairing.user.isNotEmpty()) user = pairing.user
        fingerprint = pairing.fingerprint
    }
    val scan = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { applyPairing(it) }
    }
    val scope = rememberCoroutineScope()
    val pickImage = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        notice = "Lecture de l'image…"
        error = ""
        scope.launch {
            val text = withContext(Dispatchers.Default) { qrFromImage(context, uri) }
            if (text == null) {
                notice = ""
                error = "Aucun QR code trouvé dans cette image : recadre-la sur le QR code (net, entier, sans reflet) ou scanne-le."
            } else {
                applyPairing(text)
            }
        }
    }

    Column(
        modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("openRemoteTRX", style = MaterialTheme.typography.headlineSmall)
            Text("version $version", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
        }
        // Tablette ou grande fenêtre (≥ 840 dp) : boutons QR côte à côte, champs sur deux colonnes, sans défilement
        val wide = LocalConfiguration.current.screenWidthDp >= com.rfdiy.openremotetrx.logic.ScreenLayouts.WIDE_MIN_DP
        val qrButtons: @Composable () -> Unit = {
            OutlinedButton(onClick = {
                scan.launch(
                    ScanOptions()
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("QR code du menu 4.1 de TRX Console")
                        .setBeepEnabled(false)
                        .setOrientationLocked(false)
                        .addExtra(Intents.Scan.SCAN_TYPE, Intents.Scan.MIXED_SCAN)   // terminal sombre (inversé) ou clair
                )
            }) { Text("Scanner le QR code de la station") }
            OutlinedButton(onClick = {
                pickImage.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            }) { Text("Lire le QR code depuis une image") }
        }
        if (wide) Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { qrButtons() } else qrButtons()
        if (notice.isNotEmpty()) Text(notice, color = MaterialTheme.colorScheme.primary)
        if (accounts.isNotEmpty()) {
            Text("Stations", style = MaterialTheme.typography.titleMedium)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (a in accounts) FilterChip(selected = editing?.id == a.id, onClick = { select(a) }, label = { Text(a.name) })
                FilterChip(selected = editing == null, onClick = { select(null) }, label = { Text("+ Nouvelle") })
            }
        }
        val identity: @Composable () -> Unit = {
            OutlinedTextField(name, { name = it }, label = { Text("Nom") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(
                address, { address = it }, label = { Text("Adresse (ex. 192.168.1.10:8443)") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(user, { user = it }, label = { Text("Identifiant") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(
                password, { password = it; onTyped(it) }, label = { Text("Mot de passe") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth(),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(keepPassword, { keepPassword = it })
                Text("Mémoriser le mot de passe (chiffré sur cet appareil)")
            }
        }
        val security: @Composable () -> Unit = {
            OutlinedTextField(
                fingerprint, { fingerprint = it }, label = { Text("Empreinte du certificat (TRX Console, menu 4.1)") },
                supportingText = { Text("Vide seulement derrière un proxy HTTPS à certificat reconnu.") },
                minLines = 2, modifier = Modifier.fillMaxWidth(),
            )
            Text("Reconnexion automatique après une coupure", style = MaterialTheme.typography.titleSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (w in WINDOWS) FilterChip(selected = window == w, onClick = { window = w }, label = { Text(if (w == 0) "non" else "$w s") })
            }
            if (error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    val url = StationAddress.normalize(address)
                    val pin = if (fingerprint.isBlank()) "" else Fingerprint.normalize(fingerprint)
                    error = when {
                        name.isBlank() -> "Donne un nom à la station."
                        url == null -> "Adresse invalide : hôte ou IP, port facultatif (8443), HTTPS uniquement."
                        user.isBlank() -> "Identifiant manquant."
                        password.isEmpty() -> "Mot de passe manquant."
                        pin == null -> "Empreinte invalide : 32 octets en hexadécimal (AB:CD:…)."
                        else -> ""
                    }
                    if (error.isEmpty()) {
                        val base = editing ?: StationAccount(name = name.trim(), url = url!!, user = user.trim())
                        val account = store.save(
                            base.copy(name = name.trim(), url = url!!, user = user.trim(), fingerprint = pin!!, reconnectWindowS = window),
                            if (keepPassword) password else "",
                        )
                        store.lastId = account.id
                        accounts = store.list()
                        editing = account
                        onConnect(account, password)
                    }
                }) { Text("Connecter") }
                val current = editing
                if (current != null) OutlinedButton(onClick = {
                    store.delete(current.id)
                    accounts = store.list()
                    select(accounts.firstOrNull())
                }) { Text("Supprimer") }
            }
            val last = ui.rig.log.lastOrNull()
            if (last != null) {
                Text("Dernier message", style = MaterialTheme.typography.titleSmall)
                Text(last.text, style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (wide) {
            Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) { identity() }
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) { security() }
            }
        } else {
            identity()
            security()
        }
    }
}

/** Plus grand côté décodé : une photo de 50 Mpx est réduite (mémoire, temps) ; un QR code reste lisible bien en dessous. */
private const val QR_IMAGE_MAX = 2000

/** Texte du QR code d'une image de la bibliothèque, null si illisible ou sans QR code. Hors du fil principal. */
private fun qrFromImage(context: Context, uri: Uri): String? = runCatching {
    val source = ImageDecoder.createSource(context.contentResolver, uri)
    val bitmap = ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE                      // pixels lisibles (getPixels)
        val big = maxOf(info.size.width, info.size.height)
        if (big > QR_IMAGE_MAX) {
            val k = QR_IMAGE_MAX.toFloat() / big
            decoder.setTargetSize((info.size.width * k).toInt().coerceAtLeast(1), (info.size.height * k).toInt().coerceAtLeast(1))
        }
    }
    val argb = if (bitmap.config == Bitmap.Config.ARGB_8888) bitmap else bitmap.copy(Bitmap.Config.ARGB_8888, false)
    val px = IntArray(argb.width * argb.height)
    argb.getPixels(px, 0, argb.width, 0, 0, argb.width, argb.height)
    QrImage.decode(argb.width, argb.height, px)
}.getOrNull()
