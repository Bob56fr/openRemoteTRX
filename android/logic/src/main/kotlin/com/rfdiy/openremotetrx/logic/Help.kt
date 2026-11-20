// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Aides courtes affichées par un APPUI LONG sur un bouton qui n'a pas d'autre action longue (demande de l'utilisateur,
 * 2026-11-09). Un seul endroit pour les textes : fonctions du poste (clés de `Controls.chips`), boutons du client,
 * spectres. Un bouton sans aide ici ne montre rien (aucune fenêtre vide).
 */
object Help {
    /** Fonctions du poste, par clé de `ControlChip` (toutes couvertes : HelpTest) ; textes `help.<clé en minuscules>`. */
    private val CONTROL_KEYS = listOf("NR", "NB", "PREAMP", "ATT", "NOTCH", "AGC", "FIL", "PWR", "AIP", "COMP", "RIT", "XIT",
                                      "TUNER")

    /** Boutons du client et des spectres. */
    private val CLIENT_KEYS = listOf("SEL", "BZH", "FDV", "WF", "HF", "SON", "STEP", "ARM", "MUTE")

    /** Fonctions du poste, par clé de `ControlChip` (toutes couvertes : HelpTest). */
    val CONTROLS: Map<String, String> get() = CONTROL_KEYS.associateWith { Tr.t("help." + it.lowercase()) }

    /** Boutons du client et des spectres. */
    val CLIENT: Map<String, String> get() = CLIENT_KEYS.associateWith { Tr.t("help." + it.lowercase()) }

    fun control(key: String): String? = if (key in CONTROL_KEYS) Tr.t("help." + key.lowercase()) else null

    fun client(key: String): String? = if (key in CLIENT_KEYS) Tr.t("help." + key.lowercase()) else null
}
