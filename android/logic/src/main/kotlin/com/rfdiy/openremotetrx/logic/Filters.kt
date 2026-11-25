// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.RigSpecInfo
import com.rfdiy.openremotetrx.protocol.State
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlin.math.abs

/**
 * Largeur des filtres d'après la fiche technique du poste (`hello.rig_spec`, étape 395) ; même logique que client.js
 * (filterSteps, quickWidths, nextWidth, nearestStep, filterDialogView). Kotlin pur.
 * - Icom (`presets`) : appui bref = FIL1 -> 2 -> 3 (Controls), appui long = trois curseurs sur les largeurs relues par la
 *   station sur le port B (`spectrum.settings.filter_widths` / `filter_steps`) ;
 * - Yaesu (`steps`) : texte = largeur RELUE, appui bref = palier suivant de la liste courte (1.8 à 4.0 k), appui long =
 *   un curseur sur les paliers du mode.
 */
object Filters {
    fun steps(spec: RigSpecInfo?, mode: String?): List<Int>? {
        val f = spec?.filters ?: return null
        if (f.kind != "steps" || mode == null) return null
        return f.steps[mode]?.takeIf { it.size > 1 }
    }

    fun quick(spec: RigSpecInfo?, mode: String?): List<Int>? {
        val steps = steps(spec, mode) ?: return null
        val quick = spec?.filters?.quick.orEmpty()
        return quick.takeIf { it.size > 1 && steps.containsAll(it) }
    }

    /** Largeur suivante de la liste après la largeur relue, en boucle ; inconnue : la première. */
    fun next(list: List<Int>, passband: Int?): Int {
        if (passband == null || passband <= 0) return list.first()
        return list.firstOrNull { it > passband + 1 } ?: list.first()
    }

    fun nearest(steps: List<Int>, hz: Int): Int = steps.minByOrNull { abs(it - hz) } ?: hz

    data class Row(val filter: Int, val hz: Int?)

    /** Fenêtre FIL : `kind` = presets (trois curseurs), steps (un curseur), none (rien à régler ici). */
    data class Dialog(
        val kind: String,
        val mode: String,
        val locked: Boolean,
        val steps: List<Int> = emptyList(),
        val rows: List<Row> = emptyList(),
        val current: Int? = null,
        val known: Boolean = false,
        val hz: Int? = null,
        val quick: Boolean = false,
    )

    private fun ints(value: Any?): List<Int?>? = (value as? JsonArray)?.map { (it as? JsonPrimitive)?.intOrNull }

    fun dialog(hello: Hello?, state: State?, locked: Boolean): Dialog {
        val rig = state?.rig
        val mode = rig?.mode.orEmpty()
        val preset = Controls.filterPreset(state)
        if (preset != null) {
            val settings = state?.spectrum?.get("settings") as? JsonObject
            val widths = ints(settings?.get("filter_widths"))?.takeIf { it.size == 3 }
            val steps = ints(settings?.get("filter_steps"))?.filterNotNull()?.takeIf { it.size > 1 }
            return Dialog("presets", mode, locked, steps.orEmpty(), (1..3).map { Row(it, widths?.get(it - 1)) }, preset,
                          known = widths != null && steps != null)
        }
        val steps = steps(hello?.rigSpec, rig?.mode)
        if (steps != null) return Dialog("steps", mode, locked, steps, hz = rig?.passbandHz, quick = quick(hello?.rigSpec, rig?.mode) != null)
        return Dialog("none", mode, locked)
    }
}
