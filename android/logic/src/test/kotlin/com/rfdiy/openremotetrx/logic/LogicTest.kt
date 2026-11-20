// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.PttStatus
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PttViewTest {
    @Test
    fun `emission de ce telephone, d'un autre, et reception`() {
        val mine = PttView.of(PttStatus(state = "KEYING", owner = "phone"), "phone")
        assertTrue(mine.transmitting && mine.mine && !mine.other)
        assertEquals("PRISE D'ÉMISSION", mine.label)
        val other = PttView.of(PttStatus(state = "TX", owner = "pc", totRemainingS = 12.2), "phone")
        assertTrue(other.transmitting && other.other && !other.mine)
        assertEquals(13, other.totSeconds)
        val rx = PttView.of(PttStatus(state = "RX", totRemainingS = 50.0, lastCutReason = "heartbeat"), "phone")
        assertFalse(rx.transmitting); assertNull(rx.totSeconds)
        assertEquals("perte du signal de vie du client", rx.lastCut)
    }

    @Test
    fun `poste utilise sur place - reprise possible sauf pendant l'emission locale`() {
        val waiting = PttView.of(PttStatus(localRemainingS = 95.4, localReason = "frequency"), "phone")
        assertTrue(waiting.canReleaseLocal)
        assertEquals("POSTE UTILISÉ SUR PLACE (fréquence changée sur le poste) : PTT à distance bloqué encore 1:36", waiting.local)
        val talking = PttView.of(PttStatus(localRemainingS = 120.0, localReason = "tx", localTx = true), "phone")
        assertFalse(talking.canReleaseLocal)
        assertTrue(talking.local!!.endsWith("pendant l'émission locale"))
        assertNull(PttView.of(PttStatus(), "phone").local)
        assertFalse(PttView.of(PttStatus(), "phone").canReleaseLocal)
    }

    @Test
    fun `alerte de temperature et etat inconnu`() {
        assertEquals("hot", PttView.of(PttStatus(tempAlert = "hot"), "phone").tempAlert)
        assertEquals("", PttView.of(PttStatus(tempAlert = "bizarre"), "phone").tempAlert)
        assertEquals("FUTUR", PttView.of(PttStatus(state = "FUTUR"), "phone").label)
    }
}

class LinkTest {
    @Test
    fun `battements - grace des le toggle, puis tant que l'emission est a moi`() {
        val hb = HeartbeatPolicy()
        assertFalse(hb.shouldBeat(0, mineActive = false))
        hb.onToggleSent(1000)
        assertTrue(hb.shouldBeat(3999, mineActive = false))
        assertFalse(hb.shouldBeat(4000, mineActive = false))
        assertTrue(hb.shouldBeat(10_000, mineActive = true))
        hb.onToggleSent(20_000); hb.onDisconnected()
        assertFalse(hb.shouldBeat(20_100, mineActive = false))
    }

    @Test
    fun `silence de la station - alerte unique pendant mon emission, puis liaison perdue`() {
        val watch = LinkWatch()
        assertEquals(LinkVerdict.OK, watch.check(99_999, mineActive = true))          // rien reçu : rien à juger
        watch.onMessage(0)
        assertEquals(LinkVerdict.OK, watch.check(1500, mineActive = true))
        assertEquals(LinkVerdict.TX_SILENCE, watch.check(1600, mineActive = true))
        assertEquals(LinkVerdict.OK, watch.check(2000, mineActive = true))           // une seule alerte par silence
        assertEquals(LinkVerdict.STALE, watch.check(5001, mineActive = false))
        watch.onMessage(6000)
        assertEquals(LinkVerdict.OK, watch.check(7600, mineActive = false))          // en réception : pas d'alerte courte
    }

    @Test
    fun `reconnexion - 400 ms, puis 1,5 3 et 4,5 s, arret sur identifiants refuses ou fenetre ecoulee`() {
        val r = ReconnectPolicy(windowS = 30, startedAt = 0)
        assertFalse(r.due(399, online = true)); assertTrue(r.due(400, online = true))
        assertFalse(r.due(400, online = false))                                     // pas de réseau : on attend
        r.attemptStarted(); assertFalse(r.due(500, online = true))
        assertNull(r.attemptFailed(1000, authRefused = false)); assertEquals(2500, r.nextAt)
        r.attemptStarted(); r.attemptFailed(3000, false); assertEquals(6000, r.nextAt)
        r.attemptStarted(); r.attemptFailed(7000, false); assertEquals(11_500, r.nextAt)
        r.attemptStarted(); r.attemptFailed(12_000, false); assertEquals(16_500, r.nextAt)   // 4,5 s au plus
        assertTrue(r.expired(30_000)); assertFalse(r.due(30_000, true))
        r.attemptStarted()
        assertEquals(ReconnectOutcome.AUTH, r.attemptFailed(13_000, authRefused = true))
        assertEquals(300, ReconnectPolicy(9999, 0).windowS)
        assertFalse(ReconnectPolicy(0, 0).enabled)
    }

