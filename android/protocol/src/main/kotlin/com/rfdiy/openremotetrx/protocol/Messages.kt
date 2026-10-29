// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject

/** Messages reçus de la station (docs/protocole.md § 8). Un champ ou un type inconnu est ignoré, jamais une erreur. */
sealed interface ServerMessage

@Serializable
data class Capabilities(
    val model: Int = 0,
    @SerialName("model_name") val modelName: String = "",
    val manufacturer: String = "",
    val modes: List<String> = emptyList(),
    @SerialName("can_set_frequency") val canSetFrequency: Boolean = true,
    @SerialName("can_get_frequency") val canGetFrequency: Boolean = true,
    @SerialName("can_set_mode") val canSetMode: Boolean = true,
    @SerialName("can_get_mode") val canGetMode: Boolean = true,
    @SerialName("can_get_ptt") val canGetPtt: Boolean = false,
    @SerialName("has_s_meter") val hasSMeter: Boolean = false,
    val functions: List<String> = emptyList(),
    val levels: List<String> = emptyList(),
    val complete: Boolean = false,
    val filters: Map<String, List<Int>> = emptyMap(),
    val preamps: List<Int> = emptyList(),
    val attenuators: List<Int> = emptyList(),
    @SerialName("level_ranges") val levelRanges: Map<String, List<Double>> = emptyMap(),
    /** Split lisible (« Can get Split VFO ») ; null = non déclaré. */
    @SerialName("can_get_split") val canGetSplit: Boolean? = null,
    /** Décalages maximaux du clarifieur (Hz) ; 0 = inconnu. */
    @SerialName("max_rit_hz") val maxRitHz: Int = 0,
    @SerialName("max_xit_hz") val maxXitHz: Int = 0,
)

@Serializable
data class Memory(
    val id: String,
    val name: String,
    val hz: Long,
    val mode: String,
    val favorite: Boolean = false,
)

@Serializable
data class SpectrumCapability(
    val source: String = "",
    @SerialName("level_max") val levelMax: Int = 0,
    @SerialName("max_fps") val maxFps: Int = 0,
)

@Serializable
data class Hello(
    val protocol: Int,
    @SerialName("client_id") val clientId: String,
    val version: String = "",
    val capabilities: Capabilities? = null,
    @SerialName("tx_modes") val txModes: List<String> = emptyList(),
    @SerialName("max_power_w") val maxPowerW: Int = 0,
    val memories: List<Memory> = emptyList(),
    val layouts: Boolean = false,
    val spectrum: SpectrumCapability? = null,
    val beeps: JsonObject? = null,
    /** État du SELCALL de la station (comme le message `selcall`), null si la station ne l'offre pas. */
    val selcall: JsonObject? = null,
    val features: List<String> = emptyList(),
) : ServerMessage {
    fun offers(feature: String): Boolean = feature in features
}

/** État de l'émission, tel que la station le publie : c'est LUI qui s'affiche, jamais un état supposé. */
@Serializable
data class PttStatus(
    val state: String = "RX",
    val owner: String? = null,
    @SerialName("tot_remaining_s") val totRemainingS: Double? = null,
    @SerialName("tot_warning") val totWarning: Boolean = false,
    @SerialName("last_cut_reason") val lastCutReason: String = "",
    val fault: String = "",
    @SerialName("local_remaining_s") val localRemainingS: Double? = null,
    @SerialName("local_reason") val localReason: String = "",
    @SerialName("local_tx") val localTx: Boolean = false,
    @SerialName("temp_alert") val tempAlert: String = "",
    @SerialName("temp_c") val tempC: Double? = null,
    /** Seulement dans les réponses (result.ptt) ; indicatif. */
    val event: String = "",
)

