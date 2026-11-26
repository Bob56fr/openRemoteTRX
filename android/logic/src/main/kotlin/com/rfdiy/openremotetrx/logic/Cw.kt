// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/*
 * Manipulation CW depuis l'écran tactile (branche d'essai exp/cw, docs/exp-cw/cahier-des-charges.md).
 * Kotlin pur (compilé aussi par openRemoteTRX Lite) : le manipulateur, les paquets du canal « cw », le décodage de
 * SA propre manipulation et l'état montré. La station rejoue les fronts et ne garde la tonalité que tant que le bail
 * du client la couvre : l'application ne fait qu'aider, elle ne remplace jamais les coupures de la station.
 * Temps en millisecondes (Double) sur l'horloge monotone du téléphone.
 */

/** Manipulateur choisi : pioche (1 palette) ou iambique A / B, simple levier (2 palettes). `wire` = valeur du protocole. */
enum class CwInterface(val wire: String, val pads: Int) {
    STRAIGHT("straight", 1), IAMBIC_A("iambic_a", 2), IAMBIC_B("iambic_b", 2), SINGLE_LEVER("single_lever", 2);   // i18n-ok

    companion object {
        fun of(wire: String?): CwInterface = entries.firstOrNull { it.wire == wire } ?: IAMBIC_B
    }
}

enum class Paddle { DOT, DASH }

/** Front de la clé : `at` en ms (horloge du téléphone), `down` = clé fermée (tonalité). */
data class KeyEdge(val at: Double, val down: Boolean)

/**
 * Manipulateur : appuis sur les palettes (ou la clé) -> fronts de la clé, à la milliseconde près, calculés et non
 * mesurés à l'appel : un élément iambique dure exactement un point (ou `weight` points pour un trait), quel que soit
 * le moment où l'application rappelle [advance]. Pioche : la palette DOT est la clé, le front suit le doigt.
 *
 * Iambique A : à la fin d'un élément, l'élément suivant dépend des palettes ENCORE appuyées (alterné si les deux).
 * Iambique B : en plus, une palette opposée appuyée pendant l'élément (même relâchée depuis) donne un élément de plus.
 * Simple levier : la dernière palette appuyée l'emporte, jamais d'alternance.
 */
