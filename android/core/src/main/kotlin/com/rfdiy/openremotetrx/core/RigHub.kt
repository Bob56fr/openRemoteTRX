// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.rfdiy.openremotetrx.logic.RigState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Ce que les vues (écran, notification, voiture plus tard) observent. */
data class RigUi(
    val rig: RigState = RigState(),
    val station: StationAccount? = null,
    val muted: Boolean = false,
    /** Faux : micro non autorisé, réception seule. */
    val micAllowed: Boolean = true,
)

/**
 * Point d'accès des vues à RigService, SEUL propriétaire de la connexion. Les vues observent `ui` et envoient des
 * intentions ; aucune ne garde d'état propre ni n'envoie de battement.
 */
object RigHub {
    private val _ui = MutableStateFlow(RigUi())
    val ui: StateFlow<RigUi> = _ui.asStateFlow()

    internal class Request(val account: StationAccount, val password: String, val useMic: Boolean)

    @Volatile internal var pending: Request? = null
    @Volatile internal var service: RigService? = null

    internal fun publish(update: (RigUi) -> RigUi) {
        _ui.value = update(_ui.value)
    }

    /** Connexion : démarre le service au premier plan (application visible : exigé par Android 14+ pour le micro). */
    fun connect(context: Context, account: StationAccount, password: String, useMic: Boolean) {
        pending = Request(account, password, useMic)
        ContextCompat.startForegroundService(context, Intent(context, RigService::class.java).setAction(RigService.ACTION_CONNECT))
    }

    fun toggle() { service?.onRig { session, now -> session.pressPtt(now) } }

    /** STOP : toujours transmis, armé ou non. */
    fun stop() { service?.onRig { session, now -> session.stop(now) } }

    fun setArmed(on: Boolean) { service?.onRig { session, now -> session.setArmed(now, on) } }

    fun releaseLocal() { service?.onRig { session, now -> session.releaseLocal(now) } }

    fun setFrequency(hz: Long) { service?.onRig { session, now -> session.setFrequency(now, hz) } }

    fun setMode(mode: String) { service?.onRig { session, now -> session.setMode(now, mode) } }

    fun selectBand(key: String) { service?.onRig { session, now -> session.selectBand(now, key) } }

    fun recallMemory(id: String) { service?.onRig { session, now -> session.recallMemory(now, id) } }

    fun setSquelch(value: Double) { service?.onRig { session, now -> session.setSquelch(now, value) } }

    fun setLevel(name: String, value: Double) { service?.onRig { session, now -> session.setLevel(now, name, value) } }

    fun saveMemory(name: String, hz: Long, mode: String, favorite: Boolean, id: String?) {
        service?.onRig { session, now -> session.saveMemory(now, name, hz, mode, favorite, id) }
    }

    fun deleteMemory(id: String) { service?.onRig { session, now -> session.deleteMemory(now, id) } }

    /** Bouton d'une fonction du poste (logic.Controls) ; refusé pendant l'émission. */
    fun pressControl(key: String) { service?.onRig { session, now -> session.pressControl(now, key) } }

    fun setMuted(on: Boolean) { service?.setMuted(on) ?: publish { it.copy(muted = on) } }

    fun disconnect(context: Context) {
        val s = service
        if (s != null) s.userDisconnect() else context.stopService(Intent(context, RigService::class.java))
    }
}
