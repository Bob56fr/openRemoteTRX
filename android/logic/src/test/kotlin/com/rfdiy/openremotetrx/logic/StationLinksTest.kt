// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Étape 392 : lien vers la console, mises à jour sous « Connecter », fonctions absentes de la station. */
class StationLinksTest {
    @Test
    fun `console a la meme adresse que la station, port de hello, toujours en HTTPS`() {
        assertEquals("https://192.168.1.19:8444/", StationLinks.consoleUrl("https://192.168.1.19:8443", 8444))
        assertEquals("https://station.example:8444/", StationLinks.consoleUrl("https://station.example:8443/", 8444))
        assertEquals("https://[fd00::5]:8444/", StationLinks.consoleUrl("https://[fd00::5]:8443", 8444))
        assertNull(StationLinks.consoleUrl("https://192.168.1.19:8443", null))     // pas administrateur
        assertNull(StationLinks.consoleUrl("https://192.168.1.19:8443", 80))       // port refusé
        assertNull(StationLinks.consoleUrl("pas une adresse", 8444))
    }

    @Test
    fun `nouvelle application seulement si plus recente et hors Google Play, station toujours`() {
        val seen = SeenUpdates("minix", 0L, stationVersion = "0.283.0", stationUrl = "https://x/s",
                               appVersion = "0.91.0", appCode = 98, appUrl = "https://x/a")
        val both = Updates.lines(seen, myCode = 97, storeBuild = false)
        assertEquals(listOf("https://x/a", "https://x/s"), both.map { it.url })
        assertTrue(both[0].text.contains("0.91.0") && both[1].text.contains("7.1") && both[1].text.contains("minix"))
        assertEquals(listOf("https://x/s"), Updates.lines(seen, myCode = 98, storeBuild = false).map { it.url })   // à jour
        assertEquals(listOf("https://x/s"), Updates.lines(seen, myCode = 97, storeBuild = true).map { it.url })    // Google Play
        assertEquals(emptyList(), Updates.lines(seen.copy(stationVersion = ""), 98, false))
        assertEquals(emptyList(), Updates.lines(null, 1, false))
    }

    @Test
    fun `interrupteur bloque si la station connectee n offre pas la fonction`() {
        val withoutSelcall: (String) -> Boolean = { it != "selcall" }
        assertTrue(MobileFeatures.unavailable(MobileFeature.SELCALL, withoutSelcall)!!.contains("5.5"))
        assertNull(MobileFeatures.unavailable(MobileFeature.SELCALL) { true })
        assertNull(MobileFeatures.unavailable(MobileFeature.SELCALL, null))          // aucune station connectée
        assertNull(MobileFeatures.unavailable(MobileFeature.EQ) { false })           // fonction de l'application seule
        assertTrue(MobileFeatures.unavailable(MobileFeature.WATERFALL) { false }!!.contains("2.7"))
        for (f in MobileFeature.entries) MobileFeatures.stationFeature(f)?.let { assertTrue(it.isNotEmpty()) }
    }
}
