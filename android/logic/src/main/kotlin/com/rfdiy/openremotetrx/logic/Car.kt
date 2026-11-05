// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.Memory
import com.rfdiy.openremotetrx.protocol.State
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/** Action personnalisée de l'écran de la voiture (lot A2). Le PTT reste un toggle (E1), la station décide (E2). */
enum class CarAction(val id: String) {
    /** Prise d'émission (armé, libre) ou fin de SON émission : même chemin que le bouton PTT de l'écran. */
    PTT("ptt"),
    /** STOP : toujours permis, ne fait que couper (E7). */
    STOP("stop"),
    /** « Émission autorisée » : sans elle, aucune prise d'émission (E4 : réarmer après chaque reconnexion). */
    ARM("arm"),
    DISARM("disarm"),
    /** « Reprendre la main » après une action sur le poste (jamais pendant une émission locale : la station refuse). */
    RELEASE_LOCAL("release_local"),
    /** Cadenas sans effet (en émission, réception seule, liaison perdue) : montre l'état, ne commande rien. */
    LOCK_INFO("lock_info"),
    /** Mémoire favorite précédente / suivante (F1) : boutons à nous, À DROITE (demande de l'utilisateur). */
    MEM_PREV("mem_prev"),
    MEM_NEXT("mem_next"),
    ;

    /** Prend l'émission ou l'autorise : réservé à l'écran de la voiture et à l'application elle-même. */
    val takesTransmission: Boolean get() = this == PTT || this == ARM

    companion object {
        fun of(id: String): CarAction? = entries.firstOrNull { it.id == id }
    }
}

/** Pictogramme d'un bouton de la voiture ; le cadenas suit l'état réel de « Émission autorisée » (F6). */
enum class CarIcon { PTT, STOP, HAND, LOCK_CLOSED, LOCK_OPEN, LOCK_TX, LOCK_UNKNOWN, MEM_PREV, MEM_NEXT }

/** `label` sert aussi de texte d'accessibilité : il dit l'ÉTAT montré par le pictogramme. */
data class CarButton(val action: CarAction, val label: String, val icon: CarIcon = defaultIcon(action))

private fun defaultIcon(action: CarAction): CarIcon = when (action) {
    CarAction.PTT -> CarIcon.PTT
    CarAction.STOP -> CarIcon.STOP
    CarAction.RELEASE_LOCAL -> CarIcon.HAND
    CarAction.ARM -> CarIcon.LOCK_CLOSED
    CarAction.DISARM -> CarIcon.LOCK_OPEN
    CarAction.LOCK_INFO -> CarIcon.LOCK_UNKNOWN
    CarAction.MEM_PREV -> CarIcon.MEM_PREV
    CarAction.MEM_NEXT -> CarIcon.MEM_NEXT
}

/** Ce que montre l'écran de la voiture : texte seulement (aucun graphique, aucune saisie). */
data class CarScreen(
    val title: String,
    /** Réglages actifs du poste (F3), ou l'invitation / la station hors liaison. */
    val subtitle: String,
    /** Lecteur « en lecture » : réception audible (pause = réception muette). */
    val playing: Boolean,
    val connecting: Boolean,
    val connected: Boolean,
    val buttons: List<CarButton>,
    /** Message d'erreur à afficher (connexion impossible depuis la voiture…), vide sinon. */
    val error: String = "",
    /** Ligne secondaire (champ « album ») : fréquence si le titre est un nom, S-mètre, état de l'émission, station. */
    val secondary: String = "",
    /** Suivant / Précédent du volant permis (F1) : connecté, opérateur, au moins une mémoire favorite. */
    val canSkip: Boolean = false,
)

/**
 * Android Auto (lot A2) : titre et sous-titre du lecteur, boutons permis. Logique pure, testée (CarTest) ; le service
 * Android ne fait que l'afficher.
 */
object Car {
    /** Paquets autorisés à PRENDRE l'émission (armer, PTT) : Android Auto et l'application elle-même. */
    val TX_CALLERS = setOf("com.google.android.projection.gearhead", "com.rfdiy.openremotetrx")

    /**
     * Paquets admis à parcourir le lecteur (onGetRoot) : Android Auto, Android Automotive, l'interface système
     * (contrôles média), l'application. Les autres n'obtiennent rien.
     */
    val BROWSE_CALLERS = TX_CALLERS + setOf("com.android.systemui", "com.android.car.media", "com.google.android.carassistant")

    /** Une action vient-elle d'un appelant qui a le droit de la faire ? Couper (STOP, fin de SON émission) : tous. */
    fun allowed(action: CarAction, caller: String?, mine: Boolean): Boolean = when {
        action == CarAction.PTT && mine -> true
        !action.takesTransmission -> true
        else -> caller != null && caller in TX_CALLERS
    }

    /** Cadenas d'une liaison absente ou perdue : état d'émission inconnu. */
    val LOCK_UNKNOWN = CarButton(CarAction.LOCK_INFO, "État d'émission inconnu", CarIcon.LOCK_UNKNOWN)

