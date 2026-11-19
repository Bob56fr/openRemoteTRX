// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class PowerLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
}

/** Allumage et extinction du poste (fonction « power », lot P3) : même fonctionnement que la page (lot P2). */
class PowerTest {
    private fun hello(features: String = "\"ptt\",\"power\"", role: String = "operator") =
        """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features],
            "capabilities":{"modes":["USB"],"can_set_power":true,"can_get_power":true}}"""

    private fun state(power: String) =
        """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true,"power":"$power"}}"""

    private fun session(features: String = "\"ptt\",\"power\"", role: String = "operator", auto: Boolean = false): Pair<RigSession, PowerLink> {
        val link = PowerLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, hello(features, role))
        return s to link
    }

    private fun PowerLink.commands(name: String) = sent.filter { "\"cmd\":\"$name\"" in it }
    private fun PowerLink.idOf(name: String) = Regex("\"id\":(\\d+)").find(commands(name).last())!!.groupValues[1]

    @Test
    fun `vues - fenetre, bandeau et STOP maintenu comme la page`() {
        assertNull(Power.dialog(null))
        val running = Power.dialog(PowerRun(steps = mapOf("ports" to PowerStep("ok"), "wait" to PowerStep("running", remainingS = 21.2))))!!
        assertEquals(listOf("ok", "pending", "pending", "running", "pending"), running.lines.map { it.status })
        assertEquals("encore 22 s au plus", running.lines[3].detail)
        assertTrue(running.canHide && !running.canRetry)
        val failed = Power.dialog(PowerRun(status = "error", error = "Allumage impossible : port",
            steps = mapOf("ports" to PowerStep("error", "port COM6 absent", "ORT-2809"))))!!
        assertEquals("port COM6 absent [ORT-2809]", failed.lines[0].detail)
        assertTrue(failed.canRetry && failed.canContinue)
        assertEquals(3000L, Power.dialog(PowerRun(status = "done", done = "TRX allumé"))!!.autoCloseMs)
        assertNull(Power.dialog(PowerRun(hidden = true)))
        assertEquals("POSTE ÉTEINT", Power.carTitle("off", null))
        assertEquals("ALLUMAGE DU POSTE…", Power.carTitle("off", PowerRun()))
        assertEquals("POSTE ÉTEINT : erreur", Power.carTitle("off", PowerRun(status = "error")))
        assertNull(Power.carTitle("on", null))
    }

    @Test
    fun `connexion demandee a un poste eteint - power_on une fois, etapes, reussite`() {
        val (s, link) = session()
        s.onMessage(1, state("off"))
        assertEquals(1, link.commands("power_on").size)
        assertTrue("\"how\":\"connect\"" in link.commands("power_on")[0])
        s.onMessage(2, state("off"))
        assertEquals(1, link.commands("power_on").size)                       // une fois par connexion
        assertEquals("POSTE ÉTEINT : allumage en cours…", s.snapshot.powerBanner?.text)
        assertEquals("ALLUMAGE DU POSTE…", s.snapshot.powerCarTitle)
        s.onMessage(3, """{"type":"power_progress","step":"wait","status":"running","detail":"","remaining_s":25}""")
        assertEquals("running", s.snapshot.powerDialog!!.lines[3].status)
        s.onMessage(4, """{"type":"result","id":${link.idOf("power_on")},"ok":true,"result":"on","rig":"7 074,00 kHz USB, en réception"}""")
        assertEquals("done", s.snapshot.powerDialog!!.status)
        assertEquals("TRX allumé : 7 074,00 kHz USB, en réception", s.snapshot.powerDialog!!.text)
        s.powerHide(5)
        assertNull(s.snapshot.powerDialog)
    }

    @Test
    fun `refus explicite, reessayer, et la commande attend 150 s avant pas de reponse`() {
        val (s, link) = session()
        s.onMessage(1, state("off"))
        s.onMessage(9_900, state("off"))                                    // la station parle (sinon : liaison morte)
        s.tick(10_000, true)
        assertNotNull(s.snapshot.powerDialog)                                // 10 s : pas encore « pas de réponse »
        assertEquals("running", s.snapshot.powerDialog!!.status)
        s.onMessage(11_000, """{"type":"result","id":${link.idOf("power_on")},"ok":false,"reason":"port_moved","ort":"ORT-2809",
            "step":"ports","detail":"le poste est maintenant sur COM7 (station.toml dit COM6)"}""")
        val v = s.snapshot.powerDialog!!
        assertEquals("error", v.status)
        assertTrue(v.text.contains("maintenant sur COM7") && v.text.contains("[ORT-2809]"))
        assertEquals("error", v.lines[0].status)
        assertEquals("POSTE ÉTEINT : erreur", s.snapshot.powerCarTitle)
        s.powerOn(12_000)
        assertTrue("\"how\":\"button\"" in link.commands("power_on").last())
        val late = 12_000 + RigSession.POWER_ON_TIMEOUT_MS + 1
        s.onMessage(late - 100, state("off"))
        s.tick(late, true)
        assertEquals("error", s.snapshot.powerDialog!!.status)
        assertTrue(s.snapshot.powerDialog!!.text.contains("pas de réponse"))
    }

    @Test
    fun `jamais sans la fonction, jamais pour un visiteur, jamais a une reconnexion automatique`() {
        val (s1, l1) = session(features = "\"ptt\"")
        s1.onMessage(1, state("off"))
        assertTrue(l1.commands("power_on").isEmpty())
        assertEquals("POSTE ÉTEINT : allumage à distance hors service (menu 2.8 de TRX Console sur la station).", s1.snapshot.powerBanner?.text)
        assertEquals("Arrêt à distance hors service : menu 2.8 de TRX Console", s1.snapshot.stopHold.powerReason)
        val (s2, l2) = session(role = "listener")
        s2.onMessage(1, state("off"))
        assertTrue(l2.commands("power_on").isEmpty())
        assertEquals("Le poste est éteint ; seul un opérateur peut l'allumer.", s2.snapshot.powerBanner?.text)
        assertEquals("Compte visiteur", s2.snapshot.stopHold.powerReason)
        // connexion demandée, poste allumé ; liaison perdue puis reconnexion automatique à un poste éteint : rien
        val (s3, l3) = session()
        s3.onMessage(1, state("on"))
        s3.onLinkClosed(2, "silence")
        s3.tick(5_000, true)
        s3.answered(5_000)
        s3.onMessage(5_100, hello())
        s3.onMessage(5_200, state("off"))
        assertTrue(l3.commands("power_on").isEmpty())
        assertFalse(s3.snapshot.stopHold.powerOff)                          // déjà éteint
        assertEquals("Le poste est déjà éteint", s3.snapshot.stopHold.powerReason)
    }

    @Test
    fun `Android Auto - POSTE ETEINT en titre, aucun bouton d'allumage`() {
        val (s, _) = session(features = "\"ptt\"")
        s.onMessage(1, state("off"))
        val screen = Car.screen(s.snapshot, "Station", muted = false, micAllowed = true)
        assertEquals("POSTE ÉTEINT", screen.title)
        assertTrue(screen.buttons.none { it.label.contains("Allumer") })
        s.onMessage(2, state("on"))
        assertFalse(Car.screen(s.snapshot, "Station", muted = false, micAllowed = true).title.contains("ÉTEINT"))
    }

    @Test
    fun `arret confirme - power_off avec confirm, refus garde pour sa fenetre`() {
        val (s, link) = session()
        s.onMessage(1, state("on"))
        assertTrue(s.snapshot.stopHold.powerOff)
        s.powerOff(2)
        assertTrue("\"confirm\":true" in link.commands("power_off").single())
        s.onMessage(3, """{"type":"result","id":${link.idOf("power_off")},"ok":false,"reason":"local_active","detail":"poste utilisé sur place","ort":"ORT-5005"}""")
        assertTrue(s.snapshot.powerOffNotice.isNotEmpty())
        s.clearPowerOffNotice(4)
        assertEquals("", s.snapshot.powerOffNotice)
    }
}
