// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.Memory
import com.rfdiy.openremotetrx.protocol.ServerMessages
import com.rfdiy.openremotetrx.protocol.State
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** F1 (favoris au volant) et F3 (réglages du poste en sous-titre). */
class FavoritesTest {
    private val a = Memory("a", "Réseau 40", 7_100_000, "LSB", favorite = true)
    private val b = Memory("b", "QSO 20", 14_195_000, "USB", favorite = true)
    private val c = Memory("c", "Relais", 145_600_000, "FM", favorite = true)
    private val plain = Memory("p", "Pas favori", 10_000_000, "USB")
    private val all = listOf(c, plain, a, b)

    @Test
    fun `seules les favorites, par frequence`() {
        assertEquals(listOf(a, b, c), Favorites.list(all))
    }

    @Test
    fun `suivant et precedent en boucle depuis un favori`() {
        val f = Favorites.list(all)
        assertEquals(b, Favorites.step(f, a, a.hz, forward = true))
        assertEquals(a, Favorites.step(f, c, c.hz, forward = true))        // fin de liste -> premier
        assertEquals(c, Favorites.step(f, a, a.hz, forward = false))       // début -> dernier
    }

    @Test
    fun `hors favori - premier au-dessus ou en dessous de la frequence, en boucle`() {
        val f = Favorites.list(all)
        assertEquals(b, Favorites.step(f, null, 10_000_000, forward = true))
        assertEquals(a, Favorites.step(f, null, 10_000_000, forward = false))
        assertEquals(a, Favorites.step(f, null, 430_000_000, forward = true))   // au-dessus de tout -> premier
        assertEquals(c, Favorites.step(f, null, 1_900_000, forward = false))    // en dessous de tout -> dernier
        assertNull(Favorites.step(emptyList(), null, 7_000_000, true))
    }

    @Test
    fun `appuis regroupes - seul le dernier part apres 300 ms`() {
        val st = FavoriteStepper(300)
        assertEquals(b, st.press(0, true, all, a, a.hz))
        assertEquals(c, st.press(100, true, all, a, a.hz))                  // repart du favori en attente, pas du poste
        assertNull(st.take(399))                                            // 300 ms après le DERNIER appui
        assertEquals(1L, st.remainingMs(399))
        assertEquals(c, st.take(400))
        assertNull(st.take(1000))                                           // envoyé une seule fois
        st.press(0, false, all, a, a.hz)
        st.cancel()
        assertNull(st.take(1000))
        assertNull(FavoriteStepper().press(0, true, listOf(plain), null, 7_000_000))
    }

    @Test
    fun `boutons Suivant Precedent - seulement avec des favoris`() {
        val state = ServerMessages.decode("""{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true,"frequency_hz":7100000,"mode":"LSB"}}""") as State
        val withFav = RigState(status = LinkStatus.CONNECTED, state = state, memories = all)
        assertTrue(Car.screen(withFav, "M", false, true).canSkip)
        assertFalse(Car.screen(withFav.copy(memories = listOf(plain)), "M", false, true).canSkip)
        assertFalse(Car.screen(withFav.copy(listener = true), "M", false, true).canSkip)
        assertEquals("Réseau 40", Car.screen(withFav, "M", false, true, preview = null).title)
        assertEquals("QSO 20", Car.screen(withFav, "M", false, true, preview = b).title)   // choisi au volant, pas encore envoyé
    }

    private fun state(levels: String, functions: String) = ServerMessages.decode(
        """{"type":"state","ptt":{"state":"RX"},"rig":{"connected":true,"frequency_hz":14195000,"mode":"USB","levels":{$levels},"functions":{$functions}}}""",
    ) as State

    private fun hello(maxW: Int, preamps: String = "[10,20]") = ServerMessages.decode(
        """{"type":"hello","protocol":1,"client_id":"x","version":"0","max_power_w":$maxW,"capabilities":{"preamps":$preamps}}""",
    ) as Hello

    @Test
    fun `sous-titre - reglages actifs seulement, ordre fixe, puissance au watt`() {
        val s = state(""""PREAMP":10,"ATT":0,"RFPOWER":0.5""", """"NB":true,"NR":true""")
        assertEquals("P.AMP1 · NB · NR · 50 W · EQ", Car.settings(hello(100), s, eq = true))
        assertEquals("P.AMP1 · NB · NR · 50 W", Car.settings(hello(100), s, eq = false))
        assertEquals("ATT · NR · 47 W", Car.settings(hello(100), state(""""PREAMP":10,"ATT":12,"RFPOWER":0.474""", """"NB":false,"NR":true"""), false))
        assertEquals("50 %", Car.settings(hello(0), state(""""RFPOWER":0.5""", ""), false))   // puissance maxi inconnue
        assertEquals("", Car.settings(hello(100), state("", ""), false))                       // rien de publié : rien
        assertEquals("EQ", Car.settings(null, null, true))
    }

    @Test
    fun `sous-titre - 40 caracteres au plus`() {
        val s = state(""""PREAMP":20,"RFPOWER":1.0""", """"NB":true,"NR":true""")
        val text = Car.settings(hello(100000), s, eq = true)
        assertTrue(text.length <= Car.SETTINGS_MAX, text)
    }
}
