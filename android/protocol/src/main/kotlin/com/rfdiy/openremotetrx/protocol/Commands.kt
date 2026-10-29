// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Commandes envoyées à la station (docs/protocole.md § 6). « cmd » est TOUJOURS écrit en premier : la station
 * reconnaît layout_save et bug_report à leur début, avant toute analyse JSON. `id` = numéro de la REQUÊTE
 * (repris dans result) ; l'identifiant d'une mémoire s'appelle memory_id.
 *
 * Le PTT n'existe qu'en toggle (aucune commande « émettre tant que »), et `Stop` coupe toujours.
 */
sealed class Command(val name: String) {
    protected open fun JsonObjectBuilder.params() {}

    fun toJson(id: Int? = null): JsonObject = buildJsonObject {
        put("cmd", name)
        if (id != null) put("id", id)
        params()
    }

    fun encode(id: Int? = null): String = toJson(id).toString()

    data object Toggle : Command("toggle")
    data object Stop : Command("stop")
    data object Heartbeat : Command("heartbeat")
    data object GetState : Command("get_state")
    data object LocalRelease : Command("local_release")
    data object LayoutGet : Command("layout_get")
    data object LayoutReset : Command("layout_reset")

    data class SetFrequency(val hz: Long) : Command("set_frequency") {
        override fun JsonObjectBuilder.params() { put("hz", hz) }
    }

    /** passband 0 = largeur par défaut du mode. */
    data class SetMode(val mode: String, val passband: Int = 0) : Command("set_mode") {
        override fun JsonObjectBuilder.params() { put("mode", mode); if (passband != 0) put("passband", passband) }
    }

    data class SetSquelch(val value: Double) : Command("set_squelch") {
        override fun JsonObjectBuilder.params() { put("value", value) }
    }

    data class SetFunction(val function: String, val on: Boolean) : Command("set_function") {
        override fun JsonObjectBuilder.params() { put("name", function); put("on", on) }
    }

    /** Décalage du clarifieur : `RIT` (réception) ou `XIT` (ΔTX, émission), en Hz. Refusé pendant l'émission. */
    data class SetOffset(val offset: String, val hz: Int) : Command("set_offset") {
        override fun JsonObjectBuilder.params() { put("name", offset); put("hz", hz) }
    }

    /** Entier pour AGC, PREAMP, ATT ; nombre pour RFPOWER, NR, NB : la station distingue les deux. */
    data class SetLevel(val level: String, val value: Number) : Command("set_level") {
        override fun JsonObjectBuilder.params() { put("name", level); put("value", JsonPrimitive(value)) }
    }

    data class MemorySave(
        val memoryName: String, val hz: Long, val mode: String, val favorite: Boolean = false, val memoryId: String? = null,
    ) : Command("memory_save") {
        override fun JsonObjectBuilder.params() {
            put("name", memoryName); put("hz", hz); put("mode", mode)
            if (favorite) put("favorite", true)              // absent = non (défaut de la station)
            if (memoryId != null) put("memory_id", memoryId)
        }
    }

    data class MemoryDelete(val memoryId: String) : Command("memory_delete") {
        override fun JsonObjectBuilder.params() { put("memory_id", memoryId) }
    }

    data class MemoryRecall(val memoryId: String) : Command("memory_recall") {
        override fun JsonObjectBuilder.params() { put("memory_id", memoryId) }
    }

    data class LayoutSave(val profile: JsonObject) : Command("layout_save") {
        override fun JsonObjectBuilder.params() { put("profile", profile) }
    }

    data class SpectrumSet(val setting: String, val value: JsonPrimitive) : Command("spectrum_set") {
        override fun JsonObjectBuilder.params() { put("name", setting); put("value", value) }
    }

    data class SpectrumWatch(val on: Boolean) : Command("spectrum_watch") {
        override fun JsonObjectBuilder.params() { put("on", on) }
    }

    /** Réglages des bips de fin : roger_enabled, link_lost_enabled, roger_tone, roger_pattern (liste fermée). */
    data class BeepsSet(val changes: Map<String, JsonPrimitive>) : Command("beeps_set") {
        override fun JsonObjectBuilder.params() { changes.forEach { (k, v) -> put(k, v) } }
    }

    /** SELCALL de la station (squelch numérique par appel de groupe) : n'agit que sur le son reçu, jamais sur l'émission. */
    data class SelcallActivate(val code: String) : Command("selcall_activate") {
        override fun JsonObjectBuilder.params() { put("code", code) }
    }

    data object SelcallRearm : Command("selcall_rearm")

    data object SelcallDeactivate : Command("selcall_deactivate")

    /** `filterMode` : mute, attenuate, chime ; `attenuationDb` : 6 à 60 ; `sendOnTxEnd` : trame en fin d'émission. */
    data class SelcallOptions(val filterMode: String? = null, val attenuationDb: Int? = null, val sendOnTxEnd: Boolean? = null) :
        Command("selcall_options") {
        override fun JsonObjectBuilder.params() {
            filterMode?.let { put("filter_mode", it) }
            attenuationDb?.let { put("attenuation_db", it) }
            sendOnTxEnd?.let { put("send_on_tx_end", it) }
        }
    }

    /** Appel SELCALL manuel : une ÉMISSION de ce client (micro fermé, trame du code armé N fois) ; annuler = Stop. */
    data object SelcallSend : Command("selcall_send")

    /** Texte relu par l'utilisateur, sans mot de passe. */
    data class BugReport(val text: String) : Command("bug_report") {
        override fun JsonObjectBuilder.params() { put("text", text) }
    }

    companion object {
        /** Toutes les commandes connues de l'application : comparées à COMMANDS de la station par les tests. */
        val NAMES = setOf(
            "toggle", "stop", "heartbeat", "get_state", "set_frequency", "set_mode", "set_squelch", "set_function",
            "set_level", "memory_save", "memory_delete", "memory_recall", "layout_get", "layout_save", "layout_reset",
            "spectrum_set", "spectrum_watch", "beeps_set", "local_release", "bug_report", "set_offset",
            "selcall_activate", "selcall_rearm", "selcall_deactivate", "selcall_options", "selcall_send",
        )
    }
}
