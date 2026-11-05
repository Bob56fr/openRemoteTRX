// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Memory
import java.util.Locale
import kotlin.math.abs

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
    ;

    /** Prend l'émission ou l'autorise : réservé à l'écran de la voiture et à l'application elle-même. */
    val takesTransmission: Boolean get() = this == PTT || this == ARM

    companion object {
        fun of(id: String): CarAction? = entries.firstOrNull { it.id == id }
    }
}

/** Pictogramme d'un bouton de la voiture ; le cadenas suit l'état réel de « Émission autorisée » (F6). */
enum class CarIcon { PTT, STOP, HAND, LOCK_CLOSED, LOCK_OPEN, LOCK_TX, LOCK_UNKNOWN }

/** `label` sert aussi de texte d'accessibilité : il dit l'ÉTAT montré par le pictogramme. */
data class CarButton(val action: CarAction, val label: String, val icon: CarIcon = defaultIcon(action))

private fun defaultIcon(action: CarAction): CarIcon = when (action) {
    CarAction.PTT -> CarIcon.PTT
    CarAction.STOP -> CarIcon.STOP
    CarAction.RELEASE_LOCAL -> CarIcon.HAND
    CarAction.ARM -> CarIcon.LOCK_CLOSED
    CarAction.DISARM -> CarIcon.LOCK_OPEN
    CarAction.LOCK_INFO -> CarIcon.LOCK_UNKNOWN
}

/** Ce que montre l'écran de la voiture : texte seulement (aucun graphique, aucune saisie). */
data class CarScreen(
    val title: String,
    val subtitle: String,
    /** Lecteur « en lecture » : réception audible (pause = réception muette). */
    val playing: Boolean,
    val connecting: Boolean,
    val connected: Boolean,
    val buttons: List<CarButton>,
    /** Message d'erreur à afficher (connexion impossible depuis la voiture…), vide sinon. */
    val error: String = "",
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

    fun screen(rig: RigState, station: String?, muted: Boolean, micAllowed: Boolean, notice: String = ""): CarScreen {
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
        val title = when {
            mine -> "ÉMISSION EN COURS" + (ptt?.totSeconds?.let { " ${Format.duration(it)}" } ?: "")
            ptt?.transmitting == true -> "Émission : ${ptt.label}"
            else -> listOf(frequency(r?.frequencyHz), r?.mode?.let { Radio.modeLabel(it) }).filterNotNull().joinToString(" ")
        }
        val memory = memoryAt(rig.memories, r?.frequencyHz, r?.mode)
        val parts = buildList {
            if (mine) add(listOfNotNull(frequency(r?.frequencyHz), r?.mode?.let { Radio.modeLabel(it) }).joinToString(" "))
            else r?.strengthDb?.let { add(Format.sMeter(it)) }
            memory?.let { add(it.name) }
            ptt?.local?.let { add("poste utilisé sur place") }
            if (!micAllowed) add("réception seule")
            else if (!rig.armed && !mine) add("émission non autorisée")
            if (muted) add("muet")
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
        return CarScreen(title.ifEmpty { name }, parts.joinToString(" · "), playing = !muted, connecting = false,
            connected = true, buttons = buttons, error = notice)
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
