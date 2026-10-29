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
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.rfdiy.openremotetrx.logic.Format
import com.rfdiy.openremotetrx.logic.LinkAlert
import com.rfdiy.openremotetrx.logic.LinkStatus
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

    private fun now(): Long = SystemClock.elapsedRealtime()

    /** Exécute sur le fil de la session. */
    internal fun onRig(block: (RigSession, Long) -> Unit) {
        executor.execute { block(session, now()) }
    }

    override fun onCreate() {
        super.onCreate()
        sounds = LinkSounds(this)
        rtc = RtcLink(
            this,
            post = { block -> runCatching { executor.execute(block) } },
            onMessage = { text -> session.onMessage(now(), text) },
            onClosed = { code -> session.onLinkClosed(now(), code) },
            onSpectrum = { bytes -> RigHub.offerSpectrum(bytes) },
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
