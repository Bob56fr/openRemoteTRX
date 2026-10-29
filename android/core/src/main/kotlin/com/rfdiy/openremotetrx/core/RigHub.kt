// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.rfdiy.openremotetrx.logic.RigState
import com.rfdiy.openremotetrx.protocol.SpectrumFrame
import kotlinx.serialization.json.JsonPrimitive
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
    /** Micro du casque Bluetooth : état lisible (vide si le réglage est désactivé). */
    val headsetMic: String = "",
)

/**
 * Point d'accès des vues à RigService, SEUL propriétaire de la connexion. Les vues observent `ui` et envoient des
 * intentions ; aucune ne garde d'état propre ni n'envoie de battement.
 */
object RigHub {
    private val _ui = MutableStateFlow(RigUi())
    val ui: StateFlow<RigUi> = _ui.asStateFlow()

    // Spectre HF : flux à part (jusqu'à 25 balayages par seconde) pour ne pas redessiner tout l'écran à chaque trame.
    private val _spectrum = MutableStateFlow<SpectrumFrame?>(null)
    val spectrum: StateFlow<SpectrumFrame?> = _spectrum.asStateFlow()
    @Volatile private var lastSeq: Long? = null

    /** Trame reçue (fil de WebRTC) : illisible ou plus ancienne que la dernière = jetée (canal non ordonné). */
    internal fun offerSpectrum(bytes: ByteArray) {
        val frame = SpectrumFrame.parse(bytes) ?: return
        if (!SpectrumFrame.newer(frame.seq, lastSeq)) return
        lastSeq = frame.seq
        _spectrum.value = frame
    }

    /** Nouvelle connexion : la station peut avoir redémarré et renuméroter ses balayages depuis 0 (page : idem). */
    internal fun resetSpectrum() {
        lastSeq = null
        _spectrum.value = null
    }

    /** Waterfall audio affiché : prise du son reçu ; `null` à la fermeture (aucun calcul quand il est caché). */
    fun startAudioTap(): AudioTap = AudioTap().also { tap -> service?.setAudioSink(tap) }

    fun stopAudioTap() { service?.setAudioSink(null) }

    /** Vue du spectre ouverte ou fermée : la station n'envoie les balayages qu'aux clients qui regardent. */
    fun watchSpectrum(on: Boolean) {
        if (!on) { _spectrum.value = null; lastSeq = null }
        service?.onRig { session, now -> session.watchSpectrum(now, on) }
    }

    /** Réglage du spectre DU POSTE (mode, span, ref, speed) ; refusé par la station hors réception. */
    fun spectrumSet(name: String, value: String) = spectrumSet(name, JsonPrimitive(value))

    fun spectrumSet(name: String, value: Number) = spectrumSet(name, JsonPrimitive(value))

    private fun spectrumSet(name: String, value: JsonPrimitive) { service?.onRig { session, now -> session.spectrumSet(now, name, value) } }

    /** Réglages du téléphone lus par le service (fichier de préférences de l'application). */
    const val PREFS = "ui"
    const val PREF_MEDIA_PTT = "media_ptt"
    const val PREF_HEADSET_MIC = "headset_mic"
    const val PREF_MIC_PROFILE = "mic_profile"
    const val PREF_MIC_ECHO = "mic_echo"
    const val PREF_MIC_NOISE = "mic_noise"

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

    /**
     * Application quittée (autre application, écran verrouillé) : si CE téléphone émet et que l'utilisateur n'a pas
     * choisi de rester en émission, retour en réception (STOP), noté au journal.
     */
    fun leaving(keepTransmitting: Boolean) {
        val ptt = _ui.value.rig.ptt ?: return
        if (keepTransmitting || !(ptt.mine && ptt.transmitting)) return
        service?.onRig { session, now -> session.stop(now, "Application quittée pendant l'émission : retour en réception.") }
    }

    fun setArmed(on: Boolean) { service?.onRig { session, now -> session.setArmed(now, on) } }

    fun releaseLocal() { service?.onRig { session, now -> session.releaseLocal(now) } }

    fun setFrequency(hz: Long) { service?.onRig { session, now -> session.setFrequency(now, hz) } }

    fun setMode(mode: String) { service?.onRig { session, now -> session.setMode(now, mode) } }

    fun selectBand(key: String) { service?.onRig { session, now -> session.selectBand(now, key) } }

    fun recallMemory(id: String) { service?.onRig { session, now -> session.recallMemory(now, id) } }

    /** QSY sur un spot du Cluster DX (mode adapté au poste, puis fréquence). */
    fun qsySpot(id: Long) { service?.onRig { session, now -> session.qsySpot(now, id) } }

    fun setSquelch(value: Double) { service?.onRig { session, now -> session.setSquelch(now, value) } }

    fun setOffset(name: String, hz: Int) { service?.onRig { session, now -> session.setOffset(now, name, hz) } }

    fun setLevel(name: String, value: Double) { service?.onRig { session, now -> session.setLevel(now, name, value) } }

    fun saveMemory(name: String, hz: Long, mode: String, favorite: Boolean, id: String?) {
        service?.onRig { session, now -> session.saveMemory(now, name, hz, mode, favorite, id) }
    }

    fun deleteMemory(id: String) { service?.onRig { session, now -> session.deleteMemory(now, id) } }

    /** Bouton d'une fonction du poste (logic.Controls) ; refusé pendant l'émission. */
    fun pressControl(key: String) { service?.onRig { session, now -> session.pressControl(now, key) } }

    /** Bips de fin (réglage commun de la station). */
    fun setBeep(name: String, value: Boolean) = setBeep(name, JsonPrimitive(value))

    fun setBeep(name: String, value: String) = setBeep(name, JsonPrimitive(value))

    fun setBeep(name: String, value: Int) = setBeep(name, JsonPrimitive(value))

    private fun setBeep(name: String, value: JsonPrimitive) { service?.onRig { session, now -> session.setBeeps(now, mapOf(name to value)) } }

    /** Réglage « PTT par le bouton du casque ou du volant » changé : session média ouverte ou fermée tout de suite. */
    fun mediaButtonsChanged() { service?.refreshMediaSession() }

    /** SELCALL de la station : armer sur un code, réarmer, désactiver, filtrage des tonalités. */
    fun selcallActivate(code: String) { service?.onRig { session, now -> session.selcallActivate(now, code) } }

    fun selcallRearm() { service?.onRig { session, now -> session.selcallRearm(now) } }

    fun selcallDeactivate() { service?.onRig { session, now -> session.selcallDeactivate(now) } }

    fun selcallOptions(filterMode: String? = null, attenuationDb: Int? = null, sendOnTxEnd: Boolean? = null, txLevelDbfs: Double? = null) {
        service?.onRig { session, now -> session.selcallOptions(now, filterMode, attenuationDb, sendOnTxEnd, txLevelDbfs) }
    }

    /** Réglage automatique du niveau de la trame d'après l'ALC : une émission (annuler = stop). */
    fun selcallCalibrate() { service?.onRig { session, now -> session.selcallCalibrate(now) } }

    /** Appel SELCALL manuel : une émission (annuler = stop). */
    fun selcallSend() { service?.onRig { session, now -> session.selcallSend(now) } }

    fun setMuted(on: Boolean) { service?.setMuted(on) ?: publish { it.copy(muted = on) } }

    fun disconnect(context: Context) {
        val s = service
        if (s != null) s.userDisconnect() else context.stopService(Intent(context, RigService::class.java))
    }
}
