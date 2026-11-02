// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** Mesure de TOS : mêmes calculs que la station et la page (tests/protocol/swr_plans.json). */
class SwrTest {
    private val shared: JsonObject =
        Json.parseToJsonElement(File(System.getProperty("trx.repo"), "tests/protocol/swr_plans.json").readText()).jsonObject

    private fun JsonObject.long(key: String) = getValue(key).jsonPrimitive.long

    @Test
    fun `table des bandes, pas lisibles et lignes du graphique, ceux de la station`() {
        val bands = shared.getValue("bands").jsonArray.map { it.jsonObject }
            .map { Swr.TableBand(it.getValue("name").jsonPrimitive.content, it.getValue("kind").jsonPrimitive.content, it.long("low_hz"), it.long("high_hz")) }
        assertEquals(bands, Swr.BANDS)
        assertEquals(shared.getValue("nice_steps_hz").jsonArray.map { it.jsonPrimitive.long }, Swr.NICE_STEPS_HZ)
        assertEquals(shared.getValue("grid").jsonArray.map { it.jsonPrimitive.double }, Swr.GRID)
    }

    @Test
    fun `plans, pas lisible, points ronds, refus`() {
        for (c in shared.getValue("plans").jsonArray.map { it.jsonObject }) {
            val got = Swr.plan(c.long("low_hz"), c.long("high_hz"), c.getValue("points").jsonPrimitive.int, c.getValue("max_points").jsonPrimitive.int)
            val error = (c["error"] as? JsonPrimitive)?.contentOrNull
            if (error != null) {
                assertEquals(error, got.error, c.toString())
            } else {
                val e = c.getValue("expect").jsonObject
                assertNull(got.error, c.toString())
                assertEquals(e.long("step_hz"), got.stepHz, c.toString())
                assertEquals(e.getValue("freqs").jsonArray.map { it.jsonPrimitive.long }, got.freqs, c.toString())
                assertEquals(e.getValue("amateur_only").jsonPrimitive.booleanOrNull, got.amateurOnly, c.toString())
            }
        }
    }

    @Test
    fun `centre, bande du poste, echelle et couleurs`() {
        for (c in shared.getValue("center").jsonArray.map { it.jsonObject }) {
            assertEquals(c.long("low_hz") to c.long("high_hz"), Swr.rangeFromCenter(c.long("center_hz"), c.long("width_hz")))
        }
        for (c in shared.getValue("band_at").jsonArray.map { it.jsonObject }) {
            val b = Swr.bandAt(c.long("hz"))
            assertEquals((c["name"] as? JsonPrimitive)?.contentOrNull, b?.name)
            assertEquals((c["kind"] as? JsonPrimitive)?.contentOrNull, b?.kind)
        }
        for (c in shared.getValue("scale").jsonArray.map { it.jsonObject }) {
            assertEquals(c.getValue("y").jsonPrimitive.double, Swr.scaleY(c.getValue("swr").jsonPrimitive.double), 1e-9)
        }
        for (c in shared.getValue("levels").jsonArray.map { it.jsonObject }) {
            assertEquals(c.getValue("level").jsonPrimitive.content, Swr.level(c.getValue("swr").jsonPrimitive.double))
        }
        assertNull(Swr.rangeFromCenter(7_100_000, 0))
    }
}
