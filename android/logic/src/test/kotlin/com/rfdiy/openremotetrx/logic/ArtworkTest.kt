// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ArtworkTest {
    @Test
    fun `logo sans liaison, image de la bande, hors bande sinon`() {
        assertEquals("logo", Artwork.key(connected = false, hz = 7_100_000))
        assertEquals("logo", Artwork.key(connected = true, hz = null))
        assertEquals("40m", Artwork.key(true, 7_100_000))
        assertEquals("11m", Artwork.key(true, 27_555_000))
        assertEquals("2m", Artwork.key(true, 145_500_000))
        assertEquals("70cm", Artwork.key(true, 433_500_000))
        assertEquals("hors_bande", Artwork.key(true, 9_000_000))
        assertEquals("40m", Artwork.bandKey("40"))
    }

    @Test
    fun `liste blanche - aucun chemin libre`() {
        assertFalse(Artwork.isKey("../station"))
        assertFalse(Artwork.isKey("40m.png"))
        assertTrue(Artwork.isKey("hors_bande"))
        assertTrue(Radio.BANDS.all { Artwork.isKey(Artwork.bandKey(it.key)) })
    }

    @Test
    fun `chaque cle a son image fournie (scripts build_car_art)`() {
        val dir = File(System.getProperty("trx.repo"), "android/core/src/main/assets/pochettes")
        val missing = Artwork.KEYS.filterNot { File(dir, "$it.jpg").isFile }
        assertTrue(missing.isEmpty(), "pochettes manquantes : $missing (python scripts/build_car_art.py)")
    }
}
