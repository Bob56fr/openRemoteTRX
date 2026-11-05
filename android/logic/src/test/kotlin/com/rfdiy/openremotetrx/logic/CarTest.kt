// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Memory
import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CarTest {
    private val memories = listOf(Memory("m1", "40 mètres", 7_100_000, "LSB"), Memory("m2", "Relais Rennes", 145_600_000, "FM"))

    private fun ptt(transmitting: Boolean, mine: Boolean, tot: Int? = null, canRelease: Boolean = false) =
        PttView(transmitting, mine, other = transmitting && !mine, label = if (transmitting) "TX" else "RX", totSeconds = tot,
            totWarning = false, local = null, canReleaseLocal = canRelease, tempAlert = "", fault = "", lastCut = "")

    private fun rig(ptt: PttView?, armed: Boolean, hz: Long = 7_100_000) = RigState(
        status = LinkStatus.CONNECTED, ptt = ptt, armed = armed, memories = memories,
        state = ServerMessages.decode(
            """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true,"frequency_hz":$hz,"mode":"LSB","strength_db":-12}}"""
        ) as State,
    )

    private fun ids(s: CarScreen) = s.buttons.map { it.action }

    @Test
    fun `deconnecte - seulement le cadenas barre, invitation a choisir une station`() {
        val s = Car.screen(RigState(), null, muted = false, micAllowed = true)
        assertEquals("Déconnecté", s.title)
        assertEquals(listOf(Car.LOCK_UNKNOWN), s.buttons)
        assertFalse(s.connected)
        assertEquals("Ouvrez l'application", Car.screen(RigState(), null, false, true, "Ouvrez l'application").error)
    }

    @Test
    fun `reception non armee - STOP et Autoriser, jamais EMETTRE`() {
        val s = Car.screen(rig(ptt(false, false), armed = false), "Maison", muted = false, micAllowed = true)
        assertEquals("7.100.00 LSB", s.title)                           // toujours la fréquence (format de l'utilisateur)
        assertEquals("S7  VFO", s.subtitle)                         // mémoire NON favorite : VFO ; aucun réglage publié
        assertEquals("LSB · émission non autorisée · Maison", s.secondary)
        val fav = Car.screen(rig(ptt(false, false), armed = false).let { it.copy(memories = it.memories.map { m -> m.copy(favorite = true) }) },
            "Maison", false, true)
        assertEquals("S7  M: 40 mètres", fav.subtitle)              // favori : son nom, pas son rang
        assertEquals(listOf(CarAction.ARM, CarAction.STOP), ids(s))   // cadenas à la place du micro
    }

    private fun lock(s: CarScreen) = s.buttons.single { it.icon.name.startsWith("LOCK") }

    @Test
    fun `cadenas - quatre etats distincts, pictogramme et libelle suivent l etat relu`() {
        val closed = lock(Car.screen(rig(ptt(false, false), armed = false), "M", false, true))
        assertEquals(CarButton(CarAction.ARM, "Émission verrouillée", CarIcon.LOCK_CLOSED), closed)
        val open = lock(Car.screen(rig(ptt(false, false), armed = true), "M", false, true))
        assertEquals(CarButton(CarAction.DISARM, "Émission autorisée", CarIcon.LOCK_OPEN), open)
        val tx = lock(Car.screen(rig(ptt(true, true, tot = 30), armed = true), "M", false, true))
        assertEquals(CarButton(CarAction.LOCK_INFO, "En émission", CarIcon.LOCK_TX), tx)
        val lost = RigState(status = LinkStatus.RECONNECTING, armed = true)
        assertEquals(CarIcon.LOCK_UNKNOWN, lock(Car.screen(lost, "M", false, true)).icon)
        assertEquals(CarIcon.LOCK_UNKNOWN, lock(Car.screen(RigState(status = LinkStatus.CONNECTING), "M", false, true)).icon)
        // Non-régression (étape 127) : ouvert et fermé n'ont plus le même pictogramme.
        assertTrue(closed.icon != open.icon)
    }

    @Test
    fun `cadenas sans effet - ne prend jamais l emission`() {
        assertFalse(CarAction.LOCK_INFO.takesTransmission)
        assertTrue(Car.allowed(CarAction.LOCK_INFO, null, mine = false))
        val rx = Car.screen(rig(ptt(false, false), true), "M", muted = false, micAllowed = false)
        assertEquals(CarButton(CarAction.LOCK_INFO, "Réception seule", CarIcon.LOCK_CLOSED), lock(rx))
    }

    @Test
    fun `armee - EMETTRE, en emission - FIN D'EMISSION et STOP, etat explicite`() {
        assertEquals(listOf(CarAction.PTT, CarAction.STOP, CarAction.DISARM), ids(Car.screen(rig(ptt(false, false), true), "M", false, true)))
        val tx = Car.screen(rig(ptt(true, true, tot = 65), true), "M", false, true)
        assertEquals("7.100.00 LSB ÉMISSION 1:05", tx.title)
        assertEquals("FIN D'ÉMISSION", tx.buttons.first().label)
        assertEquals(listOf(CarAction.PTT, CarAction.STOP, CarAction.LOCK_INFO), ids(tx))
    }

    @Test
    fun `autre client en emission ou reception seule - STOP seulement`() {
        assertEquals(listOf(CarAction.DISARM, CarAction.STOP), ids(Car.screen(rig(ptt(true, false), true), "M", false, true)))
        val rx = Car.screen(rig(ptt(false, false), true), "M", muted = true, micAllowed = false)
        assertEquals(listOf(CarAction.LOCK_INFO, CarAction.STOP), ids(rx))
        assertFalse(rx.playing)
        assertTrue("réception seule" in rx.secondary && "muet" in rx.secondary)
        assertTrue(CarAction.RELEASE_LOCAL in ids(Car.screen(rig(ptt(false, false, canRelease = true), false), "M", false, true)))
    }

    @Test
    fun `seules la voiture et l'application prennent l emission, couper est permis a tous`() {
        val auto = "com.google.android.projection.gearhead"
        assertTrue(Car.allowed(CarAction.PTT, auto, mine = false))
        assertTrue(Car.allowed(CarAction.ARM, "com.rfdiy.openremotetrx", mine = false))
        assertFalse(Car.allowed(CarAction.PTT, "com.android.systemui", mine = false))
        assertFalse(Car.allowed(CarAction.ARM, "com.example.malin", mine = false))
        assertFalse(Car.allowed(CarAction.PTT, null, mine = false))
        assertTrue(Car.allowed(CarAction.PTT, "com.android.systemui", mine = true))     // fin de SON émission
        assertTrue(Car.allowed(CarAction.STOP, null, mine = false))
        assertTrue(Car.allowed(CarAction.DISARM, "com.example.malin", mine = false))
    }

    @Test
    fun `frequence lisible et memoire reconnue`() {
        assertEquals("145 600,00 kHz", Car.frequency(145_600_000))
        assertEquals("14 074,50 kHz", Car.frequency(14_074_500))
        assertEquals("m1", Car.memoryAt(memories, 7_100_030, "LSB")?.id)
        assertEquals(null, Car.memoryAt(memories, 7_100_000, "USB"))
    }
}