    @Test
    fun `armement - toujours desarme a la connexion`() {
        val arming = TxArming()
        arming.arm(); assertTrue(arming.armed)
        arming.onConnected(); assertFalse(arming.armed)
    }
}

class TextsTest {
    private val repo = File(System.getProperty("trx.repo") ?: "../..")
    private val page = File(repo, "trxstation/gateway/api/static/client.js").readText()

    /** Tronc commun de la station (trxstation/i18n/client.<langue>.json), sans passer par la copie de Gradle. */
    private fun stationKeys(lang: String): Set<String> =
        Regex("""^\s*"([^"]+)":""", RegexOption.MULTILINE).findAll(File(repo, "trxstation/i18n/client.$lang.json").readText())
            .map { it.groupValues[1] }.toSet()

    @Test
    fun `refus et coupures lus dans le tronc commun copie a la compilation`() {
        for (lang in Tr.LANGS) assertEquals(stationKeys(lang), Tr.catalog(lang).keys intersect stationKeys("fr"), lang)
        val fr = stationKeys("fr")
        assertEquals(fr.filter { it.startsWith("refus.") && !it.startsWith("refus._") }.map { it.removePrefix("refus.") }.toSet(),
            Texts.REFUSALS.keys)
        assertEquals(fr.filter { it.startsWith("coupure.") }.map { it.removePrefix("coupure.") }.toSet(), Texts.CUTS.keys)
    }

    @Test
    fun `memes causes de perte de liaison que la page`() {
        val body = Regex("""function lossReasons\(\) \{(.*?)\n  \}""", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        val codes = Regex("""^\s*([a-z_]+): \{""", RegexOption.MULTILINE).findAll(body).map { it.groupValues[1] }.toSet()
        assertTrue(codes.isNotEmpty())
        assertEquals(emptySet(), codes - Texts.LOSSES.keys)
    }

    @Test
    fun `code inconnu - detail de la station ou code`() {
        assertEquals("Fréquence hors des bandes d'émission autorisées.", Texts.refusal("out_of_band"))
        assertEquals("détail", Texts.refusal("nouveau", "détail"))
        assertEquals("Refusé par la station (nouveau).", Texts.refusal("nouveau"))
        assertEquals("Refusé par la station (_inconnu).", Texts.refusal("_inconnu"))
        assertEquals("durée maximale d'émission atteinte", Texts.cut("tot"))
        assertEquals("nouveau", Texts.cut("nouveau"))
    }

    @Test
    fun `langue choisie - repli sur le francais puis la cle`() {
        try {
            Tr.lang = "de"
            assertEquals("Frequenz außerhalb der erlaubten Sendebänder.", Texts.refusal("out_of_band"))
            assertEquals("Von der Station abgelehnt (x).", Texts.refusal("x"))
            assertEquals("cle.absente", Tr.t("cle.absente"))
            Tr.lang = "xx"
            assertEquals("fr", Tr.lang)
        } finally {
            Tr.lang = "fr"
        }
    }

    @Test
    fun `choix de la langue - telephone, puis anglais, puis francais`() {
        val all = Tr.LANGS
        assertEquals("de", Tr.chooseLang(null, listOf("de-DE", "en-US"), all))
        assertEquals("es", Tr.chooseLang("es", listOf("de-DE"), all))
        assertEquals("en", Tr.chooseLang(null, listOf("it-IT"), all))
        assertEquals("fr", Tr.chooseLang(null, listOf("de-DE"), listOf("fr")))
        assertEquals("fr", Tr.chooseLang("de", emptyList()))                       // proposé aujourd'hui : français seul
    }
}

class FormatTest {
    @Test
    fun `frequence et S-metre comme la page`() {
        assertEquals("14 074 000 Hz", Format.frequency(14_074_000))
        assertEquals("475 000 Hz", Format.frequency(475_000))
        assertEquals("—", Format.frequency(null))
        assertEquals("S9", Format.sMeter(0.0))
        assertEquals("S9+20 dB", Format.sMeter(20.4))
        assertEquals("S7", Format.sMeter(-12.0))
        assertEquals("S0", Format.sMeter(-80.0))
        assertEquals("1:05", Format.duration(65))
    }
}