class CwKeyer(var keyInterface: CwInterface = CwInterface.IAMBIC_B, wpm: Int = 20, var weight: Double = 3.0,
              var reversed: Boolean = false) {
    var wpm: Int = wpm.coerceIn(MIN_WPM, MAX_WPM)
        set(value) { field = value.coerceIn(MIN_WPM, MAX_WPM) }
    val dotMs: Double get() = 1200.0 / wpm

    var down = false
        private set
    private var dotHeld = false
    private var dashHeld = false
    private var lastPressed: Paddle? = null
    private var element: Paddle? = null
    private var lastElement: Paddle? = null
    private var markEnd = 0.0
    private var spaceEnd = 0.0
    private val memory = mutableSetOf<Paddle>()

    /** Prochain instant où le manipulateur changera de lui-même (null : il attend un appui). */
    val nextEventAt: Double? get() = if (element == null) null else if (down) markEnd else spaceEnd

    fun reset() {
        down = false; dotHeld = false; dashHeld = false; lastPressed = null
        element = null; lastElement = null; memory.clear()
    }

    /** Appui ou relâchement à l'instant `at` ; renvoie les fronts produits jusqu'à `at` inclus. */
    fun press(at: Double, paddle: Paddle, pressed: Boolean): List<KeyEdge> {
        val p = if (reversed && keyInterface != CwInterface.STRAIGHT) other(paddle) else paddle
        val out = advance(at).toMutableList()
        if (keyInterface == CwInterface.STRAIGHT) {
            if (p != Paddle.DOT) return out
            dotHeld = pressed
            if (pressed != down) {
                down = pressed
                out += KeyEdge(at, pressed)
            }
            return out
        }
        if (p == Paddle.DOT) dotHeld = pressed else dashHeld = pressed
        if (pressed) {
            lastPressed = p
            val current = element
            if (current != null && p != current && keyInterface == CwInterface.IAMBIC_B) memory += p
            if (current == null) out += start(p, at)
        }
        return out
    }

    /** Fronts dus jusqu'à `now` inclus (éléments iambiques qui finissent ou s'enchaînent). */
    fun advance(now: Double): List<KeyEdge> {
        if (keyInterface == CwInterface.STRAIGHT) return emptyList()
        val out = mutableListOf<KeyEdge>()
        while (element != null) {
            if (down && markEnd <= now) {
                down = false
                out += KeyEdge(markEnd, false)
            } else if (!down && spaceEnd <= now) {
                val t = spaceEnd
                val next = choose()
                element = null
                if (next != null) out += start(next, t) else break
            } else {
                break
            }
        }
        return out
    }

    private fun choose(): Paddle? {
        if (keyInterface == CwInterface.SINGLE_LEVER) {
            return when {
                dotHeld && dashHeld -> lastPressed
                dotHeld -> Paddle.DOT
                dashHeld -> Paddle.DASH
                else -> null
            }
        }
        val last = lastElement ?: return null
        val opposite = other(last)
        val oppositeWanted = opposite in memory || held(opposite)
        memory.remove(opposite)
        return when {
            oppositeWanted -> opposite
            held(last) -> last
            else -> null
        }
    }

    private fun start(p: Paddle, at: Double): List<KeyEdge> {
        element = p
        lastElement = p
        memory.remove(p)
        if (keyInterface == CwInterface.IAMBIC_B && held(other(p))) memory += other(p)
        down = true
        markEnd = at + if (p == Paddle.DOT) dotMs else dotMs * weight
        spaceEnd = markEnd + dotMs
        return listOf(KeyEdge(at, true))
    }

    private fun held(p: Paddle) = if (p == Paddle.DOT) dotHeld else dashHeld
    private fun other(p: Paddle) = if (p == Paddle.DOT) Paddle.DASH else Paddle.DOT

    companion object {
        const val MIN_WPM = 5
        const val MAX_WPM = 40
    }
}

/**
 * Paquets du canal « cw » (cahier § 5.1) : un paquet à chaque front et toutes les 20 ms pendant la séquence, puis
 * toutes les 200 ms en silence armé ; chaque paquet porte les fronts des 500 dernières ms (32 au plus) et le bail
 * (= instant de l'envoi, ts de la séquence). Nouvelle séquence (`seq` + 1, ts remis à 0) sur une fermeture de la clé
 * après plus de `seqGapMs` de silence. Mêmes paquets que le banc Python : vecteurs tests/protocol/cw_vectors.json.
 */
class CwPacketizer(private val seqGapMs: Double = SEQ_GAP_MS) {
    data class Packet(val at: Double, val json: JsonObject) {
        val text: String get() = json.toString()
    }

    private data class Sent(val id: Int, val down: Boolean, val ts: Double)

    var seq = -1
        private set
    private var nextId = 1
    private var seqStart = 0.0
    private var lastEdgeAt = Double.NEGATIVE_INFINITY
    private var nextTick = Double.POSITIVE_INFINITY
    private val edges = ArrayDeque<Sent>()

    /** À chaque armement : séquences et identifiants repartent de zéro (la station crée un nouveau rejeu). */
    fun reset() {
        seq = -1; nextId = 1; seqStart = 0.0; lastEdgeAt = Double.NEGATIVE_INFINITY
        nextTick = Double.POSITIVE_INFINITY; edges.clear()
    }

