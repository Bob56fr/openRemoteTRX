// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import android.view.KeyEvent
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.LinkAlert
import com.rfdiy.openremotetrx.logic.LinkStatus
import com.rfdiy.openremotetrx.logic.MediaAction
import com.rfdiy.openremotetrx.logic.MediaKey
import com.rfdiy.openremotetrx.logic.MediaKeys
import com.rfdiy.openremotetrx.logic.RigSession
import com.rfdiy.openremotetrx.logic.RigState
import com.rfdiy.openremotetrx.logic.SessionLink
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Service au premier plan, SEUL propriétaire de la connexion avec la station (CLAUDE.md, « Client Android »).
 * Tout ce qui touche la session passe par UN fil (« rig ») : messages, minuterie de 400 ms, actions des vues.
 *
 * Garde la réception écran éteint (verrous de veille et Wi-Fi), affiche une notification permanente avec STOP,
 * et applique E5 : perte du focus audio (appel) pendant SON émission => STOP.
 *
 * Réglage « PTT par le bouton du casque ou du volant » (désactivé par défaut) : session média Android qui reçoit
 * Lecture/Pause d'un casque filaire ou Bluetooth et des touches du volant (logic.MediaKeys). Réglage « micro du
 * casque Bluetooth » : appareil de communication choisi pour toute la connexion (son en qualité téléphone).
 */
