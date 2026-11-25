// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.net.URI

/**
 * Liens de l'application vers les pages de la station et mises à jour signalées sous « Connecter » (étape 392).
 * Kotlin pur (compilé aussi par openRemoteTRX Lite) : aucun appel Android.
 */
object StationLinks {
    /**
     * Adresse d'openRemoteTRX Console sur le réseau : MÊME adresse que la station (celle que le téléphone joint déjà,
     * VPN compris), port de `hello.remote_console`, toujours en HTTPS (même certificat, comme la page) ; null si
     * l'adresse de la station est illisible ou le port hors des ports permis.
     */
    fun consoleUrl(stationUrl: String, port: Int?): String? {
        if (port == null || port !in 1024..65535) return null
        val host = try { URI(stationUrl.trim()).host } catch (e: Exception) { null }
        if (host.isNullOrEmpty()) return null
        val shown = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host     // IPv6 entre crochets
        return "https://$shown:$port/"
    }
}

/** Dernières versions publiées vues par une station (`hello.updates`), gardées par l'application pour l'écran de connexion. */
data class SeenUpdates(
    val station: String,               // nom de la station qui l'a dit
    val atMs: Long,                    // quand
    val stationVersion: String = "",   // version de la station plus récente que celle qui tourne, ou ""
    val stationUrl: String = "",
    val appVersion: String = "",       // dernière APK publiée, ou ""
    val appCode: Int = 0,
    val appUrl: String = "",
)

/** Ligne affichée sous « Connecter » ; `url` = page de la version à ouvrir, ou "" (rien à ouvrir). */
data class UpdateLine(val text: String, val url: String = "")

object Updates {
    /** Menu « Mise à jour » d'openRemoteTRX Console (numéros figés depuis la station 0.166.0). */
    const val STATION_MENU = "7.1"

    /**
     * Lignes de l'écran de connexion. `myCode` = versionCode de l'application installée ; `storeBuild` = version
     * Google Play (sa mise à jour est vérifiée par Google Play, jamais d'après une APK du dépôt).
     */
    fun lines(seen: SeenUpdates?, myCode: Int, storeBuild: Boolean): List<UpdateLine> {
        if (seen == null) return emptyList()
        val out = mutableListOf<UpdateLine>()
        if (!storeBuild && seen.appVersion.isNotEmpty() && seen.appCode > myCode) {
            out += UpdateLine(Tr.t("updates.app_available", "version" to seen.appVersion, "station" to seen.station,
                                   "date" to Format.dayTime(seen.atMs)), seen.appUrl)
        }
        if (seen.stationVersion.isNotEmpty()) {
            out += UpdateLine(Tr.t("updates.station_available", "station" to seen.station, "version" to seen.stationVersion,
                                   "menu" to STATION_MENU), seen.stationUrl)
        }
        return out
    }
}
