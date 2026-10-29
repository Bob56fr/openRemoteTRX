// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Command
import com.rfdiy.openremotetrx.protocol.ErrorMessage
import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.Memory
import com.rfdiy.openremotetrx.protocol.Memories
import com.rfdiy.openremotetrx.protocol.Protocol
import com.rfdiy.openremotetrx.protocol.ProtocolException
import com.rfdiy.openremotetrx.protocol.Result
import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import kotlinx.serialization.json.JsonPrimitive

enum class LinkStatus { DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING }

/** Sons de liaison (mêmes notes que la page) : perdue, rétablie, perdue pour de bon. */
enum class LinkAlert { LOST, RESTORED, FAILED }

enum class LogLevel { INFO, WARN, BAD }

data class LogLine(val atMs: Long, val text: String, val level: LogLevel)

data class ReconnectInfo(val remainingS: Int, val attempts: Int, val windowS: Int, val lastError: String)

/** Ce que l'écran, la notification et (plus tard) la voiture affichent. Une seule source : RigSession. */
data class RigState(
    val status: LinkStatus = LinkStatus.DISCONNECTED,
    val hello: Hello? = null,
    val state: State? = null,
    val ptt: PttView? = null,
    val armed: Boolean = false,
    /** Faux si la station parle une autre version du protocole : réception et STOP seulement. */
    val protocolOk: Boolean = true,
    val reconnect: ReconnectInfo? = null,
    val rttMs: Int? = null,
    val log: List<LogLine> = emptyList(),
    /** Mémoires partagées de la station, favorites d'abord. */
    val memories: List<Memory> = emptyList(),
    /** Dernière fréquence et dernier mode par bande (gardés sur le téléphone). */
    val bandSpots: Map<String, BandSpot> = emptyMap(),
)

/**
 * Ce que la session demande à la couche Android (WebRTC). Appelé sur le fil de la session uniquement.
 * `close()` ferme la liaison SANS rappeler `onLinkClosed`.
 */
interface SessionLink {
    fun startAttempt()
    fun send(text: String): Boolean
    fun setMicOpen(open: Boolean)
    fun close()
    fun alert(kind: LinkAlert)
}

/**
 * Session avec la station, reprise de la page (client.js, TrxClient) : messages, battements, micro, surveillance
 * de la liaison, reconnexion automatique, commandes en attente. Kotlin pur, piloté par des appels datés (`now` en
 * millisecondes monotones) : RigService l'appelle depuis UN seul fil, et les tests de panne la pilotent sans réseau.
 *
 * Sécurité : l'émission affichée vient TOUJOURS de `state.ptt` ; le micro n'est ouvert qu'en TX confirmé de ce
 * téléphone ; après une reconnexion, le téléphone est en réception et désarmé ; STOP est toujours permis.
 */
