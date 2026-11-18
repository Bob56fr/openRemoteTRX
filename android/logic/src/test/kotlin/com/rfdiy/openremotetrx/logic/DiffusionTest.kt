// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.DiffusionStatus
import com.rfdiy.openremotetrx.protocol.DiffusionStop
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class DifLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
    fun last(): String = sent.last()
    fun idOfLast(): Int = Regex("\"id\":(\\d+)").find(sent.last())!!.groupValues[1].toInt()
}

class DiffusionTest {
    private val page = File(System.getProperty("trx.repo") ?: "../..",
                            "trxstation/gateway/api/static/diffusion.js").readText()

    /** Textes d'un objet JS « const NOM = { cle: "texte", … }; » de diffusion.js. */
    private fun jsMap(name: String): Map<String, String> {
        val body = Regex("const $name = \\{(.*?)\\};", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
        return Regex("([a-z_]+): \"([^\"]*)\"").findAll(body).associate { it.groupValues[1] to it.groupValues[2] }
    }

    @Test
    fun `memes textes que la page`() {
        assertEquals(jsMap("STOPS"), Diffusions.STOPS.toMap())
        assertEquals(jsMap("PHASES"), Diffusions.PHASES.toMap())
        assertEquals(jsMap("SILENCES"), Diffusions.SILENCES.toMap())
        val meta = Regex("\\[\"(\\w+)\", \"([^\"]+)\"\\]").findAll(
            Regex("const META = \\[(.*?)\\];", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1])
            .map { it.groupValues[1] to it.groupValues[2] }.toList()
        assertEquals(meta, Diffusions.META)
        val warning = Regex("const WARNING = (.*?);\\n", RegexOption.DOT_MATCHES_ALL).find(page)!!.groupValues[1]
            .split(Regex("\"\\s*\\+\\s*\"")).joinToString("").trim().removePrefix("\"").removeSuffix("\"")
        assertEquals(warning, Diffusions.WARNING)
    }

    @Test
    fun `indicateur et etat - memes cas que la page`() {
        assertNull(Diffusions.indicator(null))
        assertNull(Diffusions.indicator(DiffusionStatus(active = false)))
        val live = DiffusionStatus(enabled = true, active = true, access = "prive", phase = "en_direct", listeners = 2,
                                   operator = "BOB", remainingS = 2520, silence = "hors_bandes")
        val ind = Diffusions.indicator(live)!!
        assertEquals("DIFFUSION · 🎧 2 · 42 min · 🔇", ind.text)
        assertTrue(ind.live)
        assertTrue(ind.title.contains("Silence pour les auditeurs : réception hors des bandes autorisées"))
        assertFalse(Diffusions.indicator(live.copy(phase = "nouvel_essai"))!!.live)
        assertEquals("DIFFUSION · sans limite", Diffusions.indicator(DiffusionStatus(active = true, phase = "en_direct"))!!.text)
        assertEquals("1 h 05", Diffusions.remaining(3900))
        assertTrue(Diffusions.status(live).contains("voix émise NON diffusée"))
        assertTrue(Diffusions.status(live).contains("SILENCE pour les auditeurs"))
        assertEquals("Diffusion hors service ([diffusion] de station.toml, menu 8.1).", Diffusions.status(DiffusionStatus()))
        assertTrue(Diffusions.status(DiffusionStatus(enabled = true, lastStop = DiffusionStop("overload"))).contains("surchargée"))
        assertEquals("Diffusion indisponible sur cette station.", Diffusions.status(null))
    }

    @Test
    fun `formulaire - prive, 1 h, tout diffuse, voix coupee par defaut, limites`() {
        val (args, err) = Diffusions.startArgs(Diffusions.Form())
        assertNull(err)
        assertEquals("prive", (args!!["access"] as JsonPrimitive).content)
        assertEquals(1, (args["hours"] as JsonPrimitive).content.toInt())
        assertEquals("false", (args["voice"] as JsonPrimitive).content)
        assertEquals(Diffusions.DEFAULT_META, args["meta"]!!.jsonArray.map { (it as JsonPrimitive).content })
        assertEquals(JsonNull, Diffusions.startArgs(Diffusions.Form(hours = null)).first!!["hours"])
        assertTrue(Diffusions.startArgs(Diffusions.Form(hours = 25)).second!!.startsWith("Durée"))
        assertTrue(Diffusions.startArgs(Diffusions.Form(pseudo = "x".repeat(33))).second!!.startsWith("Pseudo"))
        assertTrue(Diffusions.startArgs(Diffusions.Form(message = "a\u0007b")).second!!.contains("invalide"))
        assertEquals("BOB", (Diffusions.startArgs(Diffusions.Form(pseudo = " BOB ")).first!!["pseudo"] as JsonPrimitive).content)
        assertTrue(Diffusions.passwordOk("Abcd23456789")); assertFalse(Diffusions.passwordOk("court"))
    }

    private fun session(features: String, role: String = "operator"): Pair<RigSession, DifLink> {
        val link = DifLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30)
        s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"$role","features":[$features]}""")
        return s to link
    }

    @Test
    fun `session - etat, avertissement au premier lancement, arret, mot de passe`() {
        val (s, link) = session("\"ptt\",\"diffusion\"")
        s.onMessage(1, """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true},"diffusion":{"enabled":true,"active":false,"listener_user":"auditeur","listen_page":"https://d.example.org/ecoute/b"}}""")
        val d = s.snapshot.diffusion!!
        assertEquals("auditeur", d.user)
        assertEquals("https://d.example.org/ecoute/b", d.status!!.listenPage)
        s.diffusionStart(2, Diffusions.startArgs(Diffusions.Form()).first!!)
        assertTrue(link.last().contains("\"cmd\":\"diffusion\"") && link.last().contains("\"action\":\"start\""))
        s.onMessage(3, """{"type":"result","id":${link.idOfLast()},"ok":false,"reason":"diffusion_confirm_required","ort":"ORT-6109"}""")
        assertTrue(s.snapshot.diffusion!!.confirm)                      // la fenêtre pose la question, aucun refus affiché
        assertEquals("", s.snapshot.diffusion!!.notice)
        s.diffusionConfirm(4, true)
        assertTrue(link.last().contains("\"confirm\":true"))
        assertFalse(s.snapshot.diffusion!!.confirm)
        s.onMessage(5, """{"type":"result","id":${link.idOfLast()},"ok":true}""")
        assertEquals("Diffusion lancée.", s.snapshot.diffusion!!.notice)
        s.diffusionReveal(6)
        s.onMessage(7, """{"type":"result","id":${link.idOfLast()},"ok":true,"action":"reveal","data":{"listener_user":"auditeur","listener_password":"Abcdef234567"}}""")
        assertEquals("Abcdef234567", s.snapshot.diffusion!!.password)
        s.diffusionForget(8)                                             // fenêtre fermée : mot de passe oublié
        assertNull(s.snapshot.diffusion!!.password)
        s.diffusionStop(9)
        s.onMessage(10, """{"type":"result","id":${link.idOfLast()},"ok":false,"reason":"diffusion_busy","ort":"ORT-6109"}""")
        assertTrue(s.snapshot.diffusion!!.noticeBad)
        assertTrue(s.snapshot.diffusion!!.notice.contains("ORT-6109"))
        s.diffusionStart(11, Diffusions.startArgs(Diffusions.Form()).first!!)
        s.onMessage(12, """{"type":"result","id":${link.idOfLast()},"ok":false,"reason":"diffusion_confirm_required"}""")
        val sentBefore = link.sent.size
        s.diffusionConfirm(13, false)                                    // « Annuler » : rien n'est lancé
        assertEquals(sentBefore, link.sent.size)
        assertEquals("Diffusion non lancée.", s.snapshot.diffusion!!.notice)
    }

    @Test
    fun `station sans diffusion ou visiteur - rien`() {
        val (s, link) = session("\"ptt\"")
        assertNull(s.snapshot.diffusion)
        s.diffusionStart(1, Diffusions.startArgs(Diffusions.Form()).first!!); s.diffusionStop(1); s.diffusionReveal(1)
        assertTrue(link.sent.none { it.contains("\"diffusion\"") })
        val (v, vlink) = session("\"ptt\",\"diffusion\"", role = "listener")
        v.onMessage(1, """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true},"diffusion":{"enabled":true}}""")
        assertNull(v.snapshot.diffusion)
        v.diffusionStop(2)
        assertTrue(vlink.sent.none { it.contains("\"cmd\":\"diffusion\"") })
    }
}
