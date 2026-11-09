// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals

class ScreenLayoutTest {
    @Test
    fun `disposition selon la fenetre, pas l'appareil`() {
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(412, 915))      // téléphone en portrait
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(915, 412))      // téléphone en paysage : spectre plein écran (inchangé)
        assertEquals(ScreenLayout.WIDE, ScreenLayouts.of(1280, 800))      // tablette 10 pouces en paysage
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(800, 1280))     // tablette en portrait : étape suivante
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(640, 800))      // fenêtre partagée moyenne : téléphone
        assertEquals(ScreenLayout.WIDE, ScreenLayouts.of(840, 600))       // seuil Material 3 « Expanded »
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(839, 600))
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(900, 900))      // carré : pas un paysage
        assertEquals(ScreenLayout.PHONE, ScreenLayouts.of(932, 430))      // grand téléphone en paysage (S25 Ultra…)
        assertEquals(ScreenLayout.WIDE, ScreenLayouts.of(841, 673))       // pliant ouvert en paysage
    }
}