    /** Paquets dus jusqu'à `now` inclus, les fronts `newEdges` (dans l'ordre, tous <= now) compris. */
    fun advance(now: Double, newEdges: List<KeyEdge> = emptyList()): List<Packet> {
        val out = mutableListOf<Packet>()
        for (e in newEdges) {
            ticksBefore(e.at, out, inclusive = false)
            if (e.down && (seq < 0 || e.at - lastEdgeAt > seqGapMs)) {
                seq += 1
                seqStart = e.at
                edges.clear()
                nextTick = e.at + EVERY_MS
            } else if (seq < 0) {
                continue                                         // une ouverture ne commence jamais une séquence
            }
            edges.addLast(Sent(nextId++, e.down, e.at - seqStart))
            lastEdgeAt = e.at
            // un seul paquet à cet instant ; après un silence déjà passé au rythme lent, retour aux 20 ms ALIGNÉS sur le
            // début de la séquence (comme le banc : seqStart + 20 k)
            val aligned = seqStart + EVERY_MS * (kotlin.math.floor((e.at - seqStart) / EVERY_MS) + 1)
            if (nextTick > aligned || nextTick == e.at) nextTick = aligned
            out += packet(e.at)
        }
        ticksBefore(now, out, inclusive = true)
        return out
    }

    private fun ticksBefore(limit: Double, out: MutableList<Packet>, inclusive: Boolean) {
        while (seq >= 0 && (nextTick < limit || (inclusive && nextTick == limit))) {
            val t = nextTick
            out += packet(t)
            val busyEnd = lastEdgeAt + seqGapMs
            nextTick = when {
                t + EVERY_MS < busyEnd -> t + EVERY_MS
                t < busyEnd -> busyEnd + SILENCE_EVERY_MS
                else -> t + SILENCE_EVERY_MS
            }
        }
    }

    private fun packet(at: Double): Packet {
        val ts = at - seqStart
        while (edges.size > MAX_WINDOW || (edges.isNotEmpty() && edges.first().ts < ts - WINDOW_MS)) edges.removeFirst()
        val window = edges.filter { it.ts >= ts - WINDOW_MS && it.ts <= ts }.takeLast(MAX_WINDOW)
        return Packet(at, buildJsonObject {
            put("type", "cw")                                    // i18n-ok
            put("seq", seq)
            put("edges", buildJsonArray { for (w in window) add(buildJsonArray { add(JsonPrimitive(w.id)); add(JsonPrimitive(if (w.down) 1 else 0)); add(JsonPrimitive(w.ts)) }) })
            put("lease", ts)
        })
    }

    companion object {
        const val SEQ_GAP_MS = 1500.0
        const val WINDOW_MS = 500.0
        const val MAX_WINDOW = 32
        const val EVERY_MS = 20.0
        const val SILENCE_EVERY_MS = 200.0
    }
}

/** Décodage de SA propre manipulation (aide et diagnostic, cahier § 7) : marques classées point / trait d'après la
 *  vitesse réglée, lettre close après 2 points de silence, espace entre mots après 5. 64 caractères gardés. */
class CwDecoder(var wpm: Int = 20) {
    private val dot get() = 1200.0 / wpm
    private var downAt: Double? = null
    private var lastUp: Double? = null
    private val symbol = StringBuilder()
    private var text = StringBuilder()
    private var spaced = true

    val shown: String get() = text.toString()

    fun clear() { downAt = null; lastUp = null; symbol.clear(); text = StringBuilder(); spaced = true }

    fun edge(e: KeyEdge) {
        if (e.down) {
            poll(e.at)
            downAt = e.at
        } else {
            val start = downAt ?: return
            symbol.append(if (e.at - start < 2 * dot) '.' else '-')
            downAt = null
            lastUp = e.at
        }
    }

    /** Silence en cours : ferme la lettre, puis le mot. */
    fun poll(now: Double) {
        val up = lastUp ?: return
        if (downAt != null) return
        val quiet = now - up
        if (symbol.isNotEmpty() && quiet >= 2 * dot) {
            append(MORSE[symbol.toString()] ?: '?')
            symbol.clear()
        }
        if (symbol.isEmpty() && !spaced && quiet >= 5 * dot) {
            append(' ')
            spaced = true
        }
    }

