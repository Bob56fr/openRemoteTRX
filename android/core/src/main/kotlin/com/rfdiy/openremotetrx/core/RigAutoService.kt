// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.media.MediaDescription
import android.media.browse.MediaBrowser
import android.os.Bundle
import android.service.media.MediaBrowserService
import com.rfdiy.openremotetrx.logic.Car
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.Radio

/**
 * Android Auto (lot A2) : lecteur standard (toutes les voitures compatibles, filaire ou sans fil, aucun code propre à
 * une voiture). Ne possède ni la connexion ni l'état : il prête la session média commune (RigMedia) et liste ce que
 * l'on peut choisir sans rien saisir (stations, mémoires de la station, bandes).
 *
 * Seuls Android Auto, Android Automotive, l'interface système et l'application elle-même peuvent s'y connecter.
 */
class RigAutoService : MediaBrowserService() {
    override fun onCreate() {
        super.onCreate()
        RigMedia.acquire(this, RigMedia.USER_CAR)
        sessionToken = RigMedia.token
        RigMedia.onBrowseChanged = { listOf(ROOT, STATIONS, MEMORIES).forEach { runCatching { notifyChildrenChanged(it) } } }
    }

    override fun onDestroy() {
        RigHub.carConnected(false)
        RigMedia.onBrowseChanged = null
        RigMedia.release(RigMedia.USER_CAR)
        super.onDestroy()
    }

    override fun onGetRoot(clientPackageName: String, clientUid: Int, rootHints: Bundle?): BrowserRoot? {
        if (clientPackageName !in Car.BROWSE_CALLERS && clientPackageName != packageName) return null
        if (clientPackageName == AUTO) RigHub.carConnected(true)          // Android Auto : mode conduite automatique
        return BrowserRoot(ROOT, null)
    }

    override fun onLoadChildren(parentId: String, result: Result<MutableList<MediaBrowser.MediaItem>>) {
        val ui = RigHub.ui.value
        val connected = ui.rig.status == LinkStatus.CONNECTED
        val items: List<MediaBrowser.MediaItem> = when (parentId) {
            ROOT -> listOf(
                folder(STATIONS, "Stations", ui.station?.name?.let { "Connecté : $it" } ?: "Se connecter"),
                folder(MEMORIES, "Mémoires", if (connected) "${ui.rig.memories.size} mémoires" else "Station non connectée"),
                folder(BANDS, "Bandes", "Dernière fréquence de la bande"),
            )
            STATIONS -> buildList {
                for (account in AccountStore(this@RigAutoService).list()) {
                    val current = ui.station?.id == account.id && ui.rig.status != LinkStatus.DISCONNECTED
                    add(playable("$STATION:${account.id}", account.name, if (current) "connectée" else account.url))
                }
                if (ui.rig.status != LinkStatus.DISCONNECTED) add(playable("$DISCONNECT:", "Déconnecter", ui.station?.name ?: ""))
            }
            MEMORIES -> if (!connected) emptyList() else ui.rig.memories.map { m ->
                playable("$MEMORY:${m.id}", (if (m.favorite) "★ " else "") + m.name, "${Car.frequency(m.hz)} ${Radio.modeLabel(m.mode)}")
            }
            BANDS -> if (!connected) emptyList() else Radio.BANDS.map { b -> playable("$BAND:${b.key}", "${b.key} m", Car.frequency(b.start) ?: "") }
            else -> emptyList()
        }
        result.sendResult(items.toMutableList())
    }

    private fun folder(id: String, title: String, subtitle: String) =
        MediaBrowser.MediaItem(MediaDescription.Builder().setMediaId(id).setTitle(title).setSubtitle(subtitle).build(), MediaBrowser.MediaItem.FLAG_BROWSABLE)

    private fun playable(id: String, title: String, subtitle: String) =
        MediaBrowser.MediaItem(MediaDescription.Builder().setMediaId(id).setTitle(title).setSubtitle(subtitle).build(), MediaBrowser.MediaItem.FLAG_PLAYABLE)

    companion object {
        const val AUTO = "com.google.android.projection.gearhead"
        const val ROOT = "root"
        const val STATIONS = "stations"
        const val MEMORIES = "memories"
        const val BANDS = "bands"
        const val STATION = "station"
        const val MEMORY = "memory"
        const val BAND = "band"
        const val DISCONNECT = "disconnect"
    }
}
