// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Presence

/**
 * Visiteurs (docs/visiteurs-cahier-des-charges.md) : ce que l'écran montre de `state.presence`, comme la page
 * (client.js : presenceView). Rien de la station = null.
 */
data class PresenceUi(
    val count: Int,
    /** « 🎧 3 » ; vide sans visiteur. */
    val label: String,
    val people: List<Person>,
    /** Opérateur seulement : visiteurs à « Déconnecter ». */
    val kick: List<Kick>,
    /** Opérateur absent : compte à rebours avant la fin de l'écoute ; vide sinon. */
    val grace: String,
    /** Écoute suspendue par une surcharge de la station : message de la station ; vide sinon. */
    val suspended: String,
    val canReopen: Boolean,
    /** Commutateur « Écoute des visiteurs » (opérateur, station 0.74.0+). */
    val switchShown: Boolean,
    val switchOn: Boolean,
    val switchAvailable: Boolean,
    val switchNote: String,
) {
    data class Person(val text: String, val role: String, val since: String)
    data class Kick(val account: String, val text: String, val detail: String)

    companion object {
        fun duration(seconds: Int): String {
            val s = maxOf(0, seconds)
            return when {
                s < 60 -> "$s s"
                s < 3600 -> "${s / 60} min"
                else -> "%d h %02d".format(s / 3600, (s % 3600) / 60)
            }
        }

        fun of(p: Presence?, listener: Boolean): PresenceUi? {
            p ?: return null
            val operator = !listener
            val people = p.people.map {
                Person(it.pseudo.take(32) + if (it.count > 1) " ×${it.count}" else "",
                    if (it.role == "listener") "Visiteur" else "Opérateur", duration(it.sinceS))
            }
            val kick = if (!operator) emptyList() else p.connections.filter { it.role == "listener" }.map {
                Kick(it.id, it.pseudo.ifBlank { it.id }.take(32), "${it.id} · ${it.source.ifBlank { "?" }} · ${duration(it.sinceS)}")
            }
            val grace = p.graceRemainingS?.let {
                "Opérateur momentanément déconnecté : fin de l'écoute des visiteurs dans ${maxOf(0, Math.round(it).toInt())} s."
            } ?: ""
            val suspended = p.suspended?.let { it.message.ifBlank { "Écoute des visiteurs suspendue." }.take(300) } ?: ""
            val available = p.maxListeners > 0
            val note = when {
                !available -> "Fermée sur la station : nombre maximal de visiteurs à 0 (TRX Console, menu 20)."
                p.open == true -> "Ouverte : ${p.listeners} visiteur(s) sur ${p.maxListeners} au plus."
                else -> "Fermée : aucun visiteur ne peut se connecter."
            }
            return PresenceUi(
                count = p.listeners, label = if (p.listeners > 0) "🎧 ${p.listeners}" else "", people = people, kick = kick,
                grace = grace, suspended = suspended, canReopen = operator && p.suspended != null,
                switchShown = operator && p.open != null, switchOn = p.open == true, switchAvailable = available, switchNote = note,
            )
        }
    }
}