    private fun append(c: Char) {
        if (c != ' ') spaced = false
        text.append(c)
        if (text.length > 64) text = StringBuilder(text.takeLast(64))
    }

    companion object {
        val MORSE: Map<String, Char> = mapOf(                    // i18n-ok
            ".-" to 'A', "-..." to 'B', "-.-." to 'C', "-.." to 'D', "." to 'E', "..-." to 'F', "--." to 'G',
            "...." to 'H', ".." to 'I', ".---" to 'J', "-.-" to 'K', ".-.." to 'L', "--" to 'M', "-." to 'N',
            "---" to 'O', ".--." to 'P', "--.-" to 'Q', ".-." to 'R', "..." to 'S', "-" to 'T', "..-" to 'U',
            "...-" to 'V', ".--" to 'W', "-..-" to 'X', "-.--" to 'Y', "--.." to 'Z', "-----" to '0', ".----" to '1',
            "..---" to '2', "...--" to '3', "....-" to '4', "....." to '5', "-...." to '6', "--..." to '7',
            "---.." to '8', "----." to '9', "-..-." to '/', "..--.." to '?', "-...-" to '=', ".-.-.-" to '.',
        )
    }
}

/** Réglages de l'opérateur (gardés par l'application) ; `toneHz` = tonalité recréée par la station ET retour local. */
data class CwSettings(
    val keyInterface: CwInterface = CwInterface.IAMBIC_B,
    val wpm: Int = 20,
    val weight: Double = 3.0,
    val toneHz: Int = 700,
    val reversed: Boolean = false,
    val align: Boolean = false,
    val sidetone: Double = 0.6,
) {
    val pads: Int get() = keyInterface.pads
}

/** Ce que l'onglet CW affiche (état renvoyé par la station : jamais supposé). */
data class CwUi(
    val offered: Boolean = false,
    val requested: Boolean = false,        // armement demandé, réponse pas encore reçue
    val armed: Boolean = false,            // la station dit « armed » ou « playing »
    val playing: Boolean = false,
    val keyDown: Boolean = false,          // clé fermée sur le téléphone (retour local)
    val carrierHz: Long? = null,
    val delayMs: Int? = null,
    val bufferMs: Int? = null,
    val late: Int = 0,
    val leaseCuts: Int = 0,
    val jitterP95Ms: Double? = null,
    val decoded: String = "",
    val notice: String = "",               // dernier refus, défaut ou fin d'armement, dans la langue de l'application
    val settings: CwSettings = CwSettings(),
)

/**
 * Manipulation CW d'UNE connexion : appuis -> fronts -> paquets, et lecture des messages de la station. Ne parle pas
 * au réseau : `RigSession` envoie les commandes et les paquets. Désarmée à chaque connexion ; un refus, une coupure ou
 * `cw_state idle` la désarment. Les paquets ne partent QUE tant que la station a dit « armée ».
 */
class CwClient {
    private val keyer = CwKeyer()
    private val packetizer = CwPacketizer()
    private val decoder = CwDecoder()
    var ui = CwUi()
        private set

    var settings: CwSettings
        get() = ui.settings
        set(value) {
            keyer.keyInterface = value.keyInterface
            keyer.wpm = value.wpm
            keyer.weight = value.weight.coerceIn(2.5, 4.5)
            keyer.reversed = value.reversed
            decoder.wpm = keyer.wpm
            if (value.keyInterface != ui.settings.keyInterface) keyer.reset()
            ui = ui.copy(settings = value)
        }

    /** Ce que la station a dit armé (les appuis ne comptent que là). */
    val armed: Boolean get() = ui.armed

    /** Rappel fin (quelques ms) nécessaire : armement en cours, tonalité, ou paquets de silence à envoyer. */
    val active: Boolean get() = ui.armed || ui.requested

    fun offered(on: Boolean) {
        ui = ui.copy(offered = on)
        if (!on) forget("")
    }

    fun requestArm() {
        ui = ui.copy(requested = true, notice = "")
    }

