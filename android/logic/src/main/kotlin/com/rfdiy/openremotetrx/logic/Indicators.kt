// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.State

/** Voyant de l'afficheur (comme sur un poste) : texte vert si actif, gris sinon. */
data class Indicator(val label: String, val on: Boolean)

/**
 * Voyants à côté de la fréquence (demande de l'utilisateur) : NB, NR (fonctions lues par la station), puis POWER, SWR,
 * ALC (toujours montrés), actifs seulement quand le poste émet ET mesure quelque chose. VFO-A / VFO-B, CLAR, RIT :
 * après leur ajout côté station.
 */
object Indicators {
    private const val MEASURED = 0.01

    fun of(state: State?): List<Indicator> {
        val rig = state?.rig ?: return emptyList()
        val tx = state.ptt.state in setOf("KEYING", "TX")
        val out = mutableListOf<Indicator>()
        rig.functions["NB"]?.let { out += Indicator("NB", it) }
        rig.functions["NR"]?.let { out += Indicator("NR", it) }
        // Toujours affichés (gris en réception : la station ne publie ces mesures que pendant l'émission)
        out += Indicator("POWER", tx && (rig.levels["RFPOWER_METER"] ?: 0.0) > MEASURED)
        out += Indicator("SWR", tx && (rig.levels["SWR"] ?: 0.0) > 1.0 + MEASURED)
        out += Indicator("ALC", tx && (rig.levels["ALC"] ?: 0.0) > MEASURED)
        return out
    }
}
