// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.log10
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Spatialisation : mêmes préréglages et mêmes échantillons que la page (tests/protocol/spatial_presets.json). */
class SpatialTest {
    private val shared: JsonObject =
        Json.parseToJsonElement(File(System.getProperty("trx.repo"), "tests/protocol/spatial_presets.json").readText()).jsonObject
    private val rate = 48000

    private fun on(key: String) = Spatials.choose(SpatialSettings(on = true), key)

    private fun run(s: SpatialSettings, x: DoubleArray, ab: Boolean = false): Pair<DoubleArray, DoubleArray> {
        val sp = Spatial(rate, Spatials.params(s, ab))
        val l = DoubleArray(x.size)
        val r = DoubleArray(x.size)
        for (i in x.indices) { sp.step(x[i]); l[i] = sp.left; r[i] = sp.right }
        return l to r
    }

    @Test
    fun `préréglages et réponses impulsionnelles, ceux de la page`() {
        val presets = shared.getValue("presets").jsonObject
        assertEquals(presets.keys.toList(), Spatials.PRESETS.keys.toList())
        for ((key, p) in Spatials.PRESETS) {
            val o = presets.getValue(key).jsonObject
            assertEquals(o.getValue("label").jsonPrimitive.content, p.label)
            assertEquals(o.getValue("engine").let { if (it is JsonNull) null else it.jsonPrimitive.contentOrNull }, p.engine)
            assertEquals(o.getValue("width").jsonPrimitive.int, p.width)
            assertEquals(o.getValue("presence").jsonPrimitive.int, p.presence)
            val ref = shared.getValue("impulse").jsonObject.getValue(key).jsonObject
            val n = Spatials.LATENCY + 64
            val x = DoubleArray(n).also { it[0] = 0.5 }
            val (l, r) = run(on(key), x)
            for ((side, y) in listOf("left" to l, "right" to r)) {
                ref.getValue(side).jsonArray.forEachIndexed { i, v ->
                    assertTrue(abs(v.jsonPrimitive.double - y[Spatials.LATENCY + i]) < 1e-6, "$key $side $i")
                }
            }
        }
    }

    @Test
    fun `binaural à 90 degrés de 300 à 3000 Hz`() {
        for (f in listOf(300.0, 700.0, 1500.0, 3000.0)) {
            val x = DoubleArray(24000) { 0.3 * sin(2 * PI * f * it / rate) }
            val (l, r) = run(on("cw"), x)
            fun ph(y: DoubleArray): Pair<Double, Double> {
                var c = 0.0; var s = 0.0
                for (i in 9600 until 24000) { c += y[i] * cos(2 * PI * f * i / rate); s += y[i] * sin(2 * PI * f * i / rate) }
                return atan2(c, s) to hypot(c, s)
            }
            val (a, aa) = ph(l)
            val (b, bb) = ph(r)
            var d = abs(a - b) * 180 / PI
            if (d > 180) d = 360 - d
            assertTrue(abs(d - 90) <= 2, "$f Hz : $d°")
            assertTrue(abs(20 * log10(aa / bb)) <= 0.5, "$f Hz")
        }
    }

    @Test
    fun `décorrélation, somme mono égale au signal retardé`() {
        val x = DoubleArray(9600) { 0.2 * sin(it * 0.013) + 0.1 * sin(it * 0.21) }
        val s = on("comfort")
        val (l, r) = run(s, x)
        val we = 0.7 * (1 - 0.4)
        val g = 1 / sqrt(1 + we * we)
        val d = Spatials.LATENCY
        for (i in d until x.size) assertTrue(abs(l[i] + r[i] - 2 * g * x[i - d]) < 1e-9, "échantillon $i")
    }

    @Test
    fun `bypass, limiteur et entrées extrêmes`() {
        val x = DoubleArray(4800) { 0.2 * sin(it * 0.05) }
        val (l, r) = run(on("dx"), x, ab = true)
        val d = Spatials.LATENCY
        for (i in d until x.size) { assertEquals(x[i - d], l[i]); assertEquals(x[i - d], r[i]) }
        val y = DoubleArray(9600) { when { it % 1000 == 3 -> Double.NaN; it % 997 == 0 -> 1e30; else -> 4 * sin(it / 7.0) } }
        for (key in Spatials.PRESETS.keys) {
            val (ll, rr) = run(on(key).copy(width = 150, balance = 30), y)
            for (i in y.indices) {
                assertTrue(ll[i].isFinite() && rr[i].isFinite())
                assertTrue(abs(ll[i]) <= Spatials.CEILING + 1e-12 && abs(rr[i]) <= Spatials.CEILING + 1e-12, "$key $i")
            }
        }
    }

    @Test
    fun `réglages, bornes et libellé modifié`() {
        assertEquals(SpatialSettings(), Spatials.validate(null as JsonObject?))
        val v = Spatials.validate(Json.parseToJsonElement("""{"on":true,"preset":"cw","width":999,"presence":-5,"balance":300,"monoOut":"oui"}""").jsonObject)
        assertEquals(SpatialSettings(on = true, preset = "cw", width = 150, presence = 0, balance = 100, monoOut = false), v)
        assertEquals("comfort", Spatials.validate(Json.parseToJsonElement("""{"preset":"inconnu"}""").jsonObject).preset)
        val s = Spatials.choose(v, "dx")
        assertEquals("DX BLU", Spatials.label(s))
        assertEquals("DX BLU (modifié)", Spatials.label(s.copy(width = 81)))
        assertFalse(Spatials.isModified(Spatials.choose(v, "mono")))
        assertEquals(s, Spatials.validate(Spatials.toJson(s)))
    }
}
