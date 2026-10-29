// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.rfdiy.openremotetrx.core.AccountStore
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.LinkStatus

/**
 * Police plus petite que celle de Material (environ 85 %), proche de la page web : il faut placer beaucoup
 * d'informations sur un écran de téléphone (demande de l'utilisateur).
 */
private fun compactTypography(factor: Float = 0.85f): Typography {
    val t = Typography()
    fun TextStyle.small() = copy(fontSize = fontSize * factor, lineHeight = lineHeight * factor)
    return Typography(
        displayLarge = t.displayLarge.small(), displayMedium = t.displayMedium.small(), displaySmall = t.displaySmall.small(),
        headlineLarge = t.headlineLarge.small(), headlineMedium = t.headlineMedium.small(), headlineSmall = t.headlineSmall.small(),
        titleLarge = t.titleLarge.small(), titleMedium = t.titleMedium.small(), titleSmall = t.titleSmall.small(),
        bodyLarge = t.bodyLarge.small(), bodyMedium = t.bodyMedium.small(), bodySmall = t.bodySmall.small(),
        labelLarge = t.labelLarge.small(), labelMedium = t.labelMedium.small(), labelSmall = t.labelSmall.small(),
    )
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        volumeControlStream = AudioManager.STREAM_MUSIC          // touches de volume = volume de la réception
        val store = AccountStore(this)
        setContent {
            MaterialTheme(
                colorScheme = Page.scheme,                         // couleurs de la page web (thème par défaut)
                typography = compactTypography(),
            ) {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    App(store, Modifier.padding(padding))
                }
            }
        }
    }

    /**
     * Sortie de l'application (autre application, écran verrouillé), hors simple rotation : retour en réception si CE
     * téléphone émet, sauf réglage « Rester en émission en quittant l'application » (désactivé par défaut).
     */
    override fun onStop() {
        super.onStop()
        if (isChangingConfigurations) return
        RigHub.leaving(getSharedPreferences("ui", MODE_PRIVATE).getBoolean("keep_tx_background", false))
    }

    private fun granted(permission: String) =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    @Composable
    private fun App(store: AccountStore, modifier: Modifier) {
        val ui by RigHub.ui.collectAsStateWithLifecycle()
        // Autorisations demandées à la connexion : micro (sinon réception seule), notifications (Android 13+).
        val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { pending?.invoke() }
        if (ui.rig.status == LinkStatus.DISCONNECTED) {
            StationScreen(store, ui, modifier, typedPassword, { typedPassword = it }) { account, password ->
                val connect = {
                    pending = null
                    RigHub.connect(this, account, password, useMic = granted(Manifest.permission.RECORD_AUDIO))
                }
                val missing = buildList {
                    if (!granted(Manifest.permission.RECORD_AUDIO)) add(Manifest.permission.RECORD_AUDIO)
                    if (Build.VERSION.SDK_INT >= 33 && !granted(Manifest.permission.POST_NOTIFICATIONS)) add(Manifest.permission.POST_NOTIFICATIONS)
                }
                if (missing.isEmpty()) connect() else {
                    pending = connect
                    ask.launch(missing.toTypedArray())
                }
            }
        } else {
            RigScreen(ui, modifier, onDisconnect = { RigHub.disconnect(this) })
        }
    }

    private var pending: (() -> Unit)? = null

    /** Dernier mot de passe saisi (jamais écrit sur le téléphone s'il n'est pas « mémorisé »). */
    private var typedPassword = ""
}
