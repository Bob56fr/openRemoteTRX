// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import androidx.compose.runtime.mutableStateOf

/**
 * Application installée à la main (APK) : aucune vérification par Google Play ; la nouvelle version est signalée
 * d'après la station (`hello.updates`, UpdatesViews.kt). Même objet que src/play (version Google Play).
 */
internal object StoreUpdates {
    const val STORE_BUILD = false
    val available = mutableStateOf(false)

    fun check(context: Context) = Unit

    fun open(context: Context) = Unit
}
