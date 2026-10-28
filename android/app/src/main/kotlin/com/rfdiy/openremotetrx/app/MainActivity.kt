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
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.rfdiy.openremotetrx.core.AccountStore
import com.rfdiy.openremotetrx.core.RigHub
import com.rfdiy.openremotetrx.logic.LinkStatus

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        volumeControlStream = AudioManager.STREAM_MUSIC          // touches de volume = volume de la réception
        val store = AccountStore(this)
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    App(store, Modifier.padding(padding))
                }
            }
        }
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
