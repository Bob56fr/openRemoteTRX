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
import com.rfdiy.openremotetrx.logic.Artwork
import com.rfdiy.openremotetrx.logic.Car
import com.rfdiy.openremotetrx.logic.CarAction
import com.rfdiy.openremotetrx.logic.CarIcon
import com.rfdiy.openremotetrx.logic.CarScreen
import com.rfdiy.openremotetrx.logic.FavoriteStepper
import com.rfdiy.openremotetrx.logic.LinkStatus
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
 * - Actions personnalisées (logic.Car) : PTT, STOP, cadenas « Émission autorisée » (pictogramme = état relu dans la
 *   session, F6), reprendre la main. PRENDRE l'émission n'est permis qu'à Android Auto et à l'application (appelant
 *   vérifié) ; couper est permis à tous.
 * - Pochette (F5) : image de la bande du poste (ArtworkProvider), jamais de donnée dynamique dessinée dedans.
 * - Suivant / Précédent (volant, écran) : mémoires favorites en boucle (F1), appuis regroupés (300 ms), refusé en
 *   émission ; masqués sans favori.
 * - Sous-titre : réglages actifs du poste (F3) ; texte mis à jour au plus une fois par seconde, boutons et état du
 *   lecteur (émission, cadenas) aussitôt.
 * - Parcourir : favoris, stations, mémoires, bandes (RigAutoService) ; recherche vocale : mémoire, bande, fréquence, jamais
 *   l'émission.
 */
internal object RigMedia {
    private val main = Handler(Looper.getMainLooper())
    private var session: MediaSession? = null
    private var scope: CoroutineScope? = null
    private val users = mutableSetOf<String>()
    private var lastKey = ""
    private var lastUrgent = ""
    private var lastPublishMs = 0L
    private var delayedRefresh = false
    private val stepper = FavoriteStepper(SKIP_DELAY_MS)
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
        runCatching { ArtworkProvider.userDir(app) }                   // crée le dossier des pochettes, visible depuis le PC
        if (session != null) {
            refresh(force = true)
            return
        }
        val s = MediaSession(app, "openRemoteTRX")
        s.setCallback(Callback(), main)
        session = s
        scope = CoroutineScope(SupervisorJob() + ContextCompat.getMainExecutor(app).asCoroutineDispatcher()).also { sc ->
            sc.launch { RigHub.ui.collect { refresh() } }
            sc.launch { VoiceHub.ui.collect { refresh() } }              // EQ du sous-titre
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
        lastUrgent = ""
        stepper.cancel()
    }

    fun has(user: String) = user in users