    /** Réponse à cw_arm : `ok` = émission prise par la station (l'état « armed » suit dans cw_state). */
    fun armResult(ok: Boolean, notice: String, carrierHz: Long?, delayMs: Int?) {
        if (!ok) {
            forget(notice)
            return
        }
        keyer.reset(); packetizer.reset(); decoder.clear()
        ui = ui.copy(requested = false, armed = true, carrierHz = carrierHz, delayMs = delayMs, late = 0, leaseCuts = 0,
                     decoded = "", notice = "")
    }

    /** Message cw_state / cw_fault / cw_stats de la station. */
    fun onMessage(type: String, raw: JsonObject) {
        fun num(k: String) = (raw[k] as? JsonPrimitive)
        when (type) {
            "cw_state" -> {                                       // i18n-ok
                val state = num("state")?.contentOrNull ?: return
                if (state == "idle") {                            // i18n-ok
                    val reason = num("reason")?.contentOrNull.orEmpty()
                    forget(if (reason.isEmpty()) "" else Tr.t("cw.ended", "reason" to Texts.cut(reason)))
                    return
                }
                ui = ui.copy(armed = true, requested = false, playing = state == "playing",      // i18n-ok
                             bufferMs = num("buffer_ms")?.intOrNull ?: ui.bufferMs, late = num("late")?.intOrNull ?: ui.late,
                             leaseCuts = num("lease_cuts")?.intOrNull ?: ui.leaseCuts,
                             carrierHz = num("carrier_hz")?.longOrNull ?: ui.carrierHz)
            }
            "cw_fault" -> ui = ui.copy(notice = Tr.t("cw.fault", "reason" to Texts.cut("cw_" + (num("reason")?.contentOrNull ?: "")))) // i18n-ok
            "cw_stats" -> ui = ui.copy(jitterP95Ms = num("jitter_p95_ms")?.doubleOrNull ?: ui.jitterP95Ms)               // i18n-ok
        }
    }

    /** Désarmée (connexion perdue, coupure, refus) : plus rien ne part ; `notice` dit pourquoi. */
    fun forget(notice: String) {
        keyer.reset(); packetizer.reset()
        ui = ui.copy(requested = false, armed = false, playing = false, keyDown = false, bufferMs = null,
                     notice = notice.ifEmpty { ui.notice })
    }

    /** Appui sur une palette (ou la clé) à l'instant `at` ; paquets à envoyer tout de suite. Ignoré hors armement. */
    fun press(at: Double, paddle: Paddle, pressed: Boolean): List<CwPacketizer.Packet> {
        if (!ui.armed) return emptyList()
        return emit(at, keyer.press(at, paddle, pressed))
    }

    /** Rappel fin : éléments iambiques qui s'enchaînent, paquets de 20 ms et de silence. */
    fun poll(now: Double): List<CwPacketizer.Packet> {
        if (!ui.armed) return emptyList()
        decoder.poll(now)
        val packets = emit(now, keyer.advance(now))
        if (ui.decoded != decoder.shown) ui = ui.copy(decoded = decoder.shown)
        return packets
    }

    /** Prochain instant utile pour le rappel fin (fin d'élément iambique), ou null. */
    val nextEventAt: Double? get() = keyer.nextEventAt

    private fun emit(now: Double, edges: List<KeyEdge>): List<CwPacketizer.Packet> {
        edges.forEach(decoder::edge)
        ui = ui.copy(keyDown = keyer.down, decoded = decoder.shown)
        return packetizer.advance(now, edges)
    }
}

/** Lecture d'un résultat de cw_arm (champ `cw`). */
internal fun cwArmInfo(raw: JsonObject?): Pair<Long?, Int?> {
    val cw = raw?.get("cw") as? JsonObject ?: return null to null
    return (cw["carrier_hz"] as? JsonPrimitive)?.longOrNull to (cw["delay_ms"] as? JsonPrimitive)?.doubleOrNull?.toInt()
}
