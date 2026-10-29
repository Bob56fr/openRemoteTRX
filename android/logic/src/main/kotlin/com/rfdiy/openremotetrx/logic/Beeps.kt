// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/**
 * Bips de fin d'émission, produits et ÉMIS par la station (docs/bips.md) ; réglage commun à tous les appareils
 * (`beeps` du hello, message `beeps`, commande `beeps_set`). Les séquences servent seulement à « Écouter » ici.
 */
data class BeepSettings(
    val rogerEnabled: Boolean,
    val linkLostEnabled: Boolean,
    val tone: String,
    val pattern: Int,
    val tones: List<String>,
    val patterns: List<Int>,
    /** Segments (Hz, ms), 0 Hz = silence. */
    val rogerSequence: List<Pair<Int, Int>>,
    val linkLostSequence: List<Pair<Int, Int>>,
) {
    companion object {
        private fun JsonObject.flag(key: String) = (this[key] as? JsonPrimitive)?.booleanOrNull == true

        private fun sequence(raw: Any?): List<Pair<Int, Int>> = (raw as? JsonArray).orEmpty().take(40).mapNotNull { seg ->
            val pair = seg as? JsonArray ?: return@mapNotNull null
            val hz = (pair.getOrNull(0) as? JsonPrimitive)?.intOrNull ?: return@mapNotNull null
            val ms = (pair.getOrNull(1) as? JsonPrimitive)?.intOrNull ?: return@mapNotNull null
            if (hz in 0..4000 && ms in 1..2000) hz to ms else null
        }

        /** Réglages lus de la station ; null si absents (station sans bips). */
        fun parse(obj: JsonObject?): BeepSettings? {
            if (obj == null || obj.isEmpty()) return null
            val tones = (obj["tones"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.take(20)
            val patterns = (obj["patterns"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.intOrNull }.take(10)
            return BeepSettings(
                rogerEnabled = obj.flag("roger_enabled"),
                linkLostEnabled = obj.flag("link_lost_enabled"),
                tone = (obj["roger_tone"] as? JsonPrimitive)?.contentOrNull.orEmpty(),
                pattern = (obj["roger_pattern"] as? JsonPrimitive)?.intOrNull ?: 1,
                tones = tones,
                patterns = patterns,
                rogerSequence = sequence(obj["roger_sequence"]),
                linkLostSequence = sequence(obj["link_lost_sequence"]),
            )
        }

        /** Libellés de la page (ui.js : TONE_LABELS). */
        fun toneLabel(tone: String): String = if (tone == "duo") "deux tons montants" else "$tone Hz"

        fun patternLabel(n: Int): String = "$n bip" + if (n > 1) "s" else ""
    }
}
