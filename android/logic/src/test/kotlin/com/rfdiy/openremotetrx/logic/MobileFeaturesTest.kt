// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** « Fonctionnalités mobiles » : défauts demandés par l'utilisateur, fonction en service jamais masquée. */
class MobileFeaturesTest {
    @Test
    fun `masques par defaut roger bip, EQ, SELCALL, chorus et reverberation, les autres visibles`() {
        val hidden = MobileFeature.entries.filter { !MobileFeatures.shown(it, null) }.toSet()
        assertEquals(setOf(MobileFeature.ROGER, MobileFeature.EQ, MobileFeature.SELCALL, MobileFeature.CHORUS_REVERB), hidden)
    }

    @Test
    fun `une fonction en service reste affichee meme masquee`() {
        assertFalse(MobileFeatures.shown(MobileFeature.EQ, false))
        assertTrue(MobileFeatures.shown(MobileFeature.EQ, false, inService = true))
        assertTrue(MobileFeatures.shown(MobileFeature.ROGER, true))
        assertFalse(MobileFeatures.shown(MobileFeature.WATERFALL, false))
    }

    @Test
    fun `rien de securite ni le micro dans la liste, cles uniques`() {
        val keys = MobileFeature.entries.map { it.key }
        assertEquals(keys.size, keys.toSet().size)
        for (k in listOf("ptt", "stop", "armed", "tot", "mic", "micro")) assertFalse(k in keys, k)
    }
}