    private fun buttonsPtt(): Boolean =
        USER_BUTTONS in users && app.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).getBoolean(RigHub.PREF_MEDIA_PTT, false)

    private fun screen(): CarScreen {
        val ui = RigHub.ui.value
        val voice = VoiceHub.ui.value
        return Car.screen(
            ui.rig, ui.station?.name, ui.muted, ui.micAllowed, ui.carNotice,
            eq = voice.settings.enabled && !voice.breizh, preview = stepper.pending, selcallOpen = ui.rig.selcall?.state == "open",
        )
    }

    /**
     * Titre, sous-titre, état du lecteur et boutons, seulement s'ils ont changé. Boutons, état du lecteur et pochette :
     * aussitôt (sécurité : l'émission se voit tout de suite) ; texte seul : au plus une fois par seconde (F3, règles de
     * Google contre le scintillement).
     */
    fun refresh(force: Boolean = false) {
        val s = session ?: return
        val ui = RigHub.ui.value
        val sc = screen()
        val ptt = buttonsPtt()
        val art = Artwork.key(ui.rig.status == LinkStatus.CONNECTED, ui.rig.state?.rig?.frequencyHz)
        val key = "$sc|$ptt|$art"
        val urgent = "${sc.buttons}|${sc.playing}|${sc.connected}|${sc.connecting}|${sc.canSkip}|${sc.error}|$ptt|$art|" +
            "${ui.rig.ptt?.transmitting}|${stepper.pending?.id}"
        val now = android.os.SystemClock.elapsedRealtime()
        if (key != lastKey && urgent == lastUrgent && !force && now - lastPublishMs < TEXT_PERIOD_MS) {
            if (!delayedRefresh) {
                delayedRefresh = true
                main.postDelayed({ delayedRefresh = false; refresh() }, TEXT_PERIOD_MS - (now - lastPublishMs))
            }
        } else if (key != lastKey || force) {
            lastKey = key
            lastUrgent = urgent
            lastPublishMs = now
            val artUri = ArtworkProvider.uri(app, art).toString()
            s.setMetadata(
                MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_ALBUM_ART_URI, artUri)
                    .putString(MediaMetadata.METADATA_KEY_DISPLAY_ICON_URI, artUri)
                    .putString(MediaMetadata.METADATA_KEY_TITLE, sc.title)
                    .putString(MediaMetadata.METADATA_KEY_DISPLAY_TITLE, sc.title)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, sc.subtitle)
                    .putString(MediaMetadata.METADATA_KEY_DISPLAY_SUBTITLE, sc.subtitle)
                    .putString(MediaMetadata.METADATA_KEY_ALBUM, sc.secondary)
                    .putString(MediaMetadata.METADATA_KEY_DISPLAY_DESCRIPTION, sc.secondary)
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
        // Mémoires : boutons à nous (placés à droite), pas les Suivant / Précédent standard ; les touches du volant arrivent
        // quand même (onMediaButtonEvent).
        val b = PlaybackState.Builder()
            .setActions(
                PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_STOP or
                    PlaybackState.ACTION_PLAY_FROM_MEDIA_ID or PlaybackState.ACTION_PLAY_FROM_SEARCH,
            )
            .setState(state, PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f)
        if (state == PlaybackState.STATE_ERROR) b.setErrorMessage(sc.error)
        for (button in sc.buttons) {
            b.addCustomAction(PlaybackState.CustomAction.Builder(button.action.id, button.label, icon(button.icon)).build())
        }
        return b.build()
    }

    private fun icon(icon: CarIcon): Int = when (icon) {
        CarIcon.PTT -> R.drawable.ic_car_ptt
        CarIcon.STOP -> R.drawable.ic_car_stop
        CarIcon.HAND -> R.drawable.ic_car_hand
        CarIcon.LOCK_CLOSED -> R.drawable.ic_car_lock_closed
        CarIcon.LOCK_OPEN -> R.drawable.ic_car_lock_open
        CarIcon.LOCK_TX -> R.drawable.ic_car_lock_tx
        CarIcon.LOCK_UNKNOWN -> R.drawable.ic_car_lock_unknown
        CarIcon.MEM_PREV -> R.drawable.ic_car_mem_prev
        CarIcon.MEM_NEXT -> R.drawable.ic_car_mem_next
    }

    /**
     * Suivant / Précédent (F1). Hors liaison : rien, sans erreur. En émission (la sienne ou une autre) : refusé, rien
     * n'attend. Sinon le favori choisi s'affiche en titre et part vers la station 300 ms après le dernier appui.
     */
    private fun skip(forward: Boolean) {
        val rig = RigHub.ui.value.rig
        if (rig.status != LinkStatus.CONNECTED || rig.listener) return
        if (rig.ptt?.transmitting == true) {
            stepper.cancel()
            note("Changement refusé : émission en cours")
            return
        }
        val r = rig.state?.rig
        val current = Car.memoryAt(rig.memories, r?.frequencyHz, r?.mode)
        stepper.press(android.os.SystemClock.elapsedRealtime(), forward, rig.memories, current, r?.frequencyHz) ?: return
        refresh(force = true)
        main.removeCallbacks(sendFavorite)
        main.postDelayed(sendFavorite, SKIP_DELAY_MS)
    }

    private val sendFavorite: Runnable = object : Runnable {
        override fun run() {
            val now = android.os.SystemClock.elapsedRealtime()
            val wait = stepper.remainingMs(now) ?: return
            if (wait > 0) { main.postDelayed(this, wait); return }    // minuterie sortie trop tôt : réarmée
            val m = stepper.take(now) ?: return
            val rig = RigHub.ui.value.rig
            when {
                rig.status != LinkStatus.CONNECTED -> Unit
                rig.ptt?.transmitting == true -> note("Changement refusé : émission en cours")
                else -> RigHub.recallMemory(m.id)
            }
            refresh(force = true)
        }
    }

    /** Touche d'un événement média À L'APPUI seulement (le relâchement est consommé sans effet), -1 sinon. */
    private fun mediaKey(intent: Intent): Int {
        val event = if (android.os.Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, android.view.KeyEvent::class.java)
        } else {
            @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
        } ?: return -1
        val code = event.keyCode
        if (code != android.view.KeyEvent.KEYCODE_MEDIA_NEXT && code != android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS) return -1
        return if (event.action == android.view.KeyEvent.ACTION_DOWN && event.repeatCount == 0) code else 0
    }

    private const val SKIP_DELAY_MS = 300L
    private const val TEXT_PERIOD_MS = 1000L

    /** Cadenas sans effet : pourquoi. */
    private fun lockInfo(): String {
        val rig = RigHub.ui.value.rig
        return when {
            rig.status != LinkStatus.CONNECTED -> "Voiture : état d'émission inconnu (station non connectée)."
            rig.ptt?.let { it.mine && it.transmitting } == true -> "Voiture : en émission ; FIN D'ÉMISSION par le bouton micro, ou STOP."
            else -> "Voiture : réception seule, l'émission est impossible depuis ce téléphone."
        }
    }

    /** Paquet de l'application qui envoie la commande en cours (null si Android ne le dit pas). */
    private fun caller(): String? = runCatching { session?.currentControllerInfo?.packageName }.getOrNull()

    private fun note(text: String, warn: Boolean = true) {
        RigHub.service?.onRig { s, now -> s.note(now, text, warn) }
    }

    private class Callback : MediaSession.Callback() {
        override fun onMediaButtonEvent(intent: Intent): Boolean {
            when (mediaKey(intent)) {                                      // volant : mémoires favorites (F1)
                android.view.KeyEvent.KEYCODE_MEDIA_NEXT -> return true.also { skip(forward = true) }
                android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS -> return true.also { skip(forward = false) }
                0 -> return true                                           // relâchement : déjà traité à l'appui
            }
            if (buttonsPtt()) {
                RigHub.service?.let { if (it.mediaButton(intent)) return true }
            }
            return super.onMediaButtonEvent(intent)                 // Lecture/Pause -> réception audible ou muette
        }

        override fun onSkipToNext() = skip(forward = true)

        override fun onSkipToPrevious() = skip(forward = false)

        override fun onPlay() {
            RigHub.service?.regainAudio()                              // son repris à une autre source (voiture, appel)
            RigHub.setMuted(false)
        }

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
                CarAction.LOCK_INFO -> note(lockInfo(), warn = false)
                CarAction.MEM_PREV -> skip(forward = false)
                CarAction.MEM_NEXT -> skip(forward = true)
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
