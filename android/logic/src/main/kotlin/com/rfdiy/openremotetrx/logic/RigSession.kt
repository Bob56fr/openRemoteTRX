// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Beeps
import com.rfdiy.openremotetrx.protocol.BreizhEvent
import com.rfdiy.openremotetrx.protocol.Bye
import com.rfdiy.openremotetrx.protocol.Command
import com.rfdiy.openremotetrx.protocol.ErrorMessage
import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.Memory
import com.rfdiy.openremotetrx.protocol.Memories
import com.rfdiy.openremotetrx.protocol.ModuleMessage
import com.rfdiy.openremotetrx.protocol.NetEvent
import com.rfdiy.openremotetrx.protocol.NetPing
import com.rfdiy.openremotetrx.protocol.NetPong
import com.rfdiy.openremotetrx.protocol.Protocol
import com.rfdiy.openremotetrx.protocol.ProtocolException
import com.rfdiy.openremotetrx.protocol.Result
import com.rfdiy.openremotetrx.protocol.Selcall
import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import com.rfdiy.openremotetrx.protocol.SwrMessage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

enum class LinkStatus { DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING }

/** Sons de liaison (mêmes notes que la page) : perdue, rétablie, perdue pour de bon. */
enum class LinkAlert { LOST, RESTORED, FAILED, SELCALL_CALL,
    /** Breizh Audio Box perdu pendant MON émission : repli en direct (bip court du téléphone, jamais de la station). */
    BREIZH_FALLBACK }

enum class LogLevel { INFO, WARN, BAD }

data class LogLine(val atMs: Long, val text: String, val level: LogLevel)

data class ReconnectInfo(val remainingS: Int, val attempts: Int, val windowS: Int, val lastError: String)

/** Ce que l'écran, la notification et (plus tard) la voiture affichent. Une seule source : RigSession. */
data class RigState(
    val status: LinkStatus = LinkStatus.DISCONNECTED,
    val hello: Hello? = null,
    val state: State? = null,
    val ptt: PttView? = null,
    val armed: Boolean = false,
    /** Faux si la station parle une autre version du protocole : réception et STOP seulement. */
    val protocolOk: Boolean = true,
    val reconnect: ReconnectInfo? = null,
    val rttMs: Int? = null,
    val log: List<LogLine> = emptyList(),
    /** Mémoires partagées de la station, favorites d'abord. */
    val memories: List<Memory> = emptyList(),
    /** Dernière fréquence et dernier mode par bande (gardés sur le téléphone). */
    val bandSpots: Map<String, BandSpot> = emptyMap(),
    /** Spots du Cluster DX reçus (vue du spectre ouverte), triés par fréquence. */
    val spots: List<Spot> = emptyList(),
    /** Santé des sources du Cluster DX (« green », « orange », « red », « off »), null = module muet. */
    val clusterHealth: String? = null,
    /** Dernier état des flux du Cluster DX (`cluster_status`) et son heure de réception (ms, horloge murale). */
    val clusterStatus: JsonObject? = null,
    val clusterStatusAtMs: Long = 0,
    /** 30 derniers spots toutes bandes (message « recent » du cluster, vue du spectre ou liste ouverte), le plus récent en tête. */
    val recentSpots: List<Spot> = emptyList(),
    /** SELCALL de la station (null : station sans SELCALL). */
    val selcall: SelcallStatus? = null,
    /** Compte VISITEUR (hello.role) : réception seule, commandes inertes. */
    val listener: Boolean = false,
    /** Visiteurs connectés, attente de l'opérateur, surcharge (state.presence) ; null = rien de la station. */
    val presence: PresenceUi? = null,
    /** Bips de fin d'émission de la station (null : station sans bips). */
    val beeps: BeepSettings? = null,
    /** Santé de la machine de la station (state.host) : petit bargraph ; null = visiteur ou station plus ancienne. */
    val host: HostHealth? = null,
    /** Synthèse du matériel (host_info) : null = pas demandée ou en cours ; vide = indisponible. */
    val hostSections: List<HostSection>? = null,
    /** Profils d'égaliseur du compte rangés sur la station ; null = station sans cette fonction (ou visiteur). */
    val voiceProfiles: List<VoiceProfile>? = null,
    /** Mesure de TOS : progression de MA mesure (messages « swr »), plan de la station, derniers choix, dernière mesure. */
    val swr: SwrProgress? = null,
    val swrPlan: SwrPlanView? = null,
    val swrChoices: Pair<Double, Int>? = null,
    val swrLast: SwrResult? = null,
    /** Breizh Audio Box (state.breizh) : null = station sans Breizh, ou visiteur. */
    val breizh: BreizhView? = null,
    /** Journal de la liaison avec Breizh (relu à la connexion, complété par breizh_event), le plus ancien en tête. */
    val breizhEvents: List<BreizhEntry> = emptyList(),
    /** Sonde réseau : la liaison de CE téléphone (state.net) ; null = station sans sonde. */
    val net: NetUi.View? = null,
    /** Statistiques de la sonde (net_stats) ; null = pas demandées ; `netStatus` = texte d'état (lecture, refus, export). */
    val netStats: NetUi.Stats? = null,
    val netStatus: String = "",
)

/** Profil d'égaliseur de l'opérateur, rangé sur la station (étape 102) ; `settings` revalidé à l'application. */
data class VoiceProfile(val name: String, val settings: JsonObject) {
    /** Réglages du profil, revalidés comme un fichier importé. */
    fun voiceSettings(): VoiceSettings = VoiceEq.validate(settings)
}

/**
 * Ce que la session demande à la couche Android (WebRTC). Appelé sur le fil de la session uniquement.
 * `close()` ferme la liaison SANS rappeler `onLinkClosed`.
 */
interface SessionLink {
    fun startAttempt()
    fun send(text: String): Boolean
    fun setMicOpen(open: Boolean)
    fun close()
    fun alert(kind: LinkAlert)
}