@Serializable
data class RigStatus(
    val connected: Boolean = false,
    @SerialName("frequency_hz") val frequencyHz: Long? = null,
    val mode: String? = null,
    @SerialName("passband_hz") val passbandHz: Int? = null,
    @SerialName("strength_db") val strengthDb: Double? = null,
    val functions: Map<String, Boolean> = emptyMap(),
    val levels: Map<String, Double> = emptyMap(),
    /** Split en service ; null = inconnu (poste qui ne le dit pas). */
    val split: Boolean? = null,
    /** Fréquence d'ÉMISSION en split ; null hors split. */
    @SerialName("tx_frequency_hz") val txFrequencyHz: Long? = null,
    /** Décalages du clarifieur : « RIT », « XIT » (ΔTX) en Hz. */
    val offsets: Map<String, Int> = emptyMap(),
    /** VFO actif tel que Hamlib le nomme (VFOA, VFOB, MEM, Main, Sub) ; null = non lisible (IC-7300MK2). Station 0.65.0+. */
    val vfo: String? = null,
)

@Serializable
data class State(
    val ptt: PttStatus = PttStatus(),
    val rig: RigStatus = RigStatus(),
    val audio: JsonObject = JsonObject(emptyMap()),
    val clients: List<String> = emptyList(),
    val spectrum: JsonObject = JsonObject(emptyMap()),
) : ServerMessage

/** Réponse à une commande ; `raw` garde les champs propres à chaque commande (memory, settings, profile…). */
data class Result(
    val id: Int?,
    val ok: Boolean,
    val reason: String,
    val detail: String,
    val ptt: PttStatus?,
    val raw: JsonObject,
) : ServerMessage

/** Message illisible pour la station (sans id) : too_large, bad_json, unknown_command, invalid_params, rate_limited… */
data class ErrorMessage(val code: String, val detail: String) : ServerMessage

data class Memories(val items: List<Memory>) : ServerMessage

data class Beeps(val settings: JsonObject) : ServerMessage

/** État du SELCALL changé (commande d'un client, appel reçu). */
data class Selcall(val status: JsonObject) : ServerMessage

data class ModuleMessage(val module: String, val data: JsonElement) : ServerMessage

/** Type inconnu de cette version de l'application : ignoré (une station plus récente peut en ajouter). */
data class Unknown(val type: String) : ServerMessage

object ServerMessages {
    val json = Json {
        ignoreUnknownKeys = true      // une station plus récente peut ajouter des champs
        coerceInputValues = true      // null reçu pour un champ non nul : sa valeur par défaut
        isLenient = false
    }

    /** Décode un message du canal « control ». ProtocolException si ce n'est pas un objet JSON avec « type ». */
    fun decode(text: String): ServerMessage {
        val obj = try {
            json.parseToJsonElement(text).jsonObject
        } catch (e: IllegalArgumentException) {
            throw ProtocolException("message illisible de la station", e)
        }
        val type = (obj["type"] as? JsonPrimitive)?.contentOrNull ?: throw ProtocolException("message sans type")
        return try {
            when (type) {
                "hello" -> json.decodeFromJsonElement<Hello>(obj)
                "state" -> json.decodeFromJsonElement<State>(obj)
                "result" -> Result(
                    id = (obj["id"] as? JsonPrimitive)?.intOrNull,
                    ok = (obj["ok"] as? JsonPrimitive)?.contentOrNull == "true",
                    reason = obj.text("reason"),
                    detail = obj.text("detail"),
                    ptt = obj["ptt"]?.takeIf { it !is JsonNull }?.let { json.decodeFromJsonElement<PttStatus>(it) },
                    raw = obj,
                )
                "error" -> ErrorMessage(obj.text("code"), obj.text("detail"))
                "memories" -> Memories(json.decodeFromJsonElement<List<Memory>>(obj["items"] ?: JsonArray(emptyList())))
                "beeps" -> Beeps(obj["settings"]?.jsonObject ?: JsonObject(emptyMap()))
                "selcall" -> Selcall(obj["status"]?.jsonObject ?: JsonObject(emptyMap()))
                "module" -> ModuleMessage(obj.text("module"), obj["data"] ?: JsonNull)
                else -> Unknown(type)
            }
        } catch (e: SerializationException) {
            throw ProtocolException("message « $type » mal formé", e)
        } catch (e: IllegalArgumentException) {
            throw ProtocolException("message « $type » mal formé", e)
        }
    }

    private fun JsonObject.text(key: String): String = (this[key] as? JsonPrimitive)?.contentOrNull ?: ""
}

class ProtocolException(message: String, cause: Throwable? = null) : Exception(message, cause)
