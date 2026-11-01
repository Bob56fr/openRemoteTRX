// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class HeadsetMicTest {
    @Test
    fun `micro ouvert seulement quand le casque est en mode appel, rendu a la fin`() {
        val h = HeadsetMic()
        assertEquals(HeadsetMicStep.None, h.micWanted(false, 0))             // réception : rien
        assertEquals(HeadsetMicStep.Route, h.micWanted(true, 100))
        assertEquals(HeadsetMicStep.None, h.micWanted(true, 200))            // états suivants : une seule bascule
        assertEquals(HeadsetMicStep.None, h.routed(false))                   // passage transitoire (relevé sur le S25)
        assertEquals(HeadsetMicStep.OpenMic, h.routed(true))
        assertEquals(HeadsetMicStep.None, h.routed(true))
        assertEquals(HeadsetMicStep.Release, h.micWanted(false, 5000))
        assertEquals(HeadsetMicStep.None, h.routed(false))                   // notre propre retour à la musique
        assertEquals(HeadsetMicStep.Route, h.micWanted(true, 9000))          // émission suivante
    }

    @Test
    fun `bouton du casque pendant l'emission - STOP, une seule fois`() {
        val h = HeadsetMic()
        h.micWanted(true, 0)
        h.routed(true)
        val step = h.routed(false)                                           // Android a raccroché l'appel virtuel
        assertIs<HeadsetMicStep.Stop>(step)
        assertEquals(false, step.failure)                                    // geste normal : pas de son de refus
        assertEquals(HeadsetMicStep.None, h.routed(false))
        assertEquals(HeadsetMicStep.None, h.micWanted(true, 100))           // la station n'a pas encore répondu
        assertEquals(HeadsetMicStep.None, h.tick(10_000))
        assertEquals(HeadsetMicStep.Release, h.micWanted(false, 400))        // RX confirmé
    }

    @Test
    fun `mode appel jamais etabli - STOP apres le delai, micro jamais ouvert`() {
        val h = HeadsetMic()
        h.micWanted(true, 1000)
        assertEquals(HeadsetMicStep.None, h.tick(1000 + HeadsetMic.TIMEOUT_MS - 1))
        val step = h.tick(1000 + HeadsetMic.TIMEOUT_MS)
        assertIs<HeadsetMicStep.Stop>(step)
        assertEquals(true, step.failure)
        assertEquals(HeadsetMicStep.None, h.routed(true))                    // casque arrivé trop tard : rien ne s'ouvre
    }

    @Test
    fun `casque absent ou refuse par Android - STOP, jamais le micro du telephone`() {
        val h = HeadsetMic()
        h.micWanted(true, 0)
        val step = h.routeFailed("aucun casque")
        assertIs<HeadsetMicStep.Stop>(step)
        assertEquals("aucun casque", step.why)
        assertEquals(HeadsetMicStep.None, h.routeFailed("encore"))
        assertEquals(HeadsetMicStep.None, h.routed(true))
    }

    @Test
    fun `refus hors ouverture et remise a zero a la deconnexion`() {
        val h = HeadsetMic()
        assertEquals(HeadsetMicStep.None, h.routeFailed("x"))                // rien en cours : rien à couper
        assertEquals(HeadsetMicStep.None, h.routed(false))
        h.micWanted(true, 0)
        h.routed(true)
        h.reset()
        assertEquals(HeadsetMicStep.None, h.routed(false))                   // liaison fermée : plus d'émission à couper
        assertEquals(HeadsetMicStep.Route, h.micWanted(true, 50))
    }
}