class VoiceTest {
    private val memories = listOf(Memory("m1", "40 mètres", 7_100_000, "LSB"), Memory("m2", "Relais Rennes", 145_600_000, "FM"))

    @Test
    fun `memoire, bande, frequence, ecoute`() {
        assertEquals(VoiceAction.Listen, Voice.parse("", memories))
        assertEquals("m1", (Voice.parse("Mémoire 40 mètres", memories) as VoiceAction.RecallMemory).memory.id)
        assertEquals("m2", (Voice.parse("relais rennes", memories) as VoiceAction.RecallMemory).memory.id)
        assertEquals("m2", (Voice.parse("mémoire Rennes", memories) as VoiceAction.RecallMemory).memory.id)
        assertEquals(VoiceAction.SelectBand("20"), Voice.parse("bande 20 mètres", memories))
        assertEquals(VoiceAction.SelectBand("80"), Voice.parse("80 m", memories))
        assertEquals(VoiceAction.SetFrequency(7_074_000), Voice.parse("fréquence 7 074", memories))
        assertEquals(VoiceAction.SetFrequency(27_555_000), Voice.parse("QSY 27 555", memories))
        assertEquals(VoiceAction.SetFrequency(145_500_000), Voice.parse("fréquence 145,5 mégahertz", memories))
        assertEquals(VoiceAction.SetFrequency(14_200_000), Voice.parse("14200", memories))
    }

    @Test
    fun `jamais d'emission par la voix, phrase inconnue rejetee`() {
        for (said in listOf("émettre", "PTT", "passe en émission", "mémoire inconnue", "fréquence beaucoup")) {
            assertTrue(Voice.parse(said, memories) is VoiceAction.Unknown, said)
        }
        assertEquals(null, Voice.frequency("0"))
        assertEquals(7_074_000, Voice.frequency("7.074"))
        assertEquals(7_074_000, Voice.frequency("7074 kHz"))
    }
}

class DrivingTest {
    @Test
    fun `mode conduite - voiture connectee ou reglage, PTT tactile interdit, passager seulement si voiture`() {
        val car = Driving.reason(manual = false, auto = true, carConnected = true, passenger = false)
        assertEquals(DrivingReason.CAR, car)
        assertFalse(Driving.touchPttAllowed(car))
        assertEquals(DrivingReason.MANUAL, Driving.reason(manual = true, auto = true, carConnected = true, passenger = true))  // le réglage prime
        val passenger = Driving.reason(manual = false, auto = true, carConnected = true, passenger = true)
        assertEquals(DrivingReason.PASSENGER, passenger)
        assertTrue(Driving.touchPttAllowed(passenger))
        assertEquals(DrivingReason.OFF, Driving.reason(manual = false, auto = false, carConnected = true, passenger = false))
        assertEquals(DrivingReason.OFF, Driving.reason(manual = false, auto = true, carConnected = false, passenger = true))
        assertTrue(Driving.touchPttAllowed(DrivingReason.OFF))
    }
}
