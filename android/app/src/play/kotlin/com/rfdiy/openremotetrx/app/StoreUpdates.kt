// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.install.model.UpdateAvailability

/**
 * Version Google Play (étape 392) : nouvelle version demandée à Google Play (bibliothèque « In-app updates »), la mise
 * à jour se fait par le Store (fiche ouverte). Une erreur (Store absent, hors ligne) ne montre simplement rien.
 */
internal object StoreUpdates {
    const val STORE_BUILD = true
    val available = mutableStateOf(false)

    fun check(context: Context) {
        runCatching {
            AppUpdateManagerFactory.create(context).appUpdateInfo
                .addOnSuccessListener { info -> available.value = info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE }
        }
    }

    fun open(context: Context) {
        openLink(context, "market://details?id=${context.packageName}") ||
            openLink(context, "https://play.google.com/store/apps/details?id=${context.packageName}")
    }
}