class RigSession(
    private val link: SessionLink,
    bandSpots: Map<String, BandSpot> = emptyMap(),
    private val wall: () -> Long = System::currentTimeMillis,
) {
    var snapshot = RigState()
        private set
    var onChange: ((RigState) -> Unit)? = null
    /** Mémoire des bandes modifiée : à enregistrer par l'application. */
    var onBandSpots: ((Map<String, BandSpot>) -> Unit)? = null
    private var bands = BandMemory(bandSpots)
    private var memories: List<Memory> = emptyList()
    private var spectrumWanted = false

    private var status = LinkStatus.DISCONNECTED
    private var attemptActive = false
    private var helloDeadline: Long? = null
    private var windowS = 0
    private var reconnect: ReconnectPolicy? = null
    private var lastReconnectAlert = 0L
    private var lastAttemptError = ""
    private val heartbeat = HeartbeatPolicy()
    private val watch = LinkWatch()
    private val arming = TxArming()
    private var silenceAlerted = false
    private var hello: Hello? = null
    private var state: State? = null
    private var protocolOk = true
    private var nextId = 1
    private val pending = LinkedHashMap<Int, Pending>()
    private var lastPing = Long.MIN_VALUE
    private var rttMs: Int? = null
    private val log = ArrayDeque<LogLine>()

    private class Pending(val cmd: String, val sentAt: Long)

    val connected: Boolean get() = status == LinkStatus.CONNECTED

    // ------------------------------------------------------------------ connexion

    /**
     * Connexion demandée par l'utilisateur. `windowS` : fenêtre de reconnexion automatique (0 = aucune) ;
     * `bandSpots` : mémoire des bandes de CETTE station (null = garder l'actuelle).
     */
    fun begin(now: Long, windowS: Int, bandSpots: Map<String, BandSpot>? = null) {
        if (bandSpots != null) bands = BandMemory(bandSpots)
        teardown()
        reconnect = null
        this.windowS = windowS.coerceIn(0, ReconnectPolicy.MAX_WINDOW_S)
        status = LinkStatus.CONNECTING
        attemptActive = true
        link.startAttempt()
        publish()
    }

    /** La station a accepté l'offre : le canal doit maintenant s'ouvrir (« hello »). */
    fun answered(now: Long) {
        if (!attemptActive) return
        helloDeadline = now + if (reconnect != null) ReconnectPolicy.HELLO_TIMEOUT_MS else HELLO_TIMEOUT_MS
    }

    /** Essai échoué avant « hello » : code de Texts.LOSSES (auth, busy, network, http, pin, no_hello, client_error…). */
    fun attemptFailed(now: Long, code: String, detail: String = "") {
        if (!attemptActive) return
        attemptActive = false
        helloDeadline = null
        link.setMicOpen(false)
        link.close()
        val text = Texts.loss(code) + if (detail.isNotBlank()) " ($detail)" else ""
        val r = reconnect
        if (r != null) {
            lastAttemptError = text
            if (r.attemptFailed(now, authRefused = code == "auth") == ReconnectOutcome.AUTH) giveUp(now, "identifiants refusés par la station")
            publish(now)
            return
        }
        status = LinkStatus.DISCONNECTED
        log("Connexion impossible : $text.", LogLevel.BAD)
        publish(now)
    }

    /** Liaison fermée par le réseau ou la station (canal fermé, ICE échoué, silence…). */
    fun onLinkClosed(now: Long, code: String) {
        if (!connected) {
            if (attemptActive) attemptFailed(now, code)
            return
        }
        val mine = mineActive()
        teardown()
        val title = Texts.loss(code)
        if (windowS > 0) {
            reconnect = ReconnectPolicy(windowS, now)
            lastReconnectAlert = now
            lastAttemptError = ""
            status = LinkStatus.RECONNECTING
            log("Connexion perdue : $title." + (if (mine) " Ton émission est coupée par la station." else "") +
                " Reconnexion automatique pendant $windowS s.", LogLevel.BAD)
            link.alert(LinkAlert.LOST)
        } else {
            status = LinkStatus.DISCONNECTED
            log("Connexion perdue : $title. L'émission éventuelle est coupée par la station.", LogLevel.BAD)
            link.alert(LinkAlert.FAILED)
        }
        publish(now)
    }

    /** Déconnexion voulue : jamais de reconnexion automatique. */
    fun disconnect(now: Long) {
        val was = status != LinkStatus.DISCONNECTED
        teardown()
        reconnect = null
        status = LinkStatus.DISCONNECTED
        if (was) log("Déconnecté.", LogLevel.INFO)
        publish(now)
    }

    // ------------------------------------------------------------------ messages de la station

    fun onMessage(now: Long, text: String) {
        if (!attemptActive && !connected) return
        val msg = try {
            ServerMessages.decode(text)
        } catch (e: ProtocolException) {
            return                                              // message illisible : ignoré, comme la page
        }
        watch.onMessage(now)
        if (silenceAlerted) {
            silenceAlerted = false
            log("La station répond de nouveau.", LogLevel.INFO)
            link.alert(LinkAlert.RESTORED)
        }
        when (msg) {
            is Hello -> onHello(now, msg)
            is State -> {
                state = msg
                afterState()
                if (bands.observe(now, msg.rig.frequencyHz, msg.rig.mode)) onBandSpots?.invoke(bands.spots)
            }
            is Result -> onResult(now, msg)
            is ErrorMessage -> log("Erreur de la station : ${msg.code}" + (if (msg.detail.isNotEmpty()) " (${msg.detail})" else ""), LogLevel.WARN)
            is Memories -> memories = Radio.sortMemories(msg.items)
            else -> Unit                                         // type inconnu ou non affiché : ignoré
        }
        publish(now)
    }

    private fun onHello(now: Long, msg: Hello) {
        helloDeadline = null
        attemptActive = false
        hello = msg
        memories = Radio.sortMemories(msg.memories)
        status = LinkStatus.CONNECTED
        // La station oublie l'abonnement avec la connexion : on le redemande si la vue du spectre est ouverte.
        if (spectrumWanted && msg.spectrum != null && msg.protocol == Protocol.VERSION) send(now, Command.SpectrumWatch(true))
        arming.onConnected()                                     // toujours désarmé à la connexion
        lastPing = now
        protocolOk = msg.protocol == Protocol.VERSION
        if (!protocolOk) {
            log("La station parle le protocole ${msg.protocol}, l'application le ${Protocol.VERSION} : réception et STOP seulement. Mets à jour l'application ou la station.", LogLevel.BAD)
        } else {
            log("Connecté à la station" + (if (msg.version.isNotEmpty()) " ${msg.version}" else "") + ".", LogLevel.INFO)
        }
        val r = reconnect
        if (r != null) {
            reconnect = null
            log("Reconnecté après ${r.elapsedS(now)} s (${r.attempts} essai${if (r.attempts > 1) "s" else ""}). Réactive « Émission autorisée » pour émettre.", LogLevel.INFO)
            link.alert(LinkAlert.RESTORED)                       // la station est en RÉCEPTION : rien ne reprend tout seul
        }
        afterState()
    }

    private fun onResult(now: Long, msg: Result) {
        val entry = msg.id?.let { pending.remove(it) } ?: return
        if (entry.cmd == "get_state") {
            rttMs = (now - entry.sentAt).toInt()
            return
        }
        if (!msg.ok) {
            if (entry.cmd == "toggle") heartbeat.cancelGrace()
            log(Texts.refusal(msg.reason, msg.detail), LogLevel.WARN)
        }
    }

    private fun afterState() {
        link.setMicOpen(mineTx())                               // micro ouvert seulement en TX confirmé de ce téléphone
    }

    // ------------------------------------------------------------------ minuterie (toutes les 400 ms)

    fun tick(now: Long, online: Boolean) {
        val r = reconnect
        if (r != null && !attemptActive) {
            if (r.expired(now)) {
                giveUp(now, "plus de liaison après ${r.windowS} s")
                publish(now)
                return
            }
            if (now - lastReconnectAlert >= LINK_ALERT_REPEAT_MS) {
                lastReconnectAlert = now
                link.alert(LinkAlert.LOST)                       // rappel : la liaison n'est toujours pas revenue
            }
            if (r.due(now, online)) {
                r.attemptStarted()
                attemptActive = true
                link.startAttempt()
            }
        }
        val deadline = helloDeadline
        if (attemptActive && deadline != null && now > deadline) {
            attemptFailed(now, "no_hello")
            return
        }
        if (connected) {
            val mine = mineActive()
            when (watch.check(now, mine)) {
                LinkVerdict.STALE -> { onLinkClosed(now, "silence"); return }
                LinkVerdict.TX_SILENCE -> {
                    silenceAlerted = true
                    log("Plus de nouvelles de la station depuis 1,5 s pendant ton émission : arrête de parler.", LogLevel.BAD)
                    link.alert(LinkAlert.LOST)
                }
                LinkVerdict.OK -> Unit
            }
            if (heartbeat.shouldBeat(now, mine)) link.send(Command.Heartbeat.encode())
            if (now - lastPing >= PING_EVERY_MS) {
                lastPing = now
                send(now, Command.GetState)
            }
            val expired = pending.filterValues { now - it.sentAt > COMMAND_TIMEOUT_MS }
            for ((id, entry) in expired) {
                pending.remove(id)
                if (entry.cmd != "get_state") log("Pas de réponse de la station à « ${entry.cmd} ».", LogLevel.WARN)
            }
        }
        publish(now)
    }

    // ------------------------------------------------------------------ actions de l'utilisateur

    fun setArmed(now: Long, on: Boolean) {
        if (on && connected) arming.arm() else arming.disarm()
        publish(now)
    }

    /** Appui sur PTT (toggle) : prise d'émission si armé et libre, fin de SON émission sinon. */
    fun pressPtt(now: Long) {
        if (!connected) return
        val mine = mineActive()
        val ptt = state?.ptt
        when {
            !protocolOk -> log("Version de protocole inconnue : émission impossible (STOP reste permis).", LogLevel.WARN)
            !mine && !arming.armed -> log("Active d'abord « Émission autorisée ».", LogLevel.WARN)
            !mine && ptt != null && ptt.state != "RX" -> log("Une émission est en cours (${ptt.owner ?: "?"}) : utilise STOP pour couper.", LogLevel.WARN)
            else -> {
                heartbeat.onToggleSent(now)                      // battements dès la demande, avant la confirmation
                send(now, Command.Toggle)
            }
        }
        publish(now)
    }

    /** STOP : toujours envoyé, armé ou non, quelle que soit la version du protocole. */
    fun stop(now: Long) {
        if (!connected) return
        send(now, Command.Stop)
        heartbeat.cancelGrace()
        publish(now)
    }

    /** « Reprendre la main » après une action sur le poste ; la station refuse pendant une émission locale. */
    fun releaseLocal(now: Long) {
        if (!connected) return
        send(now, Command.LocalRelease)
        publish(now)
    }

    // ------------------------------------------------------------------ réglages du poste (la station valide tout)

    fun setFrequency(now: Long, hz: Long) = control(now, Command.SetFrequency(hz.coerceIn(Radio.MIN_HZ, Radio.MAX_HZ)))

    fun setMode(now: Long, mode: String) = control(now, Command.SetMode(mode))

    fun recallMemory(now: Long, id: String) = control(now, Command.MemoryRecall(id))

    /** Bande : dernière fréquence et dernier mode utilisés, sinon le point de départ ; mode données si l'émission l'exige. */
    fun selectBand(now: Long, key: String) {
        val h = hello ?: return
        val (hz, mode) = Radio.bandTarget(bands.spots, key, h.txModes, h.capabilities?.modes.orEmpty()) ?: return
        val commands = buildList {                                  // comme la page : le mode d'abord, puis la fréquence
            if (mode != null && mode != state?.rig?.mode) add(Command.SetMode(mode))
            add(Command.SetFrequency(hz))
        }
        control(now, *commands.toTypedArray())
    }

    /** Vue du spectre HF ouverte (`on`) ou fermée : abonnement aux balayages, gardé pour les reconnexions. */
    fun watchSpectrum(now: Long, on: Boolean) {
        spectrumWanted = on
        if (connected && protocolOk && hello?.spectrum != null) send(now, Command.SpectrumWatch(on))
        publish(now)
    }

    /** Réglage du spectre du poste : `mode`, `span`, `ref`, `speed`, `filter` (refusé hors réception, comme la page). */
    fun spectrumSet(now: Long, name: String, value: JsonPrimitive) = control(now, Command.SpectrumSet(name, value))

    /** Squelch du poste, 0 (ouvert) à 1. */
    fun setSquelch(now: Long, value: Double) = control(now, Command.SetSquelch(value.coerceIn(0.0, 1.0)))

    /** Niveau d'une fonction (NR, NB) : la station vérifie la plage déclarée par le poste. */
    fun setLevel(now: Long, name: String, value: Double) = control(now, Command.SetLevel(name, value))

    /**
     * Mémoire partagée de la station : création (`id` null) ou modification. Ne touche pas au poste : permis aussi
     * pendant une émission (comme la page). La station renvoie la liste à jour (message `memories`).
     */
    fun saveMemory(now: Long, name: String, hz: Long, mode: String, favorite: Boolean, id: String? = null) =
        memoryCommand(now, Command.MemorySave(name.trim().take(MEMORY_NAME_MAX), hz, mode, favorite, id))

    fun deleteMemory(now: Long, id: String) = memoryCommand(now, Command.MemoryDelete(id))

    private fun memoryCommand(now: Long, command: Command) {
        if (!connected) return
        if (!protocolOk) log("Version de protocole inconnue : mémoires en lecture seule.", LogLevel.WARN) else send(now, command)
        publish(now)
    }

    /** Bouton d'une fonction du poste (Controls.chips) : NR, NB, P.AMP, ATT, NOTCH, IP+, AGC, COMP, FIL, TUNER, PWR. */
    fun pressControl(now: Long, key: String) {
        val commands = Controls.press(key, hello, state)
        if (commands.isNotEmpty()) control(now, *commands.toTypedArray())
    }

    /**
     * Réglage du poste : jamais pendant une émission (page : « tx_active » ; la station refuse aussi), ni avec un
     * protocole inconnu. Plusieurs commandes partent dans l'ordre (canal ordonné).
     */
    private fun control(now: Long, vararg commands: Command) {
        if (!connected) return
        when {
            !protocolOk -> log("Version de protocole inconnue : réglages impossibles (STOP reste permis).", LogLevel.WARN)
            (state?.ptt?.state ?: "RX") != "RX" -> log(Texts.refusal("tx_active"), LogLevel.WARN)
            else -> for (command in commands) send(now, command)
        }
        publish(now)
    }

    // ------------------------------------------------------------------ interne

    private fun send(now: Long, command: Command) {
        val id = nextId++
        if (link.send(command.encode(id))) pending[id] = Pending(command.name, now)
    }

    private fun mineActive(): Boolean {
        val p = state?.ptt ?: return false
        val me = hello?.clientId ?: return false
        return p.state in Protocol.ACTIVE_STATES && p.owner == me
    }

    private fun mineTx(): Boolean {
        val p = state?.ptt ?: return false
        return p.state == "TX" && p.owner != null && p.owner == hello?.clientId
    }

    private fun giveUp(now: Long, why: String) {
        teardown()
        reconnect = null
        status = LinkStatus.DISCONNECTED
        log("Reconnexion abandonnée : $why.", LogLevel.BAD)
        link.alert(LinkAlert.FAILED)
    }

    /** Ferme tout : micro d'abord, puis la liaison ; oublie l'état de la station (rien n'est supposé ensuite). */
    private fun teardown() {
        link.setMicOpen(false)
        if (status != LinkStatus.DISCONNECTED || attemptActive) link.close()
        attemptActive = false
        helloDeadline = null
        heartbeat.onDisconnected()
        watch.reset()
        arming.onConnected()
        silenceAlerted = false
        hello = null
        state = null
        memories = emptyList()
        protocolOk = true
        pending.clear()
        rttMs = null
        status = LinkStatus.DISCONNECTED
    }

    private fun log(text: String, level: LogLevel) {
        log.addLast(LogLine(wall(), text, level))
        while (log.size > MAX_LOG) log.removeFirst()
    }

    private fun publish(now: Long = -1) {
        val r = reconnect
        val next = RigState(
            status = status,
            hello = hello,
            state = state,
            ptt = state?.let { s -> hello?.let { PttView.of(s.ptt, it.clientId) } },
            armed = arming.armed,
            protocolOk = protocolOk,
            reconnect = r?.let {
                ReconnectInfo(
                    remainingS = if (now >= 0) maxOf(0, ((it.deadline - now + 999) / 1000).toInt()) else it.windowS,
                    attempts = it.attempts, windowS = it.windowS, lastError = lastAttemptError,
                )
            },
            rttMs = rttMs,
            log = log.toList(),
            memories = memories,
            bandSpots = bands.spots,
        )
        if (next != snapshot) {
            snapshot = next
            onChange?.invoke(next)
        }
    }

    companion object {
        const val PING_EVERY_MS = 2000L
        const val COMMAND_TIMEOUT_MS = 5000L
        /** Connexion manuelle : le canal doit s'ouvrir dans ce délai après la réponse de la station. */
        const val HELLO_TIMEOUT_MS = 15_000L
        const val LINK_ALERT_REPEAT_MS = 3000L
        const val MAX_LOG = 60
        /** Nom d'une mémoire : 40 caractères au plus (station : memories.MAX_NAME). */
        const val MEMORY_NAME_MAX = 40
    }
}
