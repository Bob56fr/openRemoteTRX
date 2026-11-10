// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import kotlinx.serialization.json.JsonArray
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
    data class SelcallOptions(
        val filterMode: String? = null, val attenuationDb: Int? = null, val sendOnTxEnd: Boolean? = null, val txLevelDbfs: Double? = null,
    ) : Command("selcall_options") {
        override fun JsonObjectBuilder.params() {
            filterMode?.let { put("filter_mode", it) }
            txLevelDbfs?.let { put("tx_level_dbfs", it) }
            attenuationDb?.let { put("attenuation_db", it) }
            sendOnTxEnd?.let { put("send_on_tx_end", it) }
        }
    }

    /** Appel SELCALL manuel : une ÉMISSION de ce client (micro fermé, trame du code armé N fois) ; annuler = Stop. */
    data object SelcallSend : Command("selcall_send")

    /** Réglage automatique du niveau de la trame d'après l'ALC : une ÉMISSION (ton par paliers) ; annuler = Stop. */
    data object SelcallCalibrate : Command("selcall_calibrate")

    /** Visiteurs : déconnecter un visiteur (OPÉRATEUR seulement ; `account` = identifiant du compte visiteur). */
    data class ListenerKick(val account: String) : Command("listener_kick") {
        override fun JsonObjectBuilder.params() { put("account", account) }
    }

    /** Visiteurs : commutateur « Écoute des visiteurs » de l'OPÉRATEUR (mémorisé sur la station). */
    data class ListenersOpen(val on: Boolean) : Command("listeners_open") {
        override fun JsonObjectBuilder.params() { put("on", on) }
    }

    /** Visiteurs : rouvrir l'écoute après une surcharge de la station (acceptée seulement au vert). */
    data object ListenersReopen : Command("listeners_reopen")

    /** Synthèse du matériel de la station (opérateurs, fonction « host ») : réponse `sections`. */
    data object HostInfo : Command("host_info")

    /** Profils d'égaliseur du compte rangés sur la station (opérateurs, fonction « voice_profiles ») : réponse `profiles`. */
    data object VoiceProfiles : Command("voice_profiles")

    /** Crée ou remplace (même nom) un profil d'égaliseur ; `settings` : format de VoiceEq.toJson, compact (< 2 048 octets). */
    data class VoiceProfileSave(val profile: String, val settings: JsonObject) : Command("voice_profile_save") {
        override fun JsonObjectBuilder.params() { put("name", profile); put("settings", settings) }
    }

    data class VoiceProfileDelete(val profile: String) : Command("voice_profile_delete") {
        override fun JsonObjectBuilder.params() { put("name", profile) }
    }

    /** Mesure de TOS (opérateurs, fonction « swr ») : plan affiché avant le lancement, n'émet rien. */
    data class SwrPlan(val lowHz: Long, val highHz: Long, val points: Int, val powerPct: Double) : Command("swr_plan") {
        override fun JsonObjectBuilder.params() { put("low_hz", lowHz); put("high_hz", highHz); put("points", points); put("power_pct", powerPct) }
    }

    /** Lance la mesure : chaque point est une prise d'émission NORMALE de ce téléphone (battements, TOT, STOP). */
    data class SwrStart(val lowHz: Long, val highHz: Long, val points: Int, val powerPct: Double) : Command("swr_start") {
        override fun JsonObjectBuilder.params() { put("low_hz", lowHz); put("high_hz", highHz); put("points", points); put("power_pct", powerPct) }
    }

    data object SwrCancel : Command("swr_cancel")

    data object SwrLast : Command("swr_last")

    /** Breizh Audio Box (opérateurs, fonction « breizh ») : volume retour (−20 à +6 dB, pas de 0,5) et/ou « Direct ».
     *  Pris à la PROCHAINE émission ; au moins un des deux. */
    data class BreizhSet(val returnGainDb: Double? = null, val bypass: Boolean? = null) : Command("breizh_set") {
        override fun JsonObjectBuilder.params() {
            if (returnGainDb != null) put("return_gain_db", returnGainDb)
            if (bypass != null) put("bypass", bypass)
        }
    }

    /** Reprendre Breizh après un repli (à la prochaine émission) : réponse `pending`. */
    data object BreizhReactivate : Command("breizh_reactivate")

    /** Journal de la liaison avec Breizh : réponse `entries` (50 derniers événements). */
    data object BreizhLog : Command("breizh_log")

    /** Sonde de qualité réseau (fonction « netprobe », docs/protocole.md § 15) : mesure et affiche, n'agit jamais sur
     *  l'émission. net_ping / net_pong / net_report : sans réponse. `t`, `tr` : horloge monotone en ms ; `w` : heure Unix. */
    data class NetPing(val seq: Int, val t: Long, val w: Long? = null) : Command("net_ping") {
        override fun JsonObjectBuilder.params() { put("seq", seq); put("t", t); if (w != null) put("w", w) }
    }

    data class NetPong(val seq: Int, val t: Long, val tr: Long) : Command("net_pong") {
        override fun JsonObjectBuilder.params() { put("seq", seq); put("t", t); put("tr", tr) }
    }

    /** Résumé de 10 s (champs : docs/protocole.md § 15). */
    data class NetReport(val report: JsonObject) : Command("net_report") {
        override fun JsonObjectBuilder.params() { put("report", report) }
    }

    /** 10 dernières minutes après une reconnexion (opérateurs ; message long reconnu à son début). */
    data class NetBacklog(val reports: JsonArray) : Command("net_backlog") {
        override fun JsonObjectBuilder.params() { put("reports", reports) }
    }

    data class NetStats(val days: Int = 30, val device: String? = null) : Command("net_stats") {
        override fun JsonObjectBuilder.params() { put("days", days); if (device != null) put("device", device) }
    }

    data object NetClear : Command("net_clear")

    /** Seuils de l'indicateur choisis pour un type de réseau, ou `reset` = retour aux valeurs de station.toml. */
    data class NetThresholds(val netType: String, val rttWarn: Number? = null, val rttAlert: Number? = null,
                             val lossWarn: Number? = null, val lossAlert: Number? = null, val reset: Boolean = false) : Command("net_thresholds") {
        override fun JsonObjectBuilder.params() {
            put("net_type", netType)
            if (reset) { put("reset", true); return }
            put("rtt_warn", rttWarn); put("rtt_alert", rttAlert); put("loss_warn", lossWarn); put("loss_alert", lossAlert)
        }
    }

    data class NetVpnIgnore(val address: String) : Command("net_vpn_ignore") {
        override fun JsonObjectBuilder.params() { put("address", address) }
    }

    /** Export anonyme (zip) par morceaux : part = 0 fabrique un nouvel export ; réponse name, part, parts, size, data. */
    data class NetExport(val part: Int = 0) : Command("net_export") {
        override fun JsonObjectBuilder.params() { put("part", part) }
    }

    /** Présence de groupe « Amis » (fonction « friends », docs/protocole.md § 16) : relayée au module « presence » de
     *  la station, qui n'agit JAMAIS sur le poste ; `args` vérifié par le module. Réponse `action`, `data`. */
    data class Friends(val action: String, val args: JsonObject? = null) : Command("friends") {
        override fun JsonObjectBuilder.params() { put("action", action); if (args != null) put("args", args) }
    }

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
            "selcall_activate", "selcall_rearm", "selcall_deactivate", "selcall_options", "selcall_send", "selcall_calibrate",
            "listener_kick", "listeners_reopen", "listeners_open", "host_info",
            "voice_profiles", "voice_profile_save", "voice_profile_delete", "swr_plan", "swr_start", "swr_cancel", "swr_last",
            "breizh_set", "breizh_reactivate", "breizh_log",
            "net_ping", "net_pong", "net_report", "net_backlog", "net_stats", "net_clear", "net_thresholds", "net_vpn_ignore",
            "net_export", "friends",
        )

        /** Seules commandes qu'un compte VISITEUR envoie (la station refuserait le reste). */
        val LISTENER = setOf("get_state", "spectrum_watch", "net_ping", "net_pong", "net_report")
    }
}