    /**
     * `eq` : égaliseur de la voix émise en service (F3) ; `preview` : favori choisi au volant, pas encore envoyé (F1,
     * regroupement des appuis) ; `selcallOpen` : SELCALL de la station ouvert.
     */
    fun screen(
        rig: RigState, station: String?, muted: Boolean, micAllowed: Boolean, notice: String = "",
        eq: Boolean = false, preview: Memory? = null, selcallOpen: Boolean = false,
    ): CarScreen {
        val name = station ?: "openRemoteTRX"
        val ptt = rig.ptt
        when (rig.status) {
            LinkStatus.DISCONNECTED -> return CarScreen(
                "Déconnecté", if (notice.isNotEmpty()) notice else "Choisir une station : Parcourir > Stations",
                playing = false, connecting = false, connected = false, buttons = listOf(LOCK_UNKNOWN), error = notice,
            )
            LinkStatus.CONNECTING -> return CarScreen("Connexion…", name, false, connecting = true, connected = false, buttons = listOf(LOCK_UNKNOWN))
            LinkStatus.RECONNECTING -> return CarScreen(
                "Reconnexion…" + (rig.reconnect?.let { " ${it.remainingS} s" } ?: ""), "$name — réception seule au retour",
                playing = false, connecting = true, connected = false, buttons = listOf(LOCK_UNKNOWN),
            )
            LinkStatus.CONNECTED -> Unit
        }
        val r = rig.state?.rig
        val mine = ptt?.mine == true && ptt.transmitting
        // Seules les mémoires FAVORITES existent sur la voiture (demande de l'utilisateur).
        val favorites = Favorites.list(rig.memories)
        val memory = preview ?: memoryAt(favorites, r?.frequencyHz, r?.mode)
        // Titre : TOUJOURS la fréquence et le mode (ceux du favori choisi au volant, pas encore envoyé) ; en émission, l'état
        // en plus.
        val freq = listOfNotNull(carFrequency(preview?.hz ?: r?.frequencyHz), (preview?.mode ?: r?.mode)?.let { Radio.modeLabel(it) })
            .joinToString(" ")
        val title = when {
            mine -> "$freq ÉMISSION" + (ptt?.totSeconds?.let { " ${Format.duration(it)}" } ?: "")
            ptt?.transmitting == true -> "$freq Émission : ${ptt.label}"
            else -> freq
        }.trim()
        val parts = buildList {
            r?.mode?.let { add(Radio.modeLabel(it)) }
            ptt?.local?.let { add("poste utilisé sur place") }
            if (!micAllowed) add("réception seule")
            else if (!rig.armed && !mine) add("émission non autorisée")
            if (muted) add("muet")
            if (selcallOpen) add("SELCALL ouvert")
            add(name)
        }
        val buttons = buildList {
            val other = ptt?.transmitting == true && !mine
            if (micAllowed && rig.protocolOk) {
                when {
                    mine -> add(CarButton(CarAction.PTT, "FIN D'ÉMISSION"))
                    rig.armed && !other -> add(CarButton(CarAction.PTT, "ÉMETTRE"))
                }
            }
            add(CarButton(CarAction.STOP, "STOP"))
            // Cadenas = état actuel (pictogramme et libellé) ; un appui le bascule, l'icône suit l'état relu (jamais supposé).
            when {
                !micAllowed || !rig.protocolOk -> add(CarButton(CarAction.LOCK_INFO, "Réception seule", CarIcon.LOCK_CLOSED))
                mine -> add(CarButton(CarAction.LOCK_INFO, "En émission", CarIcon.LOCK_TX))
                rig.armed -> add(CarButton(CarAction.DISARM, "Émission autorisée", CarIcon.LOCK_OPEN))
                else -> add(CarButton(CarAction.ARM, "Émission verrouillée", CarIcon.LOCK_CLOSED))
            }
            if (ptt?.canReleaseLocal == true) add(CarButton(CarAction.RELEASE_LOCAL, "Reprendre la main"))
        }
        val canSkip = !rig.listener && favorites.isNotEmpty()
        // Sous-titre (la voiture n'affiche pas la ligne secondaire) : niveau, puis « M: <nom du favori> » ou « VFO », puis
        // les réglages (exemples de l'utilisateur : « S3  M: 430  NB NR  Preamp 100w », « S4  VFO  NB NR  100w »).
        val place = memory?.let { "M: ${it.name.take(NAME_MAX)}" } ?: "VFO"
        val signal = if (mine) null else r?.strengthDb?.let { Format.sMeter(it) }
        return CarScreen(title.ifEmpty { name }, settings(rig.hello, rig.state, eq, listOfNotNull(signal, place)), playing = !muted, connecting = false,
            connected = true, buttons = arrange(buttons, canSkip), error = notice, secondary = parts.joinToString(" · "),
            canSkip = canSkip)
    }

