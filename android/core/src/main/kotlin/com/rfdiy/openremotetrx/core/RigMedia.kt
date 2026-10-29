// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.content.Intent
import android.media.MediaMetadata
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import com.rfdiy.openremotetrx.logic.Car
import com.rfdiy.openremotetrx.logic.CarAction
import com.rfdiy.openremotetrx.logic.CarScreen
import com.rfdiy.openremotetrx.logic.Voice
import com.rfdiy.openremotetrx.logic.VoiceAction
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * LA session média de l'application (une seule : deux sessions se disputeraient les touches). Ouverte tant qu'un
 * utilisateur en a besoin : la voiture (RigAutoService, lot A2) ou le PTT par le bouton du casque (RigService).
 * Fil principal uniquement.
 *
 * - Lecture / Pause (écran de la voiture, touches du volant si le PTT au volant est désactivé) : réception audible ou
 *   muette. Arrêt : STOP de l'émission (ne fait que couper).
 * - Touches du volant ou du casque avec le réglage « PTT par le bouton » : PTT toggle (RigService.onMediaKey).
 * - Actions personnalisées (logic.Car) : PTT, STOP, autoriser l'émission, reprendre la main. PRENDRE l'émission
 *   n'est permis qu'à Android Auto et à l'application (appelant vérifié) ; couper est permis à tous.
 * - Parcourir : stations, mémoires, bandes (RigAutoService) ; recherche vocale : mémoire, bande, fréquence, jamais
 *   l'émission.
 */
internal object RigMedia {
    private val main = Handler(Looper.getMainLooper())
    private var session: MediaSession? = null
    private var scope: CoroutineScope? = null
    private val users = mutableSetOf<String>()
    private var lastKey = ""
    private var lastMemories: List<String> = emptyList()
    private var lastStatus: Any? = null
    /** Appelé quand la liste des mémoires ou l'état de la liaison change (la voiture relit Parcourir). */
    var onBrowseChanged: (() -> Unit)? = null
    private lateinit var app: Context

    const val USER_CAR = "car"
    const val USER_BUTTONS = "buttons"

    val token: MediaSession.Token? get() = session?.sessionToken

    fun acquire(context: Context, user: String) {
        app = context.applicationContext
        users += user
        if (session != null) {
            refresh(force = true)
            return
        }
        val s = MediaSession(app, "openRemoteTRX")
        s.setCallback(Callback(), main)
        session = s
        scope = CoroutineScope(SupervisorJob() + ContextCompat.getMainExecutor(app).asCoroutineDispatcher()).also { sc ->
            sc.launch { RigHub.ui.collect { refresh() } }
        }
        refresh(force = true)
        s.isActive = true
    }

    fun release(user: String) {
        users -= user
        if (users.isNotEmpty()) {
            refresh(force = true)
            return
        }
        scope?.cancel()
        scope = null
        session?.let { runCatching { it.isActive = false; it.release() } }
        session = null
        lastKey = ""
    }

    fun has(user: String) = user in users