class RigService : Service() {
    private val executor = Executors.newSingleThreadExecutor { r -> Thread(r, "rig") }
    private val scope = CoroutineScope(SupervisorJob() + executor.asCoroutineDispatcher())
    private lateinit var rtc: RtcLink
    private lateinit var session: RigSession
    private lateinit var sounds: LinkSounds
    private var request: RigHub.Request? = null
    private var attempt: Job? = null
    private var ticker: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var focus: AudioFocusRequest? = null
    private var userMuted = false
    private var focusLost = false
    private var wasMine = false
    private var lastNotification = ""
    private var foreground = false
    private var media: MediaSession? = null                       // fil principal
    private var mediaMine = false
    private var deviceAddedAt: Long? = null                       // fil « rig »
    private var lastMediaKeyAt: Long? = null
    private var headsetMic = false
    private val devices = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>?) {
            executor.execute { deviceAddedAt = now() }             // casque ou voiture arrivé : « lecture » automatique ignorée
        }
    }

    private fun now(): Long = SystemClock.elapsedRealtime()

    /** Exécute sur le fil de la session. */
    internal fun onRig(block: (RigSession, Long) -> Unit) {
        executor.execute { block(session, now()) }
    }

    override fun onCreate() {
        super.onCreate()
        sounds = LinkSounds(this)
        headsetMic = getSharedPreferences(RigHub.PREFS, MODE_PRIVATE).getBoolean(RigHub.PREF_HEADSET_MIC, false)
        rtc = RtcLink(
            this,
            post = { block -> runCatching { executor.execute(block) } },
            onMessage = { text -> session.onMessage(now(), text) },
            onClosed = { code -> session.onLinkClosed(now(), code) },
            onSpectrum = { bytes -> RigHub.offerSpectrum(bytes) },
            voiceCall = headsetMic,
        )
        session = RigSession(object : SessionLink {
            override fun startAttempt() = launchAttempt()
            override fun send(text: String): Boolean = rtc.send(text)
            override fun setMicOpen(open: Boolean) = rtc.setMicOpen(open)
            override fun close() {
                attempt?.cancel()
                attempt = null
                rtc.close()
            }
            override fun alert(kind: LinkAlert) = sounds.play(kind)
        })
        session.onChange = { state -> onState(state) }
        session.onBandSpots = { spots -> request?.let { BandStore(this).save(it.account.id, spots) } }
        RigHub.service = this
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> {
                val req = RigHub.pending
                RigHub.pending = null
                if (req == null) {
                    if (!foreground) stopSelf()
                    return START_NOT_STICKY
                }
                goForeground(req)
                executor.execute {
                    request = req
                    RigHub.publish { it.copy(station = req.account, micAllowed = req.useMic) }
                    applyMute()
                    session.begin(now(), req.account.reconnectWindowS, BandStore(this).load(req.account.id))
                    startTicker()
                }
            }
            ACTION_STOP -> onRig { s, t -> s.stop(t) }
            ACTION_DISCONNECT -> userDisconnect()
            else -> if (!foreground) stopSelf()
        }
        return START_NOT_STICKY                                   // jamais relancé seul par Android : RX par défaut
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /** Application retirée des récentes : on se déconnecte proprement (la station couperait de toute façon). */
    override fun onTaskRemoved(rootIntent: Intent?) {
        userDisconnect()
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        RigHub.service = null
        releaseMedia()
        runCatching {
            executor.submit {
                session.onChange = null
                session.disconnect(now())
                rtc.release()
            }.get(2, TimeUnit.SECONDS)
        }
        scope.cancel()
        executor.shutdown()
        releaseLocks()
        abandonFocus()
        RigHub.publish { it.copy(rig = it.rig.copy(status = LinkStatus.DISCONNECTED, ptt = null, state = null, armed = false)) }
        super.onDestroy()
    }

    internal fun userDisconnect() {
        executor.execute {
            session.disconnect(now())
            request = null
            finish()
        }
    }

    internal fun setAudioSink(sink: AudioTap?) {
        executor.execute { rtc.setAudioSink(sink?.sink) }
    }

    internal fun setMuted(on: Boolean) {
        executor.execute {
            userMuted = on
            applyMute()
        }
    }

    // ------------------------------------------------------------------ connexion

    private fun launchAttempt() {
        val req = request ?: return
        attempt?.cancel()
        RigHub.resetSpectrum()
        attempt = scope.launch {
            try {
                rtc.open(req.account, req.password, req.useMic)
                session.answered(now())
            } catch (e: AttemptException) {
                session.attemptFailed(now(), e.code, e.detail)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                session.attemptFailed(now(), "client_error", e.message ?: "")
            }
        }
    }

    private fun startTicker() {
        if (ticker?.isActive == true) return
        ticker = scope.launch {
            while (isActive) {
                session.tick(now(), online())
                delay(com.rfdiy.openremotetrx.protocol.Protocol.HEARTBEAT_TICK_MS)
            }
        }
    }

    private fun online(): Boolean {
        val cm = getSystemService(ConnectivityManager::class.java) ?: return true
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /** Sur le fil « rig » : publie l'état, bips d'émission, notification ; fin du service si déconnecté. */
    private fun onState(state: RigState) {
        RigHub.publish { it.copy(rig = state) }
        val mine = state.ptt?.let { it.mine && it.transmitting } ?: false
        if (mine != wasMine) sounds.txBeep(mine)
        wasMine = mine
        val owned = state.ptt?.mine == true
        if (owned != mediaMine) {
            mediaMine = owned
            media?.setPlaybackState(playback(owned))
        }
        updateNotification(state)
        if (state.status == LinkStatus.DISCONNECTED && request != null && attempt?.isActive != true) {
            request = null                                         // abandon : plus rien à garder au premier plan
            finish()
        }
    }

    private fun finish() {
        ticker?.cancel()
        ticker = null
        releaseLocks()
        abandonFocus()
        releaseHeadsetMic()
        runCatching { getSystemService(AudioManager::class.java)?.unregisterAudioDeviceCallback(devices) }
        Handler(mainLooper).post { releaseMedia() }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        foreground = false
        stopSelf()
    }

    // ------------------------------------------------------------------ premier plan, veille, focus audio

    private fun goForeground(req: RigHub.Request) {
        var types = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        if (req.useMic && Build.VERSION.SDK_INT >= 30) types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(req.account.name, "Connexion…", "", false), types)
        foreground = true
        acquireLocks()
        requestFocus()
        getSystemService(AudioManager::class.java)?.registerAudioDeviceCallback(devices, Handler(mainLooper))
        refreshMediaSession()
        if (headsetMic) useHeadsetMic()
    }

    // ------------------------------------------------------------------ casque et volant

    /** Ouvre ou ferme la session média selon le réglage (fil principal). Fermée : les touches restent aux autres applications. */
    internal fun refreshMediaSession() {
        Handler(mainLooper).post {
            val want = foreground && getSharedPreferences(RigHub.PREFS, MODE_PRIVATE).getBoolean(RigHub.PREF_MEDIA_PTT, false)
            if (want && media == null) {
                media = MediaSession(this, "openRemoteTRX").apply {
                    setCallback(object : MediaSession.Callback() {
                        override fun onMediaButtonEvent(intent: Intent): Boolean {
                            val event = keyEvent(intent) ?: return false
                            val key = keyOf(event.keyCode)
                            if (key == MediaKey.OTHER) return false
                            if (event.action == KeyEvent.ACTION_DOWN) executor.execute { onMediaKey(key, event.repeatCount) }
                            return true                         // appui et relâchement consommés : rien d'autre ne démarre
                        }
                    }, Handler(mainLooper))
                    setPlaybackState(playback(mediaMine))
                    isActive = true
                }
            } else if (!want) {
                releaseMedia()
            }
        }
    }

    private fun releaseMedia() {
        media?.let { runCatching { it.isActive = false; it.release() } }
        media = null
    }

    /** « En lecture » pendant SON émission : un casque envoie alors « pause » (fin), sinon « lecture » (prise). */
    private fun playback(mine: Boolean): PlaybackState = PlaybackState.Builder()
        .setActions(PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_STOP)
        .setState(if (mine) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED, PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f)
        .build()

    private fun keyEvent(intent: Intent): KeyEvent? =
        if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
        }

    private fun keyOf(code: Int): MediaKey = when (code) {
        KeyEvent.KEYCODE_HEADSETHOOK, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> MediaKey.TOGGLE
        KeyEvent.KEYCODE_MEDIA_PLAY -> MediaKey.PLAY
        KeyEvent.KEYCODE_MEDIA_PAUSE -> MediaKey.PAUSE
        KeyEvent.KEYCODE_MEDIA_STOP -> MediaKey.STOP
        else -> MediaKey.OTHER
    }

    /** Sur le fil « rig » : même chemin que le bouton PTT de l'écran (« Émission autorisée » exigée). */
    private fun onMediaKey(key: MediaKey, repeat: Int) {
        val t = now()
        val snap = session.snapshot
        val mine = snap.ptt?.mine == true
        val action = MediaKeys.decide(key, repeat, mine, deviceAddedAt?.let { t - it }, lastMediaKeyAt?.let { t - it })
        if (action != MediaAction.TOGGLE) return
        lastMediaKeyAt = t
        if (!mine && (!snap.armed || request?.useMic != true || snap.ptt?.transmitting == true)) {
            sounds.refused()                                       // refus audible : l'écran n'est peut-être pas visible
        }
        session.pressPtt(t)                                        // journal : motif du refus éventuel
    }

    /** Micro du casque Bluetooth (Android 12+) : appareil de communication pour toute la connexion. */
    private fun useHeadsetMic() {
        val am = getSystemService(AudioManager::class.java) ?: return
        val text = if (Build.VERSION.SDK_INT < 31) {
            "micro du casque Bluetooth : Android 12 ou plus récent requis (micro du téléphone)"
        } else {
            val device = am.availableCommunicationDevices.firstOrNull {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || it.type == AudioDeviceInfo.TYPE_BLE_HEADSET
            }
            if (device == null) {
                "aucun casque Bluetooth connecté : micro du téléphone"
            } else {
                am.mode = AudioManager.MODE_IN_COMMUNICATION
                if (am.setCommunicationDevice(device)) "micro du casque : ${device.productName}" else "casque Bluetooth refusé par Android : micro du téléphone"
            }
        }
        RigHub.publish { it.copy(headsetMic = text) }
    }

    private fun releaseHeadsetMic() {
        if (!headsetMic) return
        val am = getSystemService(AudioManager::class.java) ?: return
        runCatching {
            if (Build.VERSION.SDK_INT >= 31) am.clearCommunicationDevice()
            am.mode = AudioManager.MODE_NORMAL
        }
        RigHub.publish { it.copy(headsetMic = "") }
    }

    private fun acquireLocks() {
        if (wakeLock == null) {
            // Sans limite de durée : l'écoute écran éteint dure toute la connexion ; relâché par finish().
            wakeLock = getSystemService(PowerManager::class.java)
                ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "openRemoteTRX:rig")
                ?.apply { setReferenceCounted(false); acquire() }
        }
        if (wifiLock == null) {
            wifiLock = applicationContext.getSystemService(WifiManager::class.java)
                ?.createWifiLock(WifiManager.WIFI_MODE_FULL_LOW_LATENCY, "openRemoteTRX:rig")
                ?.apply { setReferenceCounted(false); acquire() }
        }
    }

    private fun releaseLocks() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
    }

    private fun requestFocus() {
        if (focus != null) return
        val am = getSystemService(AudioManager::class.java) ?: return
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setWillPauseWhenDucked(false)
            .setOnAudioFocusChangeListener { change -> executor.execute { onFocus(change) } }
            .build()
        focus = req
        am.requestAudioFocus(req)
    }

    private fun abandonFocus() {
        val req = focus ?: return
        getSystemService(AudioManager::class.java)?.abandonAudioFocusRequest(req)
        focus = null
    }

    /** E5 : focus perdu (appel entrant, autre application) pendant SON émission => STOP ; réception muette. */
    private fun onFocus(change: Int) {
        when (change) {
            AudioManager.AUDIOFOCUS_LOSS, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> {
                focusLost = true
                if (session.snapshot.ptt?.let { it.mine && it.transmitting } == true) session.stop(now())
                applyMute()
            }
            AudioManager.AUDIOFOCUS_GAIN -> {
                focusLost = false
                applyMute()
            }
        }
    }

    private fun applyMute() {
        val muted = userMuted || focusLost
        rtc.setMuted(muted)
        RigHub.publish { it.copy(muted = userMuted) }
    }

    // ------------------------------------------------------------------ notification

    private fun createChannel() {
        val channel = NotificationChannel(CHANNEL, "Liaison avec la station", NotificationManager.IMPORTANCE_LOW).apply {
            description = "État de la liaison et de l'émission, bouton STOP"
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }

    private fun updateNotification(state: RigState) {
        if (!foreground) return
        val name = request?.account?.name ?: "Station"
        val ptt = state.ptt
        val status = when (state.status) {
            LinkStatus.CONNECTED -> when {
                ptt == null -> "Connecté"
                ptt.mine && ptt.transmitting -> "ÉMISSION EN COURS" + (ptt.totSeconds?.let { " — ${Format.duration(it)}" } ?: "")
                ptt.transmitting -> "${ptt.label} (autre client)"
                else -> ptt.label
            }
            LinkStatus.RECONNECTING -> "Reconnexion…" + (state.reconnect?.let { " ${it.remainingS} s" } ?: "")
            LinkStatus.CONNECTING -> "Connexion…"
            LinkStatus.DISCONNECTED -> "Déconnecté"
        }
        val rig = state.state?.rig
        val detail = if (rig != null && state.status == LinkStatus.CONNECTED) "${Format.frequency(rig.frequencyHz)} ${rig.mode ?: ""}".trim() else ""
        val key = "$name|$status|$detail"
        if (key == lastNotification) return
        lastNotification = key
        val canStop = state.status == LinkStatus.CONNECTED
        getSystemService(NotificationManager::class.java)?.notify(NOTIFICATION_ID, buildNotification(name, status, detail, canStop))
    }

    private fun buildNotification(name: String, status: String, detail: String, canStop: Boolean): Notification {
        val open = packageManager.getLaunchIntentForPackage(packageName)?.let {
            PendingIntent.getActivity(this, 0, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
        val builder = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_rig)
            .setContentTitle("$name — $status")
            .setContentText(detail)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(open)
        if (canStop) builder.addAction(0, "STOP", servicePending(ACTION_STOP, 1))
        builder.addAction(0, "Déconnecter", servicePending(ACTION_DISCONNECT, 2))
        return builder.build()
    }

    private fun servicePending(action: String, code: Int): PendingIntent =
        PendingIntent.getService(this, code, Intent(this, RigService::class.java).setAction(action), PendingIntent.FLAG_IMMUTABLE)

    companion object {
        const val ACTION_CONNECT = "com.rfdiy.openremotetrx.CONNECT"
        const val ACTION_STOP = "com.rfdiy.openremotetrx.STOP"
        const val ACTION_DISCONNECT = "com.rfdiy.openremotetrx.DISCONNECT"
        private const val CHANNEL = "rig"
        private const val NOTIFICATION_ID = 1
    }
}
