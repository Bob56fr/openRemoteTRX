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
 * Mots des QUATRE langues acceptés quelle que soit la langue de l'application (lot T7, cahier § 4.3 : la langue de la
 * reconnaissance est celle de l'Assistant, pas celle de l'application) : « mémoire / memory / Speicher / memoria »,
 * « fréquence / frequency / Frequenz / frecuencia », « bande 20 mètres / 20 meter band / 20-Meter-Band / banda de
 * 20 metros ». Aucun mot ne fait émettre.
 *
 * Fréquence sans unité : moins de 1 000 = MHz (« 7,074 », « 145 »), sinon kHz (« 7 074 », « 27 555 ») ; « MHz » /
 * « mégahertz », « kHz » / « kilohertz » imposent l'unité. Une virgule de milliers anglaise (« 7,074 ») donne la même
 * fréquence qu'une virgule décimale française (7,074 MHz = 7 074 kHz).
 */
object Voice {
    private const val METRES = """(?:m|metres?|meters?|metros?|meter)"""                                    // i18n-ok
    private val BAND_WORDS = Regex("""^(?:(?:bande|band|banda)\s+(?:de\s+|der\s+|des\s+|on\s+)?)?(\d{1,3})\s*$METRES(?:\s+band)?$""") // i18n-ok
    private val FREQ_WORDS = Regex(                                                                         // i18n-ok
        """^(?:frequence|qsy|accorde(?:r)?|aller(?:\s+sur)?|frequency|tune(?:\s+to)?|go\s+to|frequenz|gehe\s+(?:auf|zu)|""" + // i18n-ok
            """frecuencia|sintoniza(?:r)?|ir\s+a)\s+(.+)$""")                                                // i18n-ok
    private val MEMORY_WORDS = Regex(                                                                       // i18n-ok
        """^(?:memoire|canal|preselection|memory|channel|preset|speicher(?:platz)?|kanal|memoria|preseleccion|preajuste)\s+(.+)$""") // i18n-ok
    private val NUMBER = Regex(                                                                             // i18n-ok
        """^(\d[\d ]*(?:[.,]\d+)?)\s*(mhz|mega\s?hertz|megahercios?|khz|kilo\s?hertz|kilohercios?|hz|hertz|hercios?)?$""") // i18n-ok

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
        val unit = m.groupValues[2].replace(" ", "")
        val hz = when {
            unit == "mhz" || unit.startsWith("mega") -> value * 1e6
            unit == "khz" || unit.startsWith("kilo") -> value * 1e3
            unit.isNotEmpty() -> value
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

    /** Minuscules, sans accents ni ponctuation, espaces simples ; « mètres » -> « metres », « ß » -> « ss ». */
    fun normalize(text: String): String =
        Normalizer.normalize(text.lowercase().replace("ß", "ss"), Normalizer.Form.NFD)
            .replace(Regex("""\p{M}+"""), "")
            .replace(Regex("""[^a-z0-9.,]+"""), " ")
            .trim()
            .replace(Regex("""\s+"""), " ")
}