    private fun buttonsPtt(): Boolean =
        USER_BUTTONS in users && app.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).getBoolean(RigHub.PREF_MEDIA_PTT, false)

    private fun screen(): CarScreen {
        val ui = RigHub.ui.value
        return Car.screen(ui.rig, ui.station?.name, ui.muted, ui.micAllowed, ui.carNotice)
    }

    /** Titre, sous-titre, état du lecteur et boutons, seulement s'ils ont changé. */
    fun refresh(force: Boolean = false) {
        val s = session ?: return
        val ui = RigHub.ui.value
        val sc = screen()
        val ptt = buttonsPtt()
        val key = "$sc|$ptt"
        if (key != lastKey || force) {
            lastKey = key
            s.setMetadata(
                MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_TITLE, sc.title)
                    .putString(MediaMetadata.METADATA_KEY_DISPLAY_TITLE, sc.title)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, sc.subtitle)
                    .putString(MediaMetadata.METADATA_KEY_DISPLAY_SUBTITLE, sc.subtitle)
                    .putLong(MediaMetadata.METADATA_KEY_DURATION, -1)
                    .build(),
            )
            s.setPlaybackState(playback(sc, ptt))
        }
        val memories = ui.rig.memories.map { "${it.id}|${it.name}" }
        if (memories != lastMemories || ui.rig.status != lastStatus) {
            lastMemories = memories
            lastStatus = ui.rig.status
            onBrowseChanged?.invoke()
        }
    }

    private fun playback(sc: CarScreen, ptt: Boolean): PlaybackState {
        // PTT par les touches : toujours « en lecture » (Android donne les touches à la session qui joue ; essai du 2026-10-29)
        val state = when {
            sc.error.isNotEmpty() && !sc.connected -> PlaybackState.STATE_ERROR
            sc.connecting -> PlaybackState.STATE_CONNECTING
            !sc.connected -> if (ptt) PlaybackState.STATE_PLAYING else PlaybackState.STATE_STOPPED
            sc.playing || ptt -> PlaybackState.STATE_PLAYING
            else -> PlaybackState.STATE_PAUSED
        }
        val b = PlaybackState.Builder()
            .setActions(
                PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_STOP or
                    PlaybackState.ACTION_PLAY_FROM_MEDIA_ID or PlaybackState.ACTION_PLAY_FROM_SEARCH,
            )
            .setState(state, PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f)
        if (state == PlaybackState.STATE_ERROR) b.setErrorMessage(sc.error)
        for (button in sc.buttons) {
            b.addCustomAction(PlaybackState.CustomAction.Builder(button.action.id, button.label, icon(button.action)).build())
        }
        return b.build()
    }

    private fun icon(action: CarAction): Int = when (action) {
        CarAction.PTT -> R.drawable.ic_car_ptt
        CarAction.STOP -> R.drawable.ic_car_stop
        CarAction.ARM, CarAction.DISARM -> R.drawable.ic_car_arm
        CarAction.RELEASE_LOCAL -> R.drawable.ic_car_hand
    }

    /** Paquet de l'application qui envoie la commande en cours (null si Android ne le dit pas). */
    private fun caller(): String? = runCatching { session?.currentControllerInfo?.packageName }.getOrNull()

    private fun note(text: String, warn: Boolean = true) {
        RigHub.service?.onRig { s, now -> s.note(now, text, warn) }
    }

    private class Callback : MediaSession.Callback() {
        override fun onMediaButtonEvent(intent: Intent): Boolean {
            if (buttonsPtt()) {
                RigHub.service?.let { if (it.mediaButton(intent)) return true }
            }
            return super.onMediaButtonEvent(intent)                 // Lecture/Pause -> réception audible ou muette
        }

        override fun onPlay() = RigHub.setMuted(false)

        override fun onPause() = RigHub.setMuted(true)

        override fun onStop() {
            val ptt = RigHub.ui.value.rig.ptt
            if (ptt?.transmitting == true) RigHub.stop()             // ne fait que couper
        }

        override fun onCustomAction(action: String, extras: Bundle?) {
            val a = CarAction.of(action) ?: return
            val who = caller()
            val mine = RigHub.ui.value.rig.ptt?.mine == true
            if (!Car.allowed(a, who, mine)) {
                note("Voiture : « ${a.id} » refusé (demandé par ${who ?: "une application inconnue"}).")
                return
            }
            when (a) {
                CarAction.PTT -> RigHub.toggle()
                CarAction.STOP -> RigHub.stop()
                CarAction.ARM -> RigHub.setArmed(true)
                CarAction.DISARM -> RigHub.setArmed(false)
                CarAction.RELEASE_LOCAL -> RigHub.releaseLocal()
            }
        }

        override fun onPlayFromMediaId(mediaId: String, extras: Bundle?) {
            val (kind, value) = mediaId.split(":", limit = 2).let { it[0] to it.getOrElse(1) { "" } }
            when (kind) {
                RigAutoService.STATION -> RigHub.connectFromCar(app, value)
                RigAutoService.MEMORY -> RigHub.recallMemory(value)
                RigAutoService.BAND -> RigHub.selectBand(value)
                RigAutoService.DISCONNECT -> RigHub.disconnect(app)
            }
        }

        override fun onPlayFromSearch(query: String?, extras: Bundle?) {
            when (val v = Voice.parse(query, RigHub.ui.value.rig.memories)) {
                VoiceAction.Listen -> RigHub.setMuted(false)
                is VoiceAction.RecallMemory -> RigHub.recallMemory(v.memory.id)
                is VoiceAction.SelectBand -> RigHub.selectBand(v.key)
                is VoiceAction.SetFrequency -> RigHub.setFrequency(v.hz)
                is VoiceAction.Unknown -> note("Voiture : « ${v.text} » non compris (mémoire, bande ou fréquence).")
            }
        }
    }

    /** Démarre le service au premier plan depuis la voiture ; faux si Android le refuse (application en arrière-plan). */
    fun startService(context: Context, intent: Intent): Boolean = try {
        ContextCompat.startForegroundService(context, intent)
        true
    } catch (e: IllegalStateException) {                             // ForegroundServiceStartNotAllowedException (Android 12+)
        false
    } catch (e: SecurityException) {
        false
    }
}
