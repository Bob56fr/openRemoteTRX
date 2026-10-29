// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.pow
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class VoiceEqTest {
    private fun shared(name: String): JsonObject =
        Json.parseToJsonElement(File(System.getProperty("trx.repo"), "tests/protocol/$name").readText()).jsonObject

    @Test
    fun `biquads - memes coefficients que la page (vecteurs partages)`() {
        for (case in shared("voice_vectors.json")["cases"]!!.jsonArray) {
            val c = case.jsonObject
            val got = VoiceEq.biquad(c["type"]!!.jsonPrimitive.content, c["hz"]!!.jsonPrimitive.content.toDouble(),
                c["q"]!!.jsonPrimitive.content.toDouble(), c["gain_db"]!!.jsonPrimitive.content.toDouble(), c["rate"]!!.jsonPrimitive.content.toDouble())
            val want = c["coefs"]!!.jsonArray.map { it.jsonPrimitive.content.toDouble() }
            want.forEachIndexed { i, w -> assertTrue(abs(got[i] - w) < 1e-9, "$c : ${got.toList()}") }
        }
    }

    @Test
    fun `prereglages et defauts - identiques a ceux de la page`() {
        val file = shared("voice_presets.json")
        for ((key, preset) in VoiceEq.PRESETS) {
            val page = VoiceEq.importJson(file["presets"]!!.jsonObject[key].toString())
            assertEquals(page, preset.second(), key)
        }
        assertEquals(VoiceEq.importJson(file["defaults"].toString()), VoiceSettings())
        val again = VoiceEq.importJson(VoiceEq.exportJson(VoiceEq.PRESETS.getValue("dx").second()))
        assertEquals(VoiceEq.PRESETS.getValue("dx").second(), again)                   // aller-retour du format commun
    }

    @Test
    fun `reglages valides - bornes, fichier etranger refuse`() {
        val s = VoiceEq.validate(Json.parseToJsonElement(
            """{"enabled":"oui","highpassHz":900,"lowpassHz":1000,"bands":[{"gainDb":99,"q":0}],"chorus":{"type":"inconnu","mix":500},"mic":{"gainDb":-99}}"""
        ).jsonObject)
        assertFalse(s.enabled)
        assertEquals(900.0, s.highpassHz)
        assertEquals(1500.0, s.lowpassHz)
        assertEquals(12.0, s.bands[0].gainDb)
        assertEquals(VoiceEq.Q_MIN, s.bands[0].q)
        assertEquals(10, s.bands.size)
        assertEquals("classic", s.chorus.type)
        assertEquals(100.0, s.chorus.mix)
        assertEquals(-12.0, s.mic.gainDb)
        assertFailsWith<IllegalArgumentException> { VoiceEq.importJson("""{"enabled":true}""") }
        assertFailsWith<IllegalArgumentException> { VoiceEq.importJson("pas du json") }
    }

    private fun sine(hz: Double, dbfs: Double, n: Int, rate: Int = 48000) =
        FloatArray(n) { (10.0.pow(dbfs / 20) * sin(2 * PI * hz * it / rate)).toFloat() }

    private fun peak(buf: FloatArray, from: Int = 0) = buf.drop(from).maxOf { abs(it) }

    @Test
    fun `limiteur toujours actif - crete plafonnee a -3 dBFS, egaliseur eteint ou au maximum`() {
        val ceil = 10.0.pow(-3.0 / 20) + 1e-6
        val off = VoiceDsp(48000).apply { apply(VoiceSettings(mic = MicSettings(gainDb = 20.0))) }
        val a = sine(1000.0, 0.0, 9600).also { off.process(it) }
        assertTrue(peak(a) <= ceil, "éteint : ${peak(a)}")
        val loud = VoiceSettings(enabled = true, bands = VoiceSettings().bands.map { it.copy(gainDb = 12.0) },
            chorus = Chorus(on = true, mix = 100.0), reverb = Reverb(on = true, mix = 100.0, seconds = 4.0), mic = MicSettings(gainDb = 20.0))
        val on = VoiceDsp(48000).apply { apply(loud) }
        val b = sine(880.0, 0.0, 48000).also { on.process(it) }
        assertTrue(peak(b) <= ceil, "au maximum : ${peak(b)}")
        val quiet = sine(1000.0, -30.0, 4800).also { VoiceDsp(48000).process(it) }
        assertTrue(abs(peak(quiet, 480) - 10.0.pow(-30.0 / 20)) < 0.002)         // voix normale : inchangée
    }

    @Test
    fun `fin d'emission - la traine de reverberation et du chorus est coupee net`() {
        val dsp = VoiceDsp(48000).apply { apply(VoiceSettings(enabled = true, reverb = Reverb(on = true, mix = 100.0, seconds = 4.0), chorus = Chorus(on = true, mix = 100.0))) }
        dsp.process(sine(500.0, -6.0, 24000))
        val tail = FloatArray(4800).also { dsp.process(it) }
        assertTrue(peak(tail) > 1e-3, "il y a bien une traîne")
        dsp.setTx(false)
        val after = FloatArray(4800).also { dsp.process(it) }
        assertTrue(peak(after) < 1e-9, "traîne restante : ${peak(after)}")
    }

    @Test
    fun `porte de bruit - attenue sans couper, maintien, coupee par defaut`() {
        val dsp = VoiceDsp(48000).apply { apply(VoiceSettings(mic = MicSettings(gateOn = true, gateDb = -40.0))) }
        repeat(40) { dsp.process(sine(300.0, -60.0, 480)) }                        // bruit sous le seuil : porte fermée
        val closed = sine(300.0, -60.0, 480).also { dsp.process(it) }
        assertTrue(peak(closed) < 10.0.pow(-60.0 / 20) * 0.05)
        assertTrue(peak(closed) > 0)                                                // atténuée, jamais muette
        val voice = sine(300.0, -20.0, 4800).also { dsp.process(it) }
        assertTrue(peak(voice, 2400) > 0.09)                                        // ouverte par la voix
        val free = sine(300.0, -60.0, 480).also { VoiceDsp(48000).process(it) }
        assertTrue(abs(peak(free) - 10.0.pow(-60.0 / 20)) < 1e-4)                   // réglage par défaut : porte coupée
    }

    @Test
    fun `erreur de calcul - contournement, jamais de silence`() {
        val dsp = VoiceDsp(48000)
        var told = ""
        dsp.onFail = { told = it }
        dsp.apply(VoiceSettings(enabled = true))
        val bad = FloatArray(480) { if (it == 10) Float.NaN else 0.1f }
        dsp.process(bad)
        assertTrue(dsp.failed && "limiteur seul" in told)
        val next = sine(1000.0, -20.0, 960).also { dsp.process(it) }
        assertTrue(peak(next, 480) > 0.09)                                          // la voix passe encore
    }
}
