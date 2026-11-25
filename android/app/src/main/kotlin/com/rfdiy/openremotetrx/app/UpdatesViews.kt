// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.app

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.rfdiy.openremotetrx.logic.SeenUpdates
import com.rfdiy.openremotetrx.logic.Tr
import com.rfdiy.openremotetrx.logic.Updates
import com.rfdiy.openremotetrx.protocol.UpdatesInfo
import org.json.JSONObject

/**
 * Mises à jour signalées sous « Connecter » (étape 392) : ce que la station a dit dans `hello.updates` est gardé par
 * station (préférences privées), pour être montré AVANT la connexion suivante. Version Google Play : la mise à jour
 * de l'application est vérifiée par Google Play (StoreUpdates), jamais d'après une APK du dépôt.
 */
internal object UpdateNotes {
    private const val PREFS = "updates"

    fun save(context: Context, stationId: String, stationName: String, info: UpdatesInfo, now: Long = System.currentTimeMillis()) {
        val o = JSONObject()
            .put("station", stationName).put("at", now)
            .put("station_version", info.station?.version ?: "").put("station_url", info.station?.pageUrl ?: "")
            .put("app_version", info.app?.version ?: "").put("app_code", info.app?.code ?: 0).put("app_url", info.app?.pageUrl ?: "")
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(stationId, o.toString()).apply()
    }

    fun load(context: Context, stationId: String?): SeenUpdates? {
        val raw = stationId?.let { context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(it, null) } ?: return null
        return runCatching {
            val o = JSONObject(raw)
            SeenUpdates(station = o.optString("station"), atMs = o.optLong("at"),
                        stationVersion = o.optString("station_version"), stationUrl = o.optString("station_url"),
                        appVersion = o.optString("app_version"), appCode = o.optInt("app_code"), appUrl = o.optString("app_url"))
        }.getOrNull()
    }

    fun forget(context: Context, stationId: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(stationId).apply()
    }
}

/** Lignes « nouvelle version » sous le bouton Connecter, chacune avec son bouton quand il y a une page à ouvrir. */
@Composable
internal fun UpdatesBlock(stationId: String?) {
    val context = LocalContext.current
    LaunchedEffect(Unit) { StoreUpdates.check(context) }
    val storeAvailable by StoreUpdates.available
    val lines = Updates.lines(UpdateNotes.load(context, stationId), BuildConfig.VERSION_CODE, StoreUpdates.STORE_BUILD)
    if (storeAvailable) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(Tr.t("updates.store_available"), style = MaterialTheme.typography.bodySmall, color = Page.ALERTE,
             modifier = Modifier.weight(1f))
        TextButton(onClick = { StoreUpdates.open(context) }, contentPadding = PaddingValues(horizontal = 8.dp)) {
            Text(Tr.t("updates.store_open"))
        }
    }
    for (line in lines) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(line.text, style = MaterialTheme.typography.bodySmall, color = Page.ALERTE, modifier = Modifier.weight(1f))
        if (line.url.isNotEmpty()) TextButton(onClick = { openLink(context, line.url) }, contentPadding = PaddingValues(horizontal = 8.dp)) {
            Text(Tr.t("updates.open"))
        }
    }
}
