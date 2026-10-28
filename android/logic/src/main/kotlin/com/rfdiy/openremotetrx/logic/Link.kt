// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Protocol
import kotlin.math.min

/**
 * Battements : envoyés toutes les 400 ms tant que l'émission de ce téléphone est active, et dès l'envoi de
 * « toggle » (3 s de grâce, avant même la réponse de la station). Sans eux, la station coupe en 2 s :
 * l'application ne fait que l'aider, elle ne remplace jamais cette coupure. Temps en millisecondes monotones.
 */
class HeartbeatPolicy {
    private var graceUntil = Long.MIN_VALUE

    fun onToggleSent(now: Long) {
        graceUntil = now + Protocol.HEARTBEAT_GRACE_MS
    }

    fun onDisconnected() {
        graceUntil = Long.MIN_VALUE
    }

    fun shouldBeat(now: Long, mineActive: Boolean): Boolean = mineActive || now < graceUntil
}

/** Ce que la surveillance de la liaison demande de faire à un instant donné. */
enum class LinkVerdict { OK, TX_SILENCE, STALE }

/**
 * Silence de la station. Elle envoie son état plusieurs fois par seconde : 5 s sans rien = liaison perdue ;
 * pendant SON émission, 1,5 s sans rien = alerte immédiate (l'utilisateur parle peut-être dans le vide), une
 * seule fois par silence.
 */
class LinkWatch(private val staleMs: Long = 5000, private val txSilenceMs: Long = 1500) {
    private var lastMessageAt: Long? = null
    private var silenceAlerted = false

    fun onMessage(now: Long) {
        lastMessageAt = now
        silenceAlerted = false
    }

    fun reset() {
        lastMessageAt = null
        silenceAlerted = false
    }

    fun check(now: Long, mineActive: Boolean): LinkVerdict {
        val last = lastMessageAt ?: return LinkVerdict.OK
        if (now - last > staleMs) return LinkVerdict.STALE
        if (!silenceAlerted && mineActive && now - last > txSilenceMs) {
            silenceAlerted = true
            return LinkVerdict.TX_SILENCE
        }
        return LinkVerdict.OK
    }
}

/** Issue d'une reconnexion automatique. */
enum class ReconnectOutcome { OK, TIMEOUT, AUTH, CANCELLED }

/**
 * Reconnexion automatique, comme la page : premier essai après 400 ms, puis 1,5 s, 3 s, 4,5 s au plus entre deux
 * essais, pendant une fenêtre réglable (300 s au plus). Identifiants refusés : arrêt immédiat (la station
 * freine les mots de passe faux). Après une reconnexion, le téléphone est en RÉCEPTION et doit être réarmé.
 */
class ReconnectPolicy(windowS: Int, private val startedAt: Long) {
    val windowS: Int = windowS.coerceIn(0, MAX_WINDOW_S)
    val deadline: Long = startedAt + this.windowS * 1000L
    var attempts = 0
        private set
    var nextAt: Long = startedAt + FIRST_DELAY_MS
        private set
    var busy = false
        private set

    val enabled: Boolean get() = windowS > 0

    /** Vrai s'il faut lancer un essai maintenant (réseau présent, pas d'essai en cours, délai écoulé). */
    fun due(now: Long, online: Boolean): Boolean = !busy && online && now >= nextAt && now < deadline

    fun expired(now: Long): Boolean = now >= deadline

    fun attemptStarted() {
        busy = true
        attempts += 1
    }

    /** Essai échoué ; renvoie AUTH s'il faut abandonner tout de suite, sinon null (prochain essai planifié). */
    fun attemptFailed(now: Long, authRefused: Boolean): ReconnectOutcome? {
        busy = false
        if (authRefused) return ReconnectOutcome.AUTH
        nextAt = now + RETRY_MS * min(attempts, 3)
        return null
    }

    fun elapsedS(now: Long): Int = ((now - startedAt) / 1000).toInt()

    companion object {
        const val FIRST_DELAY_MS = 400L
        const val RETRY_MS = 1500L
        const val MAX_WINDOW_S = 300
        /** En reconnexion, un canal qui ne s'ouvre pas en 6 s est abandonné pour réessayer. */
        const val HELLO_TIMEOUT_MS = 6000L
    }
}

/**
 * « Émission autorisée » : il faut armer avant de prendre l'émission, comme la case de la page. Toujours désarmé
 * à la connexion et après une reconnexion (RX au démarrage et à la reconnexion) ; reste armé après une fin
 * d'émission normale.
 */
class TxArming {
    var armed = false
        private set

    fun arm() { armed = true }
    fun disarm() { armed = false }
    fun onConnected() { armed = false }
}
