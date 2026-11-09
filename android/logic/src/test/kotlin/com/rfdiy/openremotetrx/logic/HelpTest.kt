// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class HelpTest {
    @Test
    fun `chaque fonction du poste a son aide`() {
        val source = File("src/main/kotlin/com/rfdiy/openremotetrx/logic/Controls.kt").readText()
        val keys = (Regex("""function\("([A-Z]+)"""").findAll(source) + Regex("""ControlChip\("([A-Z]+)"""").findAll(source))
            .map { it.groupValues[1] }.toSet()
        assertTrue(keys.size >= 12, keys.toString())
        assertEquals(emptySet(), keys - Help.CONTROLS.keys)                // une nouvelle fonction doit recevoir son aide
    }

    @Test
    fun `aides courtes et sans texte vide`() {
        for ((key, text) in Help.CONTROLS + Help.CLIENT) {
            assertTrue(text.isNotBlank() && text.length <= 300, key)
        }
    }
}
