// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Memory
import java.text.Normalizer

/** Ce que demande une phrase dite à la voiture (« mémoire 40 mètres », « fréquence 7 074 », « bande 20 mètres »). */
sealed class VoiceAction {
    /** Phrase vide : simple « écouter » (réception audible). */
    data object Listen : VoiceAction()
    data class RecallMemory(val memory: Memory) : VoiceAction()
    data class SetFrequency(val hz: Long) : VoiceAction()
    data class SelectBand(val key: String) : VoiceAction()
    data class Unknown(val text: String) : VoiceAction()
}

/**
 * Commande vocale d'Android Auto (`onPlayFromSearch`). Elle ne fait que CHOISIR une fréquence (mémoire, bande,
 * fréquence) : jamais d'émission par la voix, et la session refuse tout réglage pendant une émission.
 *
 * Fréquence sans unité : moins de 1 000 = MHz (« 7,074 », « 145 »), sinon kHz (« 7 074 », « 27 555 ») ; « MHz » /
 * « mégahertz », « kHz » / « kilohertz » imposent l'unité.
 */
object Voice {
    private val BAND_WORDS = Regex("""^(?:bande\s+)?(\d{1,3})\s*(?:m|metres?|meters?)$""")
    private val FREQ_WORDS = Regex("""^(?:frequence|qsy|accorde(?:r)?|aller)\s+(.+)$""")
    private val MEMORY_WORDS = Regex("""^(?:memoire|canal|preselection)\s+(.+)$""")
    private val NUMBER = Regex("""^(\d[\d ]*(?:[.,]\d+)?)\s*(mhz|megahertz|khz|kilohertz|hz|hertz)?$""")

    fun parse(query: String?, memories: List<Memory>): VoiceAction {
        val text = normalize(query.orEmpty())
        if (text.isEmpty()) return VoiceAction.Listen
        MEMORY_WORDS.find(text)?.let { m -> return findMemory(m.groupValues[1], memories) ?: VoiceAction.Unknown(query!!.trim()) }
        FREQ_WORDS.find(text)?.let { m -> return frequency(m.groupValues[1])?.let { VoiceAction.SetFrequency(it) } ?: VoiceAction.Unknown(query!!.trim()) }
        BAND_WORDS.find(text)?.let { m ->
            val key = m.groupValues[1]
            if (Radio.BANDS.any { it.key == key }) return VoiceAction.SelectBand(key)
        }
        findMemory(text, memories)?.let { return it }                    // nom de mémoire dit tout seul
        frequency(text)?.let { return VoiceAction.SetFrequency(it) }      // nombre dit tout seul
        return VoiceAction.Unknown(query!!.trim())
    }

    /** « 7 074 » -> 7 074 000 Hz ; null si ce n'est pas une fréquence permise. */
    fun frequency(said: String): Long? {
        val m = NUMBER.find(normalize(said)) ?: return null
        val value = m.groupValues[1].replace(" ", "").replace(',', '.').toDoubleOrNull() ?: return null
        val hz = when (m.groupValues[2]) {
            "mhz", "megahertz" -> value * 1e6
            "khz", "kilohertz" -> value * 1e3
            "hz", "hertz" -> value
            else -> if (value < 1000) value * 1e6 else value * 1e3
        }
        val rounded = Math.round(hz)
        return rounded.takeIf { it in Radio.MIN_HZ..Radio.MAX_HZ }
    }

    private fun findMemory(said: String, memories: List<Memory>): VoiceAction.RecallMemory? {
        val wanted = normalize(said)
        if (wanted.isEmpty()) return null
        val exact = memories.firstOrNull { normalize(it.name) == wanted }
        val found = exact ?: memories.firstOrNull { normalize(it.name).replace(" ", "") == wanted.replace(" ", "") }
            ?: memories.filter { normalize(it.name).contains(wanted) }.singleOrNull()
        return found?.let { VoiceAction.RecallMemory(it) }
    }

    /** Minuscules, sans accents ni ponctuation, espaces simples ; « mètres » -> « metres ». */
    fun normalize(text: String): String =
        Normalizer.normalize(text.lowercase(), Normalizer.Form.NFD)
            .replace(Regex("""\p{M}+"""), "")
            .replace(Regex("""[^a-z0-9.,]+"""), " ")
            .trim()
            .replace(Regex("""\s+"""), " ")
}
