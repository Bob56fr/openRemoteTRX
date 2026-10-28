// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** QR code d'appairage : mêmes exemples que la station (tests/protocol/pairing.json, tests/test_pairing_qr.py). */
class PairingTest {
    private val examples = Json.parseToJsonElement(
        File(System.getProperty("trx.repo") ?: "../..", "tests/protocol/pairing.json").readText(Charsets.UTF_8)
    ).jsonObject

    @Test
    fun `chaque code valide donne l'appairage attendu, jamais de mot de passe`() {
        val valid = examples["valid"]!!.jsonArray
        assertTrue(valid.size >= 3)
        for (case in valid) {
            val expected = case.jsonObject["pairing"]!!.jsonObject
            val got = PairingCode.parse(case.jsonObject["uri"]!!.jsonPrimitive.content)
            assertEquals(
                Pairing(
                    expected["name"]!!.jsonPrimitive.content, expected["url"]!!.jsonPrimitive.content,
                    expected["user"]!!.jsonPrimitive.content, expected["fingerprint"]!!.jsonPrimitive.content,
                ),
                got,
            )
        }
    }

    @Test
    fun `chaque code invalide est refuse`() {
        for (uri in examples["invalid"]!!.jsonArray) assertNull(PairingCode.parse(uri.jsonPrimitive.content), uri.toString())
    }

    @Test
    fun `empreinte - seuls hexadecimal, deux-points et espaces`() {
        val hex = "ab".repeat(32)
        assertEquals(("AB:".repeat(32)).dropLast(1), Fingerprint.normalize(hex))
        assertNull(Fingerprint.normalize("$hex" + "s"))                 // caractère parasite : refusé, pas ignoré
        assertNull(Fingerprint.normalize(hex.dropLast(2)))
        assertEquals("https://192.168.1.19:8443", StationAddress.normalize("192.168.1.19"))
        assertNull(StationAddress.normalize("http://192.168.1.19:8443"))
    }
}
