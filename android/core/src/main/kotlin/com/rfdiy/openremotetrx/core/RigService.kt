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
import com.rfdiy.openremotetrx.logic.HeadsetMic
import com.rfdiy.openremotetrx.logic.HeadsetMicStep
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Service au premier plan, SEUL propriétaire de la connexion avec la station (CLAUDE.md, « Client Android »).
 * Tout ce qui touche la session passe par UN fil (« rig ») : messages, minuterie de 400 ms, actions des vues.
 *
 * Garde la réception écran éteint (verrous de veille et Wi-Fi), affiche une notification permanente avec STOP,
 * et applique E5 : perte du focus audio (appel) pendant SON émission => STOP.
 *
 * Réglage « PTT par le bouton du casque ou du volant » (désactivé par défaut) : session média Android qui reçoit
 * Lecture/Pause d'un casque filaire ou Bluetooth et des touches du volant (logic.MediaKeys). Réglage « micro du
 * casque Bluetooth » : casque en mode appel pendant l'émission SEULEMENT (logic.HeadsetMic, étape 96).
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
    private var commListener: Any? = null                         // AudioManager.OnCommunicationDeviceChangedListener (Android 12+)
    private var deviceAddedAt: Long? = null                       // fil « rig »
    private var lastMediaKeyAt: Long? = null
    private var headsetMic = false
    private val headsetCall = HeadsetMic()                        // fil « rig »
    private var headsetName = ""
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
        VoiceHub.load(this)
        val prefs = getSharedPreferences(RigHub.PREFS, MODE_PRIVATE)
        headsetMic = prefs.getBoolean(RigHub.PREF_HEADSET_MIC, false)
        val processing = com.rfdiy.openremotetrx.logic.MicProfiles.processing(
            prefs.getString(RigHub.PREF_MIC_PROFILE, null), prefs.getBoolean(RigHub.PREF_MIC_ECHO, true), prefs.getBoolean(RigHub.PREF_MIC_NOISE, false),
        )
        rtc = RtcLink(
            this,
            post = { block -> runCatching { executor.execute(block) } },
            onMessage = { text -> session.onMessage(now(), text) },
            onClosed = { code -> session.onLinkClosed(now(), code) },
            onSpectrum = { bytes -> RigHub.offerSpectrum(bytes) },
            processing = processing,
            device = RigHub.deviceId(this),
            agent = "android " + (runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull() ?: ""),
        )
        SpatialHub.load(this)
        SpatialHub.attach(rtc) { block -> runCatching { executor.execute(block) } }
        session = RigSession(object : SessionLink {
            override fun startAttempt() = launchAttempt()
            override fun send(text: String): Boolean = rtc.send(text)
            override fun setMicOpen(open: Boolean) {
                if (headsetMic) headsetStep(headsetCall.micWanted(open, now())) else rtc.setMicOpen(open)
            }
            override fun close() {
                attempt?.cancel()
                attempt = null
                rtc.close()
            }
            override fun alert(kind: LinkAlert) = sounds.play(kind)
        }, netType = { netType() })
        session.onNetExport = { name, bytes -> RigHub.offerNetExport(name, bytes) }
        session.onChange = { state -> onState(state) }
        session.onBandSpots = { spots -> request?.let { BandStore(this).save(it.account.id, spots) } }
        RigHub.service = this
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> {
                val asked = RigHub.pending
                RigHub.pending = null
                if (asked == null) {
                    if (!foreground) stopSelf()
                    return START_NOT_STICKY
                }
                val req = goForeground(asked) ?: return START_NOT_STICKY   // micro refusé par Android : réception seule
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
                netHealthStep()
                if (headsetMic) headsetStep(headsetCall.tick(now()))
                delay(com.rfdiy.openremotetrx.protocol.Protocol.HEARTBEAT_TICK_MS)
            }
        }
    }

    private var nextHealth = 0L
    private var healthBusy = false

    /** Sonde réseau : GET /health toutes les 5 s (hors WebRTC), aussi pendant une reconnexion. */
    private fun netHealthStep() {
        val req = request ?: return
        val t = now()
        if (!session.netProbing || healthBusy || t < nextHealth) return
        nextHealth = t + com.rfdiy.openremotetrx.logic.NetClient.HEALTH_EVERY_MS
        healthBusy = true
        scope.launch {
            val ok = withContext(Dispatchers.IO) { StationHttp(req.account.url, req.account.fingerprint).health() }
            healthBusy = false
            session.netHealth(ok)
        }
    }

    /** Type de réseau pour la sonde (4G / 5G : lot 6, avec la radio). */
    private fun netType(): String? {
        val cm = getSystemService(ConnectivityManager::class.java) ?: return null
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return null
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "lan"
            else -> "unknown"
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
        VoiceHub.setBreizhRoute(state.breizh?.effectsOff == true)          // voix par Breizh : égaliseur et effets coupés
        val mine = state.ptt?.let { it.mine && it.transmitting } ?: false
        // Micro du casque : bip de prise quand le micro s'ouvre vraiment (casque en mode appel ~1 s plus tard, headsetStep).
        if (mine != wasMine && !(mine && headsetMic)) sounds.txBeep(mine)
        wasMine = mine

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

    /**
     * Premier plan. Lancé depuis la voiture, application en arrière-plan : Android peut refuser le micro (Android 14+)
     * => réception seule (le PTT reste impossible, jamais d'émission sans micro) ; tout refusé => rien (null).
     */
    private fun goForeground(request: RigHub.Request): RigHub.Request? {
        var req = request
        val note = buildNotification(req.account.name, "Connexion…", "", false)
        val media = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
        val withMic = if (Build.VERSION.SDK_INT >= 30) media or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else media
        try {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, note, if (req.useMic) withMic else media)
        } catch (e: RuntimeException) {                           // SecurityException, ForegroundServiceStartNotAllowedException
            if (!req.useMic) return refuseStart()
            try {
                ServiceCompat.startForeground(this, NOTIFICATION_ID, note, media)
            } catch (e2: RuntimeException) {
                return refuseStart()
            }
            req = req.copy(useMic = false)
            RigHub.carNotice("Réception seule : Android refuse le micro depuis la voiture (ouvrez l'application sur le téléphone pour émettre).")
        }
        foreground = true
        acquireLocks()
        requestFocus()
        getSystemService(AudioManager::class.java)?.registerAudioDeviceCallback(devices, Handler(mainLooper))
        refreshMediaSession()
        if (headsetMic) useHeadsetMic()
        return req
    }

    private fun refuseStart(): RigHub.Request? {
        RigHub.carNotice("Android refuse la connexion depuis la voiture : ouvrez openRemoteTRX sur le téléphone.")
        if (!foreground) stopSelf()
        return null
    }

    // ------------------------------------------------------------------ casque et volant

    /**
     * Session média commune (RigMedia, partagée avec la voiture) : prise pour les touches selon le réglage (fil
     * principal). Sans réglage ni voiture, fermée : les touches restent aux autres applications.
     */
    internal fun refreshMediaSession() {
        Handler(mainLooper).post {
            val want = foreground && getSharedPreferences(RigHub.PREFS, MODE_PRIVATE).getBoolean(RigHub.PREF_MEDIA_PTT, false)
            if (want) RigMedia.acquire(this, RigMedia.USER_BUTTONS) else RigMedia.release(RigMedia.USER_BUTTONS)
        }
    }

    private fun releaseMedia() = RigMedia.release(RigMedia.USER_BUTTONS)

    /** Touche du casque ou du volant avec « PTT par le bouton » (fil principal) : vrai si consommée. */
    internal fun mediaButton(intent: Intent): Boolean {
        val event = keyEvent(intent) ?: return false
        val key = keyOf(event.keyCode)
        if (key == MediaKey.OTHER) return false
        if (event.action == KeyEvent.ACTION_DOWN) executor.execute { onMediaKey(key, event.repeatCount) }
        return true                                                 // appui et relâchement consommés : rien d'autre ne démarre
    }

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
        val sinceDevice = deviceAddedAt?.let { t - it }
        val sinceLast = lastMediaKeyAt?.let { t - it }
        val action = MediaKeys.decide(key, repeat, mine, sinceDevice, sinceLast)
        val name = key.name.lowercase()
        if (action != MediaAction.TOGGLE) {
            if (repeat == 0) session.note(t, "Bouton du casque ou du volant ($name) ignoré : ${MediaKeys.ignoredWhy(key, repeat, mine, sinceDevice, sinceLast)}.")
            return
        }
        lastMediaKeyAt = t
        session.note(t, "Bouton du casque ou du volant ($name) : " + if (mine) "fin d'émission." else "demande d'émission.")
        if (!mine && (!snap.armed || request?.useMic != true || snap.ptt?.transmitting == true)) {
            sounds.refused()                                       // refus audible : l'écran n'est peut-être pas visible
        }
        session.pressPtt(t)                                        // journal : motif du refus éventuel
    }

    /**
     * Micro du casque Bluetooth (Android 12+), à la connexion : rien n'est basculé, la réception reste en mode musique
     * (le bouton du casque y arrive comme Lecture/Pause). On suit seulement l'appareil de communication.
     */
    private fun useHeadsetMic() {
        val am = getSystemService(AudioManager::class.java) ?: return
        val text = if (Build.VERSION.SDK_INT < 31) {
            "Android 12 ou plus récent requis : émission refusée tant que ce réglage est actif"
        } else {
            watchCommunicationDevice(am)
            headsetDevice(am)?.let { "casque prêt : ${it.productName} (micro pris pendant l'émission seulement)" }
                ?: "aucun casque Bluetooth connecté : émission refusée tant que ce réglage est actif"
        }
        RigHub.publish { it.copy(headsetMic = text) }
    }

    @androidx.annotation.RequiresApi(31)
    private fun headsetDevice(am: AudioManager): AudioDeviceInfo? = am.availableCommunicationDevices.firstOrNull { isHeadset(it) }

    private fun isHeadset(device: AudioDeviceInfo?): Boolean =
        device?.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || device?.type == AudioDeviceInfo.TYPE_BLE_HEADSET

    /**
     * Appareil de communication changé. Pendant l'émission, le casque qui sort du mode appel (son bouton « raccroche »
     * l'appel virtuel : Android le termine lui-même, relevé sur le S25 le 2026-11-01) = fin d'émission (HeadsetMic).
     */
    @androidx.annotation.RequiresApi(31)
    private fun watchCommunicationDevice(am: AudioManager) {
        if (commListener != null) return
        val listener = AudioManager.OnCommunicationDeviceChangedListener { current ->
            executor.execute { if (headsetMic && foreground) headsetStep(headsetCall.routed(isHeadset(current))) }
        }
        am.addOnCommunicationDeviceChangedListener(mainExecutor, listener)
        commListener = listener
    }

    /** Sur le fil « rig » : applique une décision de HeadsetMic (logic, testée). */
    private fun headsetStep(step: HeadsetMicStep) {
        when (step) {
            HeadsetMicStep.None -> Unit
            HeadsetMicStep.Route -> routeToHeadset()
            HeadsetMicStep.OpenMic -> {
                rtc.setMicOpen(true)
                sounds.txBeep(true)                                    // « parlez après le bip » : micro ouvert
                RigHub.publish { it.copy(headsetMic = "micro du casque : $headsetName (émission)") }
            }
            HeadsetMicStep.Release -> {
                rtc.setMicOpen(false)
                releaseRoute()
            }
            is HeadsetMicStep.Stop -> {
                rtc.setMicOpen(false)
                releaseRoute()
                if (step.failure) sounds.refused()
                executor.execute { session.stop(now(), step.why) }   // hors du rappel de la session en cours
            }
        }
    }

    /** Casque en mode appel pour l'émission ; le micro ne s'ouvre qu'à la confirmation (headsetStep, OpenMic). */
    private fun routeToHeadset() {
        val am = getSystemService(AudioManager::class.java)
        if (am == null || Build.VERSION.SDK_INT < 31) {
            headsetStep(headsetCall.routeFailed("Micro du casque : Android 12 ou plus récent requis : retour en réception."))
            return
        }
        val device = headsetDevice(am)
        if (device == null) {
            headsetStep(headsetCall.routeFailed("Micro du casque choisi, mais aucun casque Bluetooth connecté : retour en réception."))
            return
        }
        headsetName = device.productName.toString()
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        if (!am.setCommunicationDevice(device)) {
            headsetStep(headsetCall.routeFailed("Android refuse le micro du casque : retour en réception."))
        } else if (isHeadset(am.communicationDevice)) {
            headsetStep(headsetCall.routed(true))                  // déjà en place : aucun changement ne sera signalé
        }
    }

    /** Casque rendu à la musique (réception). */
    private fun releaseRoute() {
        val am = getSystemService(AudioManager::class.java) ?: return
        runCatching {
            if (Build.VERSION.SDK_INT >= 31) am.clearCommunicationDevice()
            am.mode = AudioManager.MODE_NORMAL
        }
        if (headsetMic && foreground) useHeadsetMic()             // texte des réglages : prêt ou absent
    }

    private fun releaseHeadsetMic() {
        if (!headsetMic) return
        headsetCall.reset()
        val am = getSystemService(AudioManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= 31) (commListener as? AudioManager.OnCommunicationDeviceChangedListener)?.let {
            runCatching { am.removeOnCommunicationDeviceChangedListener(it) }
        }
        commListener = null
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

    /** Vrai si le focus est tenu (déjà, ou accordé à l'instant). */
    private fun requestFocus(): Boolean {
        if (focus != null) return true
        val am = getSystemService(AudioManager::class.java) ?: return false
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setWillPauseWhenDucked(false)
            .setOnAudioFocusChangeListener { change -> executor.execute { onFocus(change) } }
            .build()
        if (am.requestAudioFocus(req) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) return false   // appel en cours : plus tard
        focus = req
        return true
    }

    private fun abandonFocus() {
        val req = focus ?: return
        getSystemService(AudioManager::class.java)?.abandonAudioFocusRequest(req)
        focus = null
    }

    /**
     * Lecture demandée (écran de la voiture, Lecture / Pause) ou voiture connectée : reprendre le son. Sans cela, une perte
     * du focus jamais rendue par Android (assistant, guidage, appel par la voiture) laissait la réception muette jusqu'à
     * la relance de l'application (essai Android Auto du 2026-11-05).
     */
    internal fun regainAudio() {
        executor.execute {
            if (!foreground) return@execute
            if (!focusLost && focus != null) return@execute
            abandonFocus()
            if (!requestFocus()) {
                session.note(now(), "Son occupé par un appel ou une autre application : réception muette en attendant.")
                return@execute
            }
            if (focusLost) session.note(now(), "Son repris (lecture demandée).", false)
            focusLost = false
            applyMute()
        }
    }

    /** E5 : focus perdu (appel entrant, autre application) pendant SON émission => STOP ; réception muette. */
    private fun onFocus(change: Int) {
        when (change) {
            AudioManager.AUDIOFOCUS_LOSS, AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> {
                if (change == AudioManager.AUDIOFOCUS_LOSS) focus = null     // demande morte : la prochaine lecture la refait
                if (session.snapshot.ptt?.let { it.mine && it.transmitting } == true) session.stop(now(), "Son pris par un appel ou une autre application : retour en réception.")
                // Appel (perte passagère) : réception muette jusqu'au retour du son. Perte définitive (autre application de
                // musique) : la réception continue, sinon elle resterait muette sans raison visible (essai du 2026-10-29).
                if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) {
                    focusLost = true
                    session.note(now(), "Son pris par un appel ou une autre application : réception muette en attendant.")
                } else {
                    session.note(now(), "Une autre application a pris le son : la réception continue.")
                }
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