    /**
     * Ordre des boutons (demande de l'utilisateur) : micro et STOP À GAUCHE (côté conducteur), mémoires à droite.
     * Relevé au DHU (2026-11-05) : après Lecture, les deux premières actions à gauche, les deux suivantes à droite, le
     * reste dans le menu « ⋯ ». Sans micro (émission non autorisée), le cadenas prend SA place : on autorise là où l'on
     * émettra ensuite ; une fois l'émission autorisée, le cadenas passe après les mémoires (menu « ⋯ »).
     */
    fun arrange(buttons: List<CarButton>, canSkip: Boolean): List<CarButton> {
        val ptt = buttons.filter { it.action == CarAction.PTT }.ifEmpty { buttons.filter { it.icon.name.startsWith("LOCK") } }
        val stop = buttons.filter { it.action == CarAction.STOP }
        val rest = buttons - (ptt + stop).toSet()
        val mem = if (canSkip) listOf(CarButton(CarAction.MEM_PREV, "Mémoire précédente"), CarButton(CarAction.MEM_NEXT, "Mémoire suivante")) else emptyList()
        return order(ptt, stop, mem, rest)
    }

    /** Ordre retenu au DHU ; une seule fonction à changer si Android Auto range autrement. */
    private fun order(ptt: List<CarButton>, stop: List<CarButton>, mem: List<CarButton>, rest: List<CarButton>) =
        ptt + stop + mem + rest

    /** Longueur maximale du sous-titre (F3) et du nom de mémoire qu'il montre. */
    const val SETTINGS_MAX = 40
    const val NAME_MAX = 12

    /**
     * Sous-titre (F3, format de l'utilisateur) : groupes séparés par deux espaces, mots d'un groupe par un espace.
     * `lead` (niveau, « M: nom » ou « VFO ») d'abord ; puis NB NR RIT XIT ; puis préampli (« Preamp », « Preamp2 ») ou ATT,
     * TUNER, puissance (« 100w », « 50% » si la station ne connaît pas la puissance maximale), EQ du téléphone. Seulement ce qui
     * est ACTIF et publié par la station (un poste qui ne le gère pas ne le montre jamais). Trop long : un espace entre
     * les groupes, puis coupé.
     */
    fun settings(hello: Hello?, state: State?, eq: Boolean, lead: List<String> = emptyList()): String {
        val rig = state?.rig
        val lv = rig?.levels.orEmpty()
        val fn = rig?.functions.orEmpty()
        // RIT et XIT (ΔTX) seulement s'ils sont actifs sur le poste (demande de l'utilisateur)
        val functions = listOf("NB", "NR", "RIT", "XIT").filter { fn[it] == true }
        val levels = buildList {
            val att = lv["ATT"] ?: 0.0
            val preamp = lv["PREAMP"] ?: 0.0
            when {
                att > 0 -> add("ATT")
                preamp > 0 -> add("Preamp" + Indicators.preampNumber(preamp, hello?.capabilities?.preamps.orEmpty()).let { if (it > 1) "$it" else "" })
            }
            if (fn["TUNER"] == true) add("TUNER")                     // coupleur en service : juste avant la puissance
            lv["RFPOWER"]?.takeIf { it > 0 }?.let { f ->
                val max = hello?.maxPowerW ?: 0
                add(if (max > 0) "${(f * max).roundToInt()}w" else "${(f * 100).roundToInt()}%")
            }
            if (eq) add("EQ")
        }
        val groups = (lead + listOf(functions.joinToString(" "), levels.joinToString(" "))).filter { it.isNotEmpty() }
        val full = groups.joinToString("  ")
        if (full.length <= SETTINGS_MAX) return full
        val tight = groups.joinToString(" ")
        return if (tight.length <= SETTINGS_MAX) tight else tight.take(SETTINGS_MAX - 1) + "…"
    }

    /** Fréquence de la voiture (format de l'utilisateur) : 27430000 -> « 27.430.00 », 6660000 -> « 6.660.00 ». */
    fun carFrequency(hz: Long?): String? {
        if (hz == null || hz < 0) return null
        return String.format(Locale.ROOT, "%d.%03d.%02d", hz / 1_000_000, (hz / 1000) % 1000, (hz % 1000) / 10)
    }

    /** 14074000 -> « 14 074,00 kHz » (lisible d'un coup d'œil). */
    fun frequency(hz: Long?): String? {
        if (hz == null) return null
        val khz = hz / 1000
        val rest = (hz % 1000) / 10
        val grouped = khz.toString().reversed().chunked(3).joinToString(" ").reversed()
        return String.format(Locale.ROOT, "%s,%02d kHz", grouped, rest)
    }

    /** Mémoire qui correspond à la fréquence actuelle (à 50 Hz près, même mode si connu). */
    fun memoryAt(memories: List<Memory>, hz: Long?, mode: String?): Memory? {
        if (hz == null) return null
        return memories.firstOrNull { abs(it.hz - hz) <= 50 && (mode == null || it.mode == mode) }
    }
}
