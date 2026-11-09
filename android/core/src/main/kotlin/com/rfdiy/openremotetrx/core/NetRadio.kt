// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.telephony.CellInfo
import android.telephony.CellInfoLte
import android.telephony.CellInfoNr
import android.telephony.CellSignalStrengthLte
import android.telephony.CellSignalStrengthNr
import android.telephony.TelephonyManager
import androidx.core.content.ContextCompat
import com.rfdiy.openremotetrx.logic.RadioSample

/**
 * Radio du téléphone pour la sonde réseau (EF11, docs/netprobe-cahier-des-charges.md § 13). Relevé de base SANS
 * autorisation : type de réseau (Wi-Fi, mobile, réseau local ; 4G ou 5G d'après la puissance relevée), RSRP / RSSNR
 * (4G) ou SS-RSRP / SS-SINR (5G), niveau 0 à 4, bascule de réseau. Changement de cellule : seulement si l'utilisateur
 * l'a activé ET a donné l'autorisation de localisation (version installée à la main ; jamais dans la version Google
 * Play, qui ne déclare pas cette autorisation). AUCUNE position n'est lue : seul l'identifiant de la cellule servante.
 * Appelé sur le fil de la session : `sample()` toutes les 2 s, `take()` à chaque résumé (remet les faits à zéro).
 */
class NetRadio(private val context: Context) {
    private val tm = context.getSystemService(TelephonyManager::class.java)
    private val cm = context.getSystemService(ConnectivityManager::class.java)
    private var transport: String? = null
    private var network: String? = null
    private var cell: String? = null
    private var cellChanged = false
    private var netSwitched = false
    private var last = RadioSample()

    /** Changement de cellule demandé par l'utilisateur (Réglages) ; sans l'autorisation, rien n'est lu. */
    private fun cellsWanted(): Boolean =
        context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).getBoolean(RigHub.PREF_NET_CELLS, false) &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun transportOf(caps: NetworkCapabilities?): String? = when {
        caps == null -> null
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "lan"
        else -> null
    }

    /** Réseau réellement utilisé : derrière un VPN, le réseau sous-jacent (Wi-Fi d'abord, puis mobile). */
    @Suppress("DEPRECATION")
    private fun current(): Pair<String?, String?> {
        val cm = cm ?: return null to null
        val active = cm.activeNetwork ?: return null to null
        transportOf(cm.getNetworkCapabilities(active))?.let { return it to active.toString() }
        val under = cm.allNetworks.mapNotNull { n ->
            val caps = cm.getNetworkCapabilities(n) ?: return@mapNotNull null
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) null
            else transportOf(caps)?.let { it to n.toString() }
        }
        return (under.firstOrNull { it.first == "wifi" } ?: under.firstOrNull()) ?: ("unknown" to active.toString())
    }

    fun sample() {
        val (kind, net) = try { current() } catch (e: Exception) { null to null }
        if (transport != null && kind != null && (kind != transport || net != network)) netSwitched = true
        if (kind != null) { transport = kind; network = net }
        var rsrp: Int? = null
        var sinr: Int? = null
        var level: Int? = null
        var type = kind
        if (kind == "mobile") {
            try {
                val strength = tm?.signalStrength
                level = strength?.level
                val nr = strength?.getCellSignalStrengths(CellSignalStrengthNr::class.java)?.firstOrNull { it.ssRsrp != CellInfo.UNAVAILABLE }
                val lte = strength?.getCellSignalStrengths(CellSignalStrengthLte::class.java)?.firstOrNull { it.rsrp != CellInfo.UNAVAILABLE }
                when {
                    nr != null -> { type = "5g"; rsrp = nr.ssRsrp; sinr = nr.ssSinr.takeIf { it != CellInfo.UNAVAILABLE } }
                    lte != null -> { type = "4g"; rsrp = lte.rsrp; sinr = lte.rssnr.takeIf { it != CellInfo.UNAVAILABLE } }
                }
            } catch (e: Exception) {                       // pas de carte SIM, service indisponible : niveaux absents
            }
            if (cellsWanted()) {
                val id = try {
                    tm?.allCellInfo?.firstOrNull { it.isRegistered }?.let { info ->
                        when (info) {
                            is CellInfoNr -> (info.cellIdentity as? android.telephony.CellIdentityNr)?.let { "nr:${it.nci}:${it.pci}" }
                            is CellInfoLte -> "lte:${info.cellIdentity.ci}:${info.cellIdentity.pci}"
                            else -> info.javaClass.simpleName + ":" + info.cellIdentity.hashCode()
                        }
                    }
                } catch (e: SecurityException) {
                    null
                } catch (e: Exception) {
                    null
                }
                if (id != null) {
                    if (cell != null && id != cell) cellChanged = true
                    cell = id
                }
            }
        }
        last = RadioSample(type, RadioSample.rsrp(rsrp), RadioSample.sinr(sinr), RadioSample.level(level), cellChanged, netSwitched)
    }

    /** Dernier relevé (affichage). */
    fun shown(): RadioSample = last.copy(cellChanged = false, netSwitched = false)

    /** Relevé pour un résumé : les faits survenus depuis le précédent, puis remis à zéro. */
    fun take(): RadioSample {
        val out = last
        cellChanged = false; netSwitched = false
        last = last.copy(cellChanged = false, netSwitched = false)
        return out
    }
}
