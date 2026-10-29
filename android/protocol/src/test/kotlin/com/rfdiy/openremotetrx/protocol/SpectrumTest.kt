// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/** Trames du spectre : mêmes exemples que la station (tests/protocol/spectrum.json, test_protocol_contract.py). */
class SpectrumTest {
    private val examples = Json.parseToJsonElement(
        File(System.getProperty("trx.repo") ?: "../..", "tests/protocol/spectrum.json").readText(Charsets.UTF_8)
    ).jsonObject

    private fun hex(text: String): ByteArray = text.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    @Test
    fun `chaque trame d'exemple est lue comme la station l'a ecrite`() {
        val valid = examples["valid"]!!.jsonArray
        assertTrue(valid.isNotEmpty())
        for (case in valid) {
            val expected = case.jsonObject["frame"]!!.jsonObject
            val frame = SpectrumFrame.parse(hex(case.jsonObject["hex"]!!.jsonPrimitive.content))!!
            assertEquals(expected["mode"]!!.jsonPrimitive.int, frame.mode)
            assertEquals(expected["out_of_range"]!!.jsonPrimitive.boolean, frame.outOfRange)
            assertEquals(expected["seq"]!!.jsonPrimitive.long, frame.seq)
            assertEquals(expected["low_hz"]!!.jsonPrimitive.long, frame.lowHz)
            assertEquals(expected["high_hz"]!!.jsonPrimitive.long, frame.highHz)
            assertEquals(expected["points"]!!.jsonArray.map { it.jsonPrimitive.int }, (0 until frame.size).map { frame.level(it) })
        }
    }

    @Test
    fun `trames illisibles refusees`() {
        for (h in examples["invalid"]!!.jsonArray) assertNull(SpectrumFrame.parse(hex(h.jsonPrimitive.content)), h.toString())
    }

    @Test
    fun `numero de balayage - plus recent, y compris apres le bouclage`() {
        assertTrue(SpectrumFrame.newer(5, null))
        assertTrue(SpectrumFrame.newer(6, 5))
        assertFalse(SpectrumFrame.newer(5, 5))
        assertFalse(SpectrumFrame.newer(4, 5))
        assertTrue(SpectrumFrame.newer(1, 0xFFFFFFFFL))
    }
}