/**
 * Session avec la station, reprise de la page (client.js, TrxClient) : messages, battements, micro, surveillance
 * de la liaison, reconnexion automatique, commandes en attente. Kotlin pur, piloté par des appels datés (`now` en
 * millisecondes monotones) : RigService l'appelle depuis UN seul fil, et les tests de panne la pilotent sans réseau.
 *
 * Sécurité : l'émission affichée vient TOUJOURS de `state.ptt` ; le micro n'est ouvert qu'en TX confirmé de ce
 * téléphone ; après une reconnexion, le téléphone est en réception et désarmé ; STOP est toujours permis.
 */
class RigSession(
    private val link: SessionLink,
    bandSpots: Map<String, BandSpot> = emptyMap(),
    /** Type de réseau du téléphone pour la sonde (lan, wifi, 4g, 5g, mobile, unknown) ; null = inconnu. */
    private val netType: () -> String? = { null },
    private val wall: () -> Long = System::currentTimeMillis,
) {
    /** Export anonyme de la sonde reçu en entier : (nom du fichier, contenu du zip), à partager par l'application. */
    var onNetExport: ((String, ByteArray) -> Unit)? = null
    var snapshot = RigState()
        private set
    var onChange: ((RigState) -> Unit)? = null
    /** Mémoire des bandes modifiée : à enregistrer par l'application. */
    var onBandSpots: ((Map<String, BandSpot>) -> Unit)? = null
    private var bands = BandMemory(bandSpots)
    private var memories: List<Memory> = emptyList()
    private var spectrumWanted = false
    private val spotBook = SpotBook()
    private var clusterHealth: String? = null
    private var clusterStatus: JsonObject? = null
    private var clusterStatusAt = 0L
    private var beeps: BeepSettings? = null
    private var recentSpots: List<Spot> = emptyList()
    private var selcall: SelcallStatus? = null
    private var hostSections: List<HostSection>? = null
    private var voiceProfiles: List<VoiceProfile>? = null
    private var swr: SwrProgress? = null
    private var swrPlan: SwrPlanView? = null
    private var swrChoices: Pair<Double, Int>? = null
    private var swrLast: SwrResult? = null
    private var breizhEvents: List<BreizhEntry> = emptyList()
    private val net = NetClient()
    private var netOffered = false                   // la station a annoncé « netprobe » à la dernière connexion
    private var netStats: NetUi.Stats? = null
    private var netStatus = ""
    private var netExport: Pair<String, java.io.ByteArrayOutputStream>? = null

    private var status = LinkStatus.DISCONNECTED
    private var attemptActive = false
    private var helloDeadline: Long? = null
    private var windowS = 0
    private var reconnect: ReconnectPolicy? = null
    private var lastReconnectAlert = 0L
    private var lastAttemptError = ""
    private val heartbeat = HeartbeatPolicy()
    private var bye: Bye? = null                     // « bye » reçu : la fermeture qui suit ne relance pas de reconnexion
    private var lastForbiddenLog = Long.MIN_VALUE / 2
    private val watch = LinkWatch()
    private val arming = TxArming()
    private var silenceAlerted = false
    private var hello: Hello? = null
    private var state: State? = null
    private var protocolOk = true
    private var nextId = 1
    private val pending = LinkedHashMap<Int, Pending>()
    private var lastPing = Long.MIN_VALUE
    private var rttMs: Int? = null
    private val log = ArrayDeque<LogLine>()

    private class Pending(val cmd: String, val sentAt: Long)

    val connected: Boolean get() = status == LinkStatus.CONNECTED

    // ------------------------------------------------------------------ connexion

    /**
     * Connexion demandée par l'utilisateur. `windowS` : fenêtre de reconnexion automatique (0 = aucune) ;
     * `bandSpots` : mémoire des bandes de CETTE station (null = garder l'actuelle).
     */
    fun begin(now: Long, windowS: Int, bandSpots: Map<String, BandSpot>? = null) {
        if (bandSpots != null) bands = BandMemory(bandSpots)
        teardown()
        reconnect = null
        this.windowS = windowS.coerceIn(0, ReconnectPolicy.MAX_WINDOW_S)
        status = LinkStatus.CONNECTING
        attemptActive = true
        link.startAttempt()
        publish()
    }

    /** La station a accepté l'offre : le canal doit maintenant s'ouvrir (« hello »). */
    fun answered(now: Long) {
        if (!attemptActive) return
        helloDeadline = now + if (reconnect != null) ReconnectPolicy.HELLO_TIMEOUT_MS else HELLO_TIMEOUT_MS
    }

    /** Essai échoué avant « hello » : code de Texts.LOSSES (auth, busy, network, http, pin, no_hello, client_error…). */
    fun attemptFailed(now: Long, code: String, detail: String = "") {
        if (!attemptActive) return
        attemptActive = false
        helloDeadline = null
        link.setMicOpen(false)
        link.close()
        val text = Texts.loss(code) + if (detail.isNotBlank()) " ($detail)" else ""
        val r = reconnect
        if (r != null) {
            lastAttemptError = text
            // identifiants refusés, ou accès refusé (visiteurs) : on n'insiste jamais
            if (r.attemptFailed(now, authRefused = code == "auth" || code == "refused") == ReconnectOutcome.AUTH) {
                giveUp(now, if (code == "refused") "accès refusé par la station" + (if (detail.isNotBlank()) " ($detail)" else "")
                            else "identifiants refusés par la station")
            }
            publish(now)
            return
        }
        status = LinkStatus.DISCONNECTED
        log("Connexion impossible : $text.", LogLevel.BAD)
        publish(now)
    }

    /** Liaison fermée par le réseau ou la station (canal fermé, ICE échoué, silence…). */
    fun onLinkClosed(now: Long, code: String) {
        if (!connected) {
            if (attemptActive) attemptFailed(now, code)
            return
        }
        val mine = mineActive()
        val farewell = bye
        teardown()
        val title = Texts.loss(code)
        if (farewell != null) {                                  // la station a dit pourquoi : pas de reconnexion automatique
            status = LinkStatus.DISCONNECTED
            log("La station a fermé la connexion : ${farewell.message.ifBlank { farewell.reason }}", LogLevel.BAD)
            link.alert(LinkAlert.FAILED)
        } else if (windowS > 0) {
            reconnect = ReconnectPolicy(windowS, now)
            lastReconnectAlert = now
            lastAttemptError = ""
            status = LinkStatus.RECONNECTING
            log("Connexion perdue : $title." + (if (mine) " Ton émission est coupée par la station." else "") +
                " Reconnexion automatique pendant $windowS s.", LogLevel.BAD)
            link.alert(LinkAlert.LOST)
        } else {
            status = LinkStatus.DISCONNECTED
            log("Connexion perdue : $title. L'émission éventuelle est coupée par la station.", LogLevel.BAD)
            link.alert(LinkAlert.FAILED)
        }
        publish(now)
    }

    /** Déconnexion voulue : jamais de reconnexion automatique. */
    fun disconnect(now: Long) {
        val was = status != LinkStatus.DISCONNECTED
        teardown()
        reconnect = null
        net.forget()
        netOffered = false
        status = LinkStatus.DISCONNECTED
        if (was) log("Déconnecté.", LogLevel.INFO)
        publish(now)
    }

    // ------------------------------------------------------------------ messages de la station

    fun onMessage(now: Long, text: String) {
        if (!attemptActive && !connected) return
        val msg = try {
            ServerMessages.decode(text)
        } catch (e: ProtocolException) {
            return                                              // message illisible : ignoré, comme la page
        }
        watch.onMessage(now)
        if (silenceAlerted) {
            silenceAlerted = false
            log("La station répond de nouveau.", LogLevel.INFO)
            link.alert(LinkAlert.RESTORED)
        }
        when (msg) {
            is Hello -> onHello(now, msg)
            is State -> {
                state = msg
                afterState()
                if (bands.observe(now, msg.rig.frequencyHz, msg.rig.mode)) onBandSpots?.invoke(bands.spots)
            }
            is Result -> onResult(now, msg)
            is ErrorMessage -> log("Erreur de la station : ${msg.code}" + (if (msg.detail.isNotEmpty()) " (${msg.detail})" else ""), LogLevel.WARN)
            is Memories -> memories = Radio.sortMemories(msg.items)
            is Beeps -> beeps = BeepSettings.parse(msg.settings)
            is Selcall -> onSelcall(SelcallStatus.parse(msg.status))
            is BreizhEvent -> onBreizhEvent(msg)
            is NetPing -> link.send(Command.NetPong(msg.seq, msg.t, now).encode())      // écho immédiat, sans file d'attente
            is NetPong -> net.pong(msg.seq, msg.t, now)
            is NetEvent -> onNetEvent(msg)
            is SwrMessage -> {
                val p = SwrUi.progress(msg.raw)
                swr = p
                p.result?.let { if (it.points.any { pt -> pt.swr != null }) swrLast = it }
            }
            is Bye -> {
                bye = msg
                log("La station va fermer la connexion : ${msg.message.ifBlank { msg.reason }}", LogLevel.BAD)
            }
            is ModuleMessage -> {                                       // spots et santé du cluster ; autres modules : ignorés ici
                spotBook.apply(msg.data, wall())
                Spots.recentOf(msg.data, wall())?.let { recentSpots = it }
                if (msg.module == "cluster") {
                    val data = msg.data as? JsonObject
                    (data?.get("health") as? JsonPrimitive)?.contentOrNull?.let { clusterHealth = it }
                    if ((data?.get("kind") as? JsonPrimitive)?.contentOrNull == "cluster_status") {
                        clusterStatus = data
                        clusterStatusAt = wall()
                    }
                }
            }
            else -> Unit                                         // type inconnu ou non affiché : ignoré
        }
        publish(now)
    }

    private fun onHello(now: Long, msg: Hello) {
        helloDeadline = null
        attemptActive = false
        hello = msg
        beeps = BeepSettings.parse(msg.beeps)
        selcall = SelcallStatus.parse(msg.selcall)
        memories = Radio.sortMemories(msg.memories)
        status = LinkStatus.CONNECTED
        // La station oublie l'abonnement avec la connexion : on le redemande si la vue du spectre est ouverte.
        if (spectrumWanted && msg.spectrum != null && msg.protocol == Protocol.VERSION) send(now, Command.SpectrumWatch(true))
        // Profils d'égaliseur de ce compte (opérateur) : relus à chaque connexion
        voiceProfiles = null
        if (msg.protocol == Protocol.VERSION && !msg.listener && msg.offers("voice_profiles")) send(now, Command.VoiceProfiles)
        // Journal de la liaison avec Breizh Audio Box : relu sur la station à chaque connexion
        breizhEvents = emptyList()
        if (msg.protocol == Protocol.VERSION && !msg.listener && msg.offers("breizh")) send(now, Command.BreizhLog)
        arming.onConnected()                                     // toujours désarmé à la connexion
        lastPing = now
        // Sonde réseau : battement et résumés si la station l'annonce ; résumés d'avant la coupure remis (opérateurs)
        netOffered = msg.protocol == Protocol.VERSION && msg.offers("netprobe")
        if (netOffered) {
            net.start(now)
            val backlog = net.backlog()
            if (backlog.isNotEmpty() && !msg.listener) send(now, Command.NetBacklog(kotlinx.serialization.json.JsonArray(backlog)))
        }
        protocolOk = msg.protocol == Protocol.VERSION
        if (!protocolOk) {
            log("La station parle le protocole ${msg.protocol}, l'application le ${Protocol.VERSION} : réception et STOP seulement. Mets à jour l'application ou la station.", LogLevel.BAD)
        } else {
            log("Connecté à la station" + (if (msg.version.isNotEmpty()) " ${msg.version}" else "") + ".", LogLevel.INFO)
        }
        val r = reconnect
        if (r != null) {
            reconnect = null
            log("Reconnecté après ${r.elapsedS(now)} s (${r.attempts} essai${if (r.attempts > 1) "s" else ""}). Réactive « Émission autorisée » pour émettre.", LogLevel.INFO)
            link.alert(LinkAlert.RESTORED)                       // la station est en RÉCEPTION : rien ne reprend tout seul
        }
        afterState()
    }

    private fun onResult(now: Long, msg: Result) {
        val entry = msg.id?.let { pending.remove(it) } ?: return
        if (entry.cmd == "get_state") {
            rttMs = (now - entry.sentAt).toInt()
            return
        }
        if (entry.cmd.startsWith("swr_")) {                     // mesure de TOS : plan, derniers choix, dernière mesure
            if (msg.ok) {
                (msg.raw["plan"] as? JsonObject)?.let { if (entry.cmd == "swr_plan") swrPlan = SwrUi.planView(it) }
                (msg.raw["choices"] as? JsonObject)?.let { c ->
                    val power = (c["power_pct"] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()
                    val points = (c["points"] as? JsonPrimitive)?.contentOrNull?.toIntOrNull()
                    if (power != null && points != null) swrChoices = power to points
                }
                if (entry.cmd == "swr_last") SwrUi.result(msg.raw["last"])?.let { swrLast = it }
            } else {
                log("Mesure de TOS : " + Texts.refusal(msg.reason, msg.detail), LogLevel.WARN)
                if (entry.cmd == "swr_start") swr = null
            }
            publish(now)
            return
        }
        if (entry.cmd.startsWith("voice_profile")) {              // liste à jour après lecture, ajout ou suppression
            if (msg.ok) voiceProfiles = parseVoiceProfiles(msg.raw["profiles"]) ?: voiceProfiles
            else log("Profils de voix : " + msg.detail.ifEmpty { Texts.refusal(msg.reason, msg.detail) }, LogLevel.WARN)
            publish(now)
            return
        }
        if (entry.cmd.startsWith("breizh_")) {                  // Breizh Audio Box : journal, réactivation, réglages
            if (!msg.ok) {
                log("Breizh : " + Texts.refusal(msg.reason, msg.detail), LogLevel.WARN)
            } else if (entry.cmd == "breizh_log") {
                (msg.raw["entries"] as? kotlinx.serialization.json.JsonArray)?.let { list ->
                    breizhEvents = list.mapNotNull { item ->
                        val o = item as? JsonObject ?: return@mapNotNull null
                        fun f(k: String) = (o[k] as? JsonPrimitive)?.contentOrNull
                        val event = f("event") ?: return@mapNotNull null
                        BreizhEntry(f("t").orEmpty(), event, f("detail").orEmpty().take(300))
                    }.takeLast(Breizhs.EVENTS_MAX)
                }
            } else if (entry.cmd == "breizh_reactivate") {
                val pending = (msg.raw["pending"] as? JsonPrimitive)?.contentOrNull == "true"
                log(if (pending) "Breizh sera repris dès qu'il répondra (à la prochaine émission)." else "Breizh repris : la prochaine émission passera par Breizh.", LogLevel.INFO)
            }
            publish(now)
            return
        }
        if (entry.cmd.startsWith("net_")) {
            onNetResult(now, entry.cmd, msg)
            publish(now)
            return
        }
        if (entry.cmd == "host_info") {                         // synthèse du matériel : affichée telle quelle
            hostSections = if (msg.ok) HostSection.parse(msg.raw["sections"]).orEmpty() else emptyList()
            publish(now)
            return
        }
        if (!msg.ok) {
            if (entry.cmd == "toggle") heartbeat.cancelGrace()
            log(Texts.refusal(msg.reason, msg.detail), LogLevel.WARN)
        }
    }

    private fun onBreizhEvent(msg: BreizhEvent) {
        if (msg.event.isEmpty() || msg.detail.isEmpty()) return
        val entry = BreizhEntry.of(msg)
        breizhEvents = (breizhEvents + entry).takeLast(Breizhs.EVENTS_MAX)
        val alarm = entry.event == "fallback" && mineActive()
        log("Breizh Audio Box : " + entry.detail, if (alarm) LogLevel.BAD else if (entry.warn) LogLevel.WARN else LogLevel.INFO)
        if (alarm) link.alert(LinkAlert.BREIZH_FALLBACK)
    }

    private fun onNetEvent(msg: NetEvent) {
        if (msg.event == "outage") {
            val o = msg.raw["outage"] as? JsonObject ?: return
            val ms = (o["duration_ms"] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull() ?: 0.0
            val diag = (o["diagnosis"] as? JsonPrimitive)?.contentOrNull
            val agent = (o["agent"] as? JsonPrimitive)?.contentOrNull.orEmpty()
            log("Coupure réseau de ${NetUi.duration(ms / 1000)}" + (if (agent.isNotEmpty()) " ($agent)" else "") +
                " — tronçon probable : ${NetUi.DIAGNOSES[diag] ?: "indéterminé"}.", LogLevel.WARN)
        } else if (msg.event == "vpn_shared") {
            val w = msg.raw["warning"] as? JsonObject ?: return
            val warning = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
                .decodeFromJsonElement(com.rfdiy.openremotetrx.protocol.NetVpnWarning.serializer(), w)
            log(NetUi.vpnText(warning), LogLevel.BAD)
        }
    }

    private fun onNetResult(now: Long, cmd: String, msg: Result) {
        if (!msg.ok) {
            netStatus = when (cmd) {
                "net_stats" -> "Statistiques indisponibles : "
                "net_export" -> "Export impossible : "
                else -> "Refusé : "
            } + Texts.refusal(msg.reason, msg.detail)
            if (cmd == "net_export") netExport = null
            return
        }
        when (cmd) {
            "net_stats" -> {
                netStats = NetUi.stats(msg.raw["stats"] as? JsonObject)
                netStatus = if (netStats != null) "Mesures de tous les appareils ; heures locales de la station." else "Réponse illisible."
            }
            "net_clear" -> { netStatus = "Historique réseau effacé (les seuils choisis sont gardés)."; netStats(now) }
            "net_thresholds" -> { netStatus = "Seuils enregistrés sur la station."; netStats(now) }
            "net_vpn_ignore" -> netStatus = "Avertissement ignoré pour cette adresse."
            "net_export" -> {
                val current = netExport ?: return
                val data = (msg.raw["data"] as? JsonPrimitive)?.contentOrNull ?: return
                current.second.write(java.util.Base64.getDecoder().decode(data))
                val part = (msg.raw["part"] as? JsonPrimitive)?.contentOrNull?.toIntOrNull() ?: 0
                val parts = (msg.raw["parts"] as? JsonPrimitive)?.contentOrNull?.toIntOrNull() ?: 1
                val name = (msg.raw["name"] as? JsonPrimitive)?.contentOrNull?.replace(Regex("[^\\w.-]"), "_") ?: "openremotetrx-reseau.zip"
                if (part + 1 < parts && part < 99) {
                    netExport = name to current.second
                    send(now, Command.NetExport(part + 1))
                } else {
                    netExport = null
                    netStatus = "Export prêt : $name (anonyme)."
                    onNetExport?.invoke(name, current.second.toByteArray())
                }
            }
        }
    }

    private fun afterState() {
        link.setMicOpen(mineTx())                               // micro ouvert seulement en TX confirmé de ce téléphone
    }

    // ------------------------------------------------------------------ minuterie (toutes les 400 ms)

    fun tick(now: Long, online: Boolean) {
        val r = reconnect
        if (r != null && netOffered) net.offline(now, wall(), netType())    // résumés hors ligne, remis au retour
        if (r != null && !attemptActive) {
            if (r.expired(now)) {
                giveUp(now, "plus de liaison après ${r.windowS} s")
                publish(now)
                return
            }
            if (now - lastReconnectAlert >= LINK_ALERT_REPEAT_MS) {
                lastReconnectAlert = now
                link.alert(LinkAlert.LOST)                       // rappel : la liaison n'est toujours pas revenue
            }
            if (r.due(now, online)) {
                r.attemptStarted()
                attemptActive = true
                link.startAttempt()
            }
        }
        val deadline = helloDeadline
        if (attemptActive && deadline != null && now > deadline) {
            attemptFailed(now, "no_hello")
            return
        }
        if (connected) {
            val mine = mineActive()
            when (watch.check(now, mine)) {
                LinkVerdict.STALE -> { onLinkClosed(now, "silence"); return }
                LinkVerdict.TX_SILENCE -> {
                    silenceAlerted = true
                    log("Plus de nouvelles de la station depuis 1,5 s pendant ton émission : arrête de parler.", LogLevel.BAD)
                    link.alert(LinkAlert.LOST)
                }
                LinkVerdict.OK -> Unit
            }
            if (!listener && heartbeat.shouldBeat(now, mine)) link.send(Command.Heartbeat.encode())
            if (netOffered) {                                     // sonde réseau : mesure seulement, jamais l'émission
                net.ping(now, wall())?.let { (seq, t, w) -> link.send(Command.NetPing(seq, t, w).encode()) }
                net.report(now, wall(), netType(), null, true)?.let { link.send(Command.NetReport(it).encode()) }
            }
            if (now - lastPing >= PING_EVERY_MS) {
                lastPing = now
                send(now, Command.GetState)
            }
            val expired = pending.filterValues { now - it.sentAt > COMMAND_TIMEOUT_MS }
            for ((id, entry) in expired) {
                pending.remove(id)
                if (entry.cmd != "get_state") log("Pas de réponse de la station à « ${entry.cmd} ».", LogLevel.WARN)
            }
        }
        publish(now)
    }

    // ------------------------------------------------------------------ actions de l'utilisateur

    fun setArmed(now: Long, on: Boolean) {
        if (on && connected && !listener) arming.arm() else arming.disarm()
        publish(now)
    }

    /** Appui sur PTT (toggle) : prise d'émission si armé et libre, fin de SON émission sinon. */
    fun pressPtt(now: Long) {
        if (!connected) return
        if (listener) {                                          // visiteur : réception seule, aucune émission
            send(now, Command.Toggle)                            // refusé (et dit) avant de partir
            publish(now)
            return
        }
        val mine = mineActive()
        val ptt = state?.ptt
        when {
            !protocolOk -> log("Version de protocole inconnue : émission impossible (STOP reste permis).", LogLevel.WARN)
            !mine && !arming.armed -> log("Active d'abord « Émission autorisée ».", LogLevel.WARN)
            !mine && ptt != null && ptt.state != "RX" -> log("Une émission est en cours (${ptt.owner ?: "?"}) : utilise STOP pour couper.", LogLevel.WARN)
            else -> {
                heartbeat.onToggleSent(now)                      // battements dès la demande, avant la confirmation
                send(now, Command.Toggle)
            }
        }
        publish(now)
    }

    /** STOP : toujours envoyé, armé ou non, quelle que soit la version du protocole. */
    fun stop(now: Long, why: String? = null) {
        if (!connected) return
        why?.let { log(it, LogLevel.WARN) }
        send(now, Command.Stop)
        heartbeat.cancelGrace()
        publish(now)
    }

    /** « Reprendre la main » après une action sur le poste ; la station refuse pendant une émission locale. */
    /** Ligne du journal venue de la couche Android (bouton du casque, routage audio) : utile aux essais. */
    fun note(now: Long, text: String, warn: Boolean = false) {
        log(text, if (warn) LogLevel.WARN else LogLevel.INFO)
        publish(now)
    }

    fun releaseLocal(now: Long) {
        if (!connected) return
        send(now, Command.LocalRelease)
        publish(now)
    }

    // ------------------------------------------------------------------ réglages du poste (la station valide tout)

    fun setFrequency(now: Long, hz: Long) = control(now, Command.SetFrequency(hz.coerceIn(Radio.MIN_HZ, Radio.MAX_HZ)))

    fun setMode(now: Long, mode: String) = control(now, Command.SetMode(mode))

    fun recallMemory(now: Long, id: String) = control(now, Command.MemoryRecall(id))

    /** Bande : dernière fréquence et dernier mode utilisés, sinon le point de départ ; mode données si l'émission l'exige. */
    fun selectBand(now: Long, key: String) {
        val h = hello ?: return
        val (hz, mode) = Radio.bandTarget(bands.spots, key, h.txModes, h.capabilities?.modes.orEmpty()) ?: return
        val commands = buildList {                                  // comme la page : le mode d'abord, puis la fréquence
            if (mode != null && mode != state?.rig?.mode) add(Command.SetMode(mode))
            add(Command.SetFrequency(hz))
        }
        control(now, *commands.toTypedArray())
    }

    /** Vue du spectre HF ouverte (`on`) ou fermée : abonnement aux balayages, gardé pour les reconnexions. */
    fun watchSpectrum(now: Long, on: Boolean) {
        spectrumWanted = on
        spotBook.clear()                                             // la station rejoue les spots à l'ouverture (page : idem)
        if (connected && protocolOk && hello?.spectrum != null) send(now, Command.SpectrumWatch(on))
        publish(now)
    }

    /** Réglage du spectre du poste : `mode`, `span`, `ref`, `speed`, `filter` (refusé hors réception, comme la page). */
    fun spectrumSet(now: Long, name: String, value: JsonPrimitive) = control(now, Command.SpectrumSet(name, value))

    /** QSY sur un spot : son mode (adapté à ce poste, mode données si l'émission l'exige) puis sa fréquence. */
    fun qsySpot(now: Long, id: Long) {
        val spot = spotBook.get(id) ?: return
        val h = hello ?: return
        val (hz, mode) = Spots.qsyTarget(spot) { Radio.adaptMode(it, h.txModes, h.capabilities?.modes.orEmpty()) }
        val commands = buildList {
            if (mode != null && mode != state?.rig?.mode) add(Command.SetMode(mode))
            add(Command.SetFrequency(hz))
        }
        control(now, *commands.toTypedArray())
    }

    /** Décalage du clarifieur (RIT ou XIT = ΔTX), arrondi à 10 Hz ; refusé pendant l'émission. */
    /**
     * Bips de fin (réglage commun de la station) : `roger_enabled`, `link_lost_enabled`, `roger_tone`, `roger_pattern`.
     * La station répond par le message `beeps` diffusé à tous.
     */
    fun setBeeps(now: Long, changes: Map<String, JsonPrimitive>) {
        if (!connected || !protocolOk || hello?.beeps == null || changes.isEmpty()) return
        send(now, Command.BeepsSet(changes))
        publish(now)
    }

    /** Appel reçu (veille -> ouvert) : noté au journal et bip discret (le son de la station revient). */
    private fun onSelcall(status: SelcallStatus?) {
        val before = selcall
        selcall = status ?: return
        if (before?.state == SelcallStatus.STANDBY && status.open) {
            val c = status.lastCall
            log("SELCALL : appel ${c?.code ?: status.code} reçu" +
                (c?.let { " (décalage ${if (it.deltaHz > 0) "+" else ""}${it.deltaHz} Hz, SNR ${it.snrDb} dB)" } ?: "") + " : son ouvert.", LogLevel.INFO)
            link.alert(LinkAlert.SELCALL_CALL)
        }
    }

    /** SELCALL de la station : n'agit que sur le son reçu (jamais sur l'émission) ; permis même pendant une émission. */
    private fun selcallCommand(now: Long, command: Command) {
        if (!connected || !protocolOk || hello?.offers("selcall") != true) return
        send(now, command)
        publish(now)
    }

    fun selcallActivate(now: Long, code: String) {
        if (!SelcallTones.validCode(code)) {
            log("Code SELCALL : 3 à 8 chiffres.", LogLevel.WARN)
            publish(now)
            return
        }
        selcallCommand(now, Command.SelcallActivate(code))
    }

    fun selcallRearm(now: Long) = selcallCommand(now, Command.SelcallRearm)

    fun selcallDeactivate(now: Long) = selcallCommand(now, Command.SelcallDeactivate)

    fun selcallOptions(now: Long, filterMode: String? = null, attenuationDb: Int? = null, sendOnTxEnd: Boolean? = null,
                       txLevelDbfs: Double? = null) =
        selcallCommand(now, Command.SelcallOptions(filterMode, attenuationDb, sendOnTxEnd, txLevelDbfs))

    /** Réglage automatique du niveau de la trame d'après l'ALC : une ÉMISSION (mêmes conditions que l'appel manuel). */
    fun selcallCalibrate(now: Long) = selcallTransmit(now, "selcall_calibrate", Command.SelcallCalibrate)

    /**
     * Appel SELCALL manuel : c'est une ÉMISSION de ce téléphone, mêmes conditions que le PTT (« Émission autorisée »,
     * personne d'autre en émission) ; battements dès la demande. Annuler = `stop`.
     */
    fun selcallSend(now: Long) = selcallTransmit(now, "selcall_send", Command.SelcallSend)

    private fun selcallTransmit(now: Long, feature: String, command: Command) {
        if (!connected || hello?.offers("selcall") != true) return
        if (hello?.offers(feature) != true) {
            log("Appel SELCALL : station à mettre à jour (0.63.0 ou plus).", LogLevel.WARN)
            publish(now)
            return
        }
        val ptt = state?.ptt
        when {
            !protocolOk -> log("Version de protocole inconnue : émission impossible (STOP reste permis).", LogLevel.WARN)
            !arming.armed -> log("Active d'abord « Émission autorisée » : l'appel SELCALL est une émission.", LogLevel.WARN)
            ptt != null && ptt.state != "RX" -> log("Une émission est en cours (${ptt.owner ?: "?"}) : appel SELCALL impossible.", LogLevel.WARN)
            command == Command.SelcallSend && selcall?.disabled != false -> log("Arme d'abord le SELCALL sur un code.", LogLevel.WARN)
            else -> {
                heartbeat.onToggleSent(now)
                send(now, command)
            }
        }
        publish(now)
    }

    fun setOffset(now: Long, name: String, hz: Int) = control(now, Command.SetOffset(name, Math.round(hz / 10.0).toInt() * 10))

    /** Squelch du poste, 0 (ouvert) à 1. */
    fun setSquelch(now: Long, value: Double) = control(now, Command.SetSquelch(value.coerceIn(0.0, 1.0)))

    /** Niveau d'une fonction (NR, NB) : la station vérifie la plage déclarée par le poste. */
    fun setLevel(now: Long, name: String, value: Double) = control(now, Command.SetLevel(name, value))

    /**
     * Mémoire partagée de la station : création (`id` null) ou modification. Ne touche pas au poste : permis aussi
     * pendant une émission (comme la page). La station renvoie la liste à jour (message `memories`).
     */
    fun saveMemory(now: Long, name: String, hz: Long, mode: String, favorite: Boolean, id: String? = null) =
        memoryCommand(now, Command.MemorySave(name.trim().take(MEMORY_NAME_MAX), hz, mode, favorite, id))

    fun deleteMemory(now: Long, id: String) = memoryCommand(now, Command.MemoryDelete(id))

    private fun memoryCommand(now: Long, command: Command) {
        if (!connected) return
        if (!protocolOk) log("Version de protocole inconnue : mémoires en lecture seule.", LogLevel.WARN) else send(now, command)
        publish(now)
    }

    /** Bouton d'une fonction du poste (Controls.chips) : NR, NB, P.AMP, ATT, NOTCH, IP+, AGC, COMP, FIL, TUNER, PWR. */
    fun pressControl(now: Long, key: String) {
        val commands = Controls.press(key, hello, state)
        if (commands.isNotEmpty()) control(now, *commands.toTypedArray())
    }

    /**
     * Réglage du poste : jamais pendant une émission (page : « tx_active » ; la station refuse aussi), ni avec un
     * protocole inconnu. Plusieurs commandes partent dans l'ordre (canal ordonné).
     */
    private fun control(now: Long, vararg commands: Command) {
        if (!connected) return
        when {
            !protocolOk -> log("Version de protocole inconnue : réglages impossibles (STOP reste permis).", LogLevel.WARN)
            (state?.ptt?.state ?: "RX") != "RX" -> log(Texts.refusal("tx_active"), LogLevel.WARN)
            else -> for (command in commands) send(now, command)
        }
        publish(now)
    }

    // ------------------------------------------------------------------ interne

    // ------------------------------------------------------------------ visiteurs (opérateur seulement)

    /** Déconnecter un visiteur (il peut revenir ; pour l'en empêcher : désactiver son compte sur la station). */
    fun kickListener(now: Long, account: String) {
        if (!connected) return
        send(now, Command.ListenerKick(account))
        publish(now)
    }

    /** Rouvrir l'écoute suspendue par une surcharge (la station refuse tant qu'elle n'est pas revenue à la normale). */
    fun reopenListeners(now: Long) {
        if (!connected) return
        send(now, Command.ListenersReopen)
        publish(now)
    }

    // ---- mesure de TOS (opérateur) : chaque point est une prise d'émission NORMALE de ce téléphone (battements envoyés
    // comme pour le PTT tant que l'émission est la sienne) ; la station décide de tout et coupe à la moindre anomalie
    fun swrPlan(now: Long, lowHz: Long, highHz: Long, points: Int, powerPct: Double) {
        if (!connected || listener || hello?.offers("swr") != true) return
        send(now, Command.SwrPlan(lowHz, highHz, points, powerPct))
    }

    fun swrStart(now: Long, lowHz: Long, highHz: Long, points: Int, powerPct: Double) {
        if (!connected || listener || hello?.offers("swr") != true) return
        if (!arming.armed) { log("Mesure de TOS : « Émission autorisée » d'abord.", LogLevel.WARN); publish(now); return }
        swr = SwrProgress("preparing", 0, emptyList(), null)
        send(now, Command.SwrStart(lowHz, highHz, points, powerPct))
        publish(now)
    }

    fun swrCancel(now: Long) {
        if (!connected || listener) return
        send(now, Command.SwrCancel)
    }

    fun swrLast(now: Long) {
        if (!connected || listener || hello?.offers("swr") != true) return
        send(now, Command.SwrLast)
    }

    /** Profils d'égaliseur (opérateur) : enregistrer (remplace le même nom) ou supprimer ; la liste revient dans `voiceProfiles`. */
    fun saveVoiceProfile(now: Long, name: String, settings: JsonObject) {
        if (!connected || listener || voiceProfiles == null) return
        send(now, Command.VoiceProfileSave(name.trim(), settings))
        publish(now)
    }

    fun deleteVoiceProfile(now: Long, name: String) {
        if (!connected || listener || voiceProfiles == null) return
        send(now, Command.VoiceProfileDelete(name))
        publish(now)
    }

    private fun parseVoiceProfiles(raw: kotlinx.serialization.json.JsonElement?): List<VoiceProfile>? =
        (raw as? kotlinx.serialization.json.JsonArray)?.mapNotNull { item ->
            val obj = item as? JsonObject ?: return@mapNotNull null
            val name = (obj["name"] as? JsonPrimitive)?.contentOrNull ?: return@mapNotNull null
            VoiceProfile(name, obj["settings"] as? JsonObject ?: JsonObject(emptyMap()))
        }

    /** Synthèse du matériel de la station (opérateurs) ; la réponse arrive dans `hostSections`. N'agit sur rien. */
    fun hostInfo(now: Long) {
        if (!connected || listener) return
        hostSections = null
        send(now, Command.HostInfo)
        publish(now)
    }

    /** Commutateur « Écoute des visiteurs » ; fermer déconnecte les visiteurs présents. */
    fun setListenersOpen(now: Long, on: Boolean) {
        if (!connected) return
        send(now, Command.ListenersOpen(on))
        publish(now)
    }

    // ---- Breizh Audio Box (opérateur, fonction « breizh ») : réglages pris à la PROCHAINE émission, jamais pendant
    private fun breizhOffered() = connected && protocolOk && !listener && hello?.offers("breizh") == true

    /** Volume retour (−20 à +6 dB, pas de 0,5) et/ou « Direct ». */
    fun breizhSet(now: Long, returnGainDb: Double? = null, bypass: Boolean? = null) {
        if (!breizhOffered() || (returnGainDb == null && bypass == null)) return
        send(now, Command.BreizhSet(returnGainDb?.let { Breizhs.snapGain(it) }, bypass))
        publish(now)
    }

    fun breizhReactivate(now: Long) {
        if (!breizhOffered()) return
        send(now, Command.BreizhReactivate)
    }

    // ---- sonde de qualité réseau (fonction « netprobe ») : mesure et affiche, n'agit jamais sur l'émission
    private fun netOperator() = connected && protocolOk && !listener && netOffered

    /** La couche Android sonde /health toutes les 5 s tant que c'est vrai (connecté ou en reconnexion). */
    val netProbing: Boolean get() = netOffered && (connected || reconnect != null)

    /** Réponse (ou échec) de GET /health. */
    fun netHealth(ok: Boolean) { if (netOffered) net.health(ok) }

    fun netStats(now: Long, days: Int = 30) {
        if (!netOperator()) return
        netStatus = "Lecture…"
        send(now, Command.NetStats(days))
        publish(now)
    }

    fun netClear(now: Long) { if (netOperator()) { send(now, Command.NetClear); publish(now) } }

    fun netThresholds(now: Long, netType: String, rttWarn: Double, rttAlert: Double, lossWarn: Double, lossAlert: Double) {
        if (!netOperator() || rttWarn >= rttAlert || lossWarn >= lossAlert) return
        send(now, Command.NetThresholds(netType, rttWarn, rttAlert, lossWarn, lossAlert))
    }

    fun netThresholdsReset(now: Long, netType: String) { if (netOperator()) send(now, Command.NetThresholds(netType, reset = true)) }

    fun netVpnIgnore(now: Long, address: String) { if (netOperator()) send(now, Command.NetVpnIgnore(address)) }

    /** Export anonyme : morceaux demandés l'un après l'autre, puis `onNetExport`. */
    fun netExport(now: Long) {
        if (!netOperator() || netExport != null) return
        netExport = "" to java.io.ByteArrayOutputStream()
        netStatus = "Export en cours…"
        send(now, Command.NetExport(0))
        publish(now)
    }

    fun breizhLog(now: Long) {
        if (!breizhOffered()) return
        send(now, Command.BreizhLog)
    }

    private val listener: Boolean get() = hello?.listener == true

    private fun send(now: Long, command: Command) {
        if (listener && command.name !in Command.LISTENER) {      // visiteur : rien d'autre ne part vers la station
            if (now - lastForbiddenLog > 2000) {
                lastForbiddenLog = now
                log(Texts.refusal("forbidden", ""), LogLevel.WARN)
            }
            return
        }
        val id = nextId++
        if (link.send(command.encode(id))) pending[id] = Pending(command.name, now)
    }

    private fun mineActive(): Boolean {
        val p = state?.ptt ?: return false
        val me = hello?.clientId ?: return false
        return p.state in Protocol.ACTIVE_STATES && p.owner == me
    }

    private fun mineTx(): Boolean {
        val p = state?.ptt ?: return false
        return p.state == "TX" && p.owner != null && p.owner == hello?.clientId
    }

    private fun giveUp(now: Long, why: String) {
        teardown()
        reconnect = null
        status = LinkStatus.DISCONNECTED
        log("Reconnexion abandonnée : $why.", LogLevel.BAD)
        link.alert(LinkAlert.FAILED)
    }

    /** Ferme tout : micro d'abord, puis la liaison ; oublie l'état de la station (rien n'est supposé ensuite). */
    private fun teardown() {
        link.setMicOpen(false)
        if (status != LinkStatus.DISCONNECTED || attemptActive) link.close()
        attemptActive = false
        helloDeadline = null
        heartbeat.onDisconnected()
        watch.reset()
        arming.onConnected()
        silenceAlerted = false
        bye = null
        hello = null
        state = null
        memories = emptyList()
        spotBook.clear()
        clusterHealth = null
        clusterStatus = null
        beeps = null
        recentSpots = emptyList()
        selcall = null
        hostSections = null
        voiceProfiles = null
        swr = null; swrPlan = null; swrChoices = null; swrLast = null
        breizhEvents = emptyList()
        protocolOk = true
        net.stop(wall())                                         // les résumés restent : remis à la reconnexion
        netStats = null; netExport = null; netStatus = ""
        pending.clear()
        rttMs = null
        status = LinkStatus.DISCONNECTED
    }

    private fun log(text: String, level: LogLevel) {
        log.addLast(LogLine(wall(), text, level))
        while (log.size > MAX_LOG) log.removeFirst()
    }

    private fun publish(now: Long = -1) {
        val r = reconnect
        val next = RigState(
            status = status,
            hello = hello,
            state = state,
            ptt = state?.let { s -> hello?.let { PttView.of(s.ptt, it.clientId) } },
            armed = arming.armed,
            protocolOk = protocolOk,
            reconnect = r?.let {
                ReconnectInfo(
                    remainingS = if (now >= 0) maxOf(0, ((it.deadline - now + 999) / 1000).toInt()) else it.windowS,
                    attempts = it.attempts, windowS = it.windowS, lastError = lastAttemptError,
                )
            },
            rttMs = rttMs,
            log = log.toList(),
            memories = memories,
            bandSpots = bands.spots,
            spots = spotBook.all().sortedBy { it.hz },
            clusterHealth = clusterHealth,
            clusterStatus = clusterStatus,
            clusterStatusAtMs = clusterStatusAt,
            beeps = beeps,
            recentSpots = recentSpots,
            selcall = selcall,
            listener = listener,
            presence = PresenceUi.of(state?.presence, listener),
            host = HostHealth.of(state?.host, listener),
            hostSections = hostSections,
            voiceProfiles = voiceProfiles,
            swr = swr, swrPlan = swrPlan, swrChoices = swrChoices, swrLast = swrLast,
            breizh = if (listener) null else Breizhs.view(state?.breizh),
            breizhEvents = if (listener) emptyList() else breizhEvents,
            net = NetUi.view(state?.net),
            netStats = netStats, netStatus = netStatus,
        )
        if (next != snapshot) {
            snapshot = next
            onChange?.invoke(next)
        }
    }

    companion object {
        const val PING_EVERY_MS = 2000L
        const val COMMAND_TIMEOUT_MS = 5000L
        /** Connexion manuelle : le canal doit s'ouvrir dans ce délai après la réponse de la station. */
        const val HELLO_TIMEOUT_MS = 15_000L
        const val LINK_ALERT_REPEAT_MS = 3000L
        const val MAX_LOG = 60
        /** Nom d'une mémoire : 40 caractères au plus (station : memories.MAX_NAME). */
        const val MEMORY_NAME_MAX = 40
    }
}
