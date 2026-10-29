// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ScramblerTest {
    private val rate = 48000
    private val n = 96000
    private val tones = listOf(500.0, 1100.0, 1900.0, 2600.0)

    private fun voice() = FloatArray(n) { i -> tones.sumOf { f -> 0.2 * sin(2 * PI * f * i / rate + f) }.toFloat() }

    /** Énergie aux fréquences d'origine (±25 Hz) / énergie ailleurs dans 300-3 000 Hz (comme le test de la page). */
    private fun toneRatioDb(y: FloatArray): Double {
        val m = 16384
        val re = DoubleArray(m) { y[60000 + it] * (0.5 - 0.5 * kotlin.math.cos(2 * PI * it / m)) }
        val im = DoubleArray(m)
        Scramblers.fft(re, im, false)
        var tone = 0.0; var rest = 0.0
        for (k in 0 until m / 2) {
            val f = k.toDouble() * rate / m
            if (f < 300 || f > 3000) continue
            val p = re[k] * re[k] + im[k] * im[k]
            if (tones.any { abs(f - it) < 25 }) tone += p else rest += p
        }
        return 10 * log10(tone / rest)
    }

    private fun through(mode: String, x: FloatArray, delay: Int = 0, channelHz: Double = 0.0, fixHz: Int = 0): Pair<FloatArray, FloatArray> {
        val a = x.copyOf()
        Scrambler(rate, tx = true).apply { set(mode, 0) }.process(a)
        val ch = FrequencyShifter(rate).apply { hz = channelHz }
        val b = FloatArray(n)
        for (i in 0 until n - delay) b[i + delay] = ch.run(a[i].toDouble()).toFloat()
        val rx = Scrambler(rate, tx = false).apply { set(mode, fixHz) }
        var i = 0
        while (i < n) {                                              // blocs de 480 comme WebRTC
            val k = minOf(480, n - i)
            val block = b.copyOfRange(i, i + k)
            rx.process(block, k)
            System.arraycopy(block, 0, b, i, k)
            i += k
        }
        return a to b
    }

    @Test
    fun `memes correspondances de bins que la page (fichier partage)`() {
        val shared = Json.parseToJsonElement(File(System.getProperty("trx.repo"), "tests/protocol/scrambler_modes.json").readText()).jsonObject
        assertEquals(Scramblers.FRAME, shared["frame"]!!.jsonPrimitive.int)
        val modes = shared["modes"]!!.jsonObject
        assertEquals(modes.keys.toList(), Scramblers.MODES.keys.toList())
        for ((key, m) in modes) {
            assertEquals(m.jsonObject["label"]!!.jsonPrimitive.content, Scramblers.MODES.getValue(key).label)
            for ((dir, tx) in listOf("tx" to true, "rx" to false)) {
                val (dest, conj) = Scramblers.binMap(key, tx, rate)
                val mine = dest.indices.filter { dest[it] >= 0 }.map { listOf(it, dest[it], if (conj[it]) 1 else 0) }
                val page = m.jsonObject[dir]!!.jsonArray.map { p -> p.jsonArray.map { it.jsonPrimitive.int } }
                assertEquals(page, mine, "$key $dir")
            }
        }
    }

    @Test
    fun `brouille puis debrouille - la voix revient quel que soit le decalage temporel`() {
        val x = voice()
        assertTrue(toneRatioDb(x) > 55)
        for (mode in Scramblers.MODES.keys) for (delay in listOf(0, 333, 777)) {
            val (scrambled, back) = through(mode, x, delay)
            assertTrue(toneRatioDb(scrambled) < 0, "$mode brouillé : ${toneRatioDb(scrambled)}")
            assertTrue(toneRatioDb(back) > 30, "$mode décalé de $delay : ${toneRatioDb(back)}")
        }
    }

    @Test
    fun `BLU mal accordee de 40 Hz - retablie par le decalage fin`() {
        val x = voice()
        assertTrue(toneRatioDb(through("inv3", x, channelHz = 40.0).second) < 0)
        assertTrue(toneRatioDb(through("inv3", x, channelHz = 40.0, fixHz = -40).second) > 20)
    }

    @Test
    fun `eteint - transparent, reglages relus jamais actives`() {
        val s = Scrambler(rate, tx = true).apply { set(null, 0) }
        val x = floatArrayOf(0.1f, -0.2f, 0.3f)
        val y = x.copyOf().also { s.process(it) }
        assertTrue(x.contentEquals(y))
        assertEquals(ScramblerSettings(mode = "mix4", offsetHz = 300), Scramblers.validate("mix4", 999))
        assertEquals(ScramblerSettings(), Scramblers.validate("inconnu", null))
        assertFailsWith<IllegalArgumentException> { Scramblers.binMap("inconnu", true, rate) }
    }
}
