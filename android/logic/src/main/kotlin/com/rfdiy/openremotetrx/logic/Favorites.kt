// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Memory

/**
 * Favoris au volant (F1) : Suivant / Précédent font défiler les mémoires favorites (★) comme les présélections d'un
 * autoradio, avec retour circulaire. Ne change que la fréquence et le mode, jamais l'émission ; refusé en émission.
 */
object Favorites {
    /** Mémoires favorites, par fréquence (ordre de l'application : favorites d'abord, puis par fréquence). */
    fun list(memories: List<Memory>): List<Memory> = memories.filter { it.favorite }.sortedWith(compareBy({ it.hz }, { it.name }))

    /**
     * Favori suivant (`forward`) ou précédent. Depuis un favori : voisin, en boucle. Hors favori : premier favori au-dessus
     * (Suivant) ou en dessous (Précédent) de la fréquence actuelle, en boucle aussi. null : aucun favori.
     */
    fun step(favorites: List<Memory>, from: Memory?, hz: Long?, forward: Boolean): Memory? {
        if (favorites.isEmpty()) return null
        val i = from?.let { f -> favorites.indexOfFirst { it.id == f.id } } ?: -1
        if (i >= 0) return favorites[Math.floorMod(i + if (forward) 1 else -1, favorites.size)]
        if (hz == null) return if (forward) favorites.first() else favorites.last()
        return if (forward) favorites.firstOrNull { it.hz > hz } ?: favorites.first()
        else favorites.lastOrNull { it.hz < hz } ?: favorites.last()
    }
}

/**
 * Regroupement des appuis (F1) : chaque appui avance d'un favori à partir du dernier choisi ; seul le dernier part vers
 * la station, `delayMs` après le dernier appui. Logique pure : l'appelant fournit l'heure et arme sa minuterie.
 */
class FavoriteStepper(private val delayMs: Long = 300) {
    /** Favori choisi, pas encore envoyé (affiché en titre en attendant). */
    var pending: Memory? = null
        private set
    private var dueAtMs = 0L

    /** Un appui ; renvoie le favori choisi (null : aucun favori). */
    fun press(nowMs: Long, forward: Boolean, memories: List<Memory>, current: Memory?, hz: Long?): Memory? {
        val next = Favorites.step(Favorites.list(memories), pending ?: current, hz, forward) ?: return null
        pending = next
        dueAtMs = nowMs + delayMs
        return next
    }

    /** Millisecondes avant l'envoi (0 : maintenant), null si rien n'attend. */
    fun remainingMs(nowMs: Long): Long? = pending?.let { maxOf(0L, dueAtMs - nowMs) }

    /** Le favori à envoyer si le délai est écoulé (et l'oublie), sinon null. */
    fun take(nowMs: Long): Memory? {
        val p = pending ?: return null
        if (nowMs < dueAtMs) return null
        pending = null
        return p
    }

    /** Abandon (émission, déconnexion). */
    fun cancel() { pending = null }
}
