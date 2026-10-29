// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json

class SpotsTest {
    private fun json(text: String) = Json.parseToJsonElement(text)

    @Test
    fun `spots nettoyes comme la page, instantane puis changements`() {
        val book = SpotBook()
        assertTrue(book.apply(json("""{"kind":"spots","op":"snapshot","spots":[
            {"id":1,"f":14074.0,"dx":"EA8XYZ","m":"FT8","k":"cluster","age":30},
            {"id":2,"f":14205.5,"dx":"K1‮ABC","k":"bizarre","n":3},
            {"id":3,"f":-1,"dx":"X"},{"id":"4","f":7000,"dx":"Y"},{"id":5,"f":7000,"dx":""}]}"""), 1000))
        assertEquals(listOf(1L, 2L), book.all().map { it.id })
        val k1 = book.get(2)!!
        assertEquals("K1ABC", k1.dx)                                    // caractère de contrôle bidirectionnel retiré
        assertEquals("cluster", k1.kind)
        assertEquals(14_205_500, k1.hz)
        assertTrue(book.apply(json("""{"kind":"spots","op":"delta","spots":[{"id":6,"f":21074,"dx":"JA1AA"}],"removed":[1]}"""), 2000))
        assertEquals(listOf(2L, 6L), book.all().map { it.id })
        assertEquals(listOf(2L), book.visible(14_000_000, 14_350_000).map { it.id })
        assertEquals(false, book.apply(json("""{"kind":"cluster_status","health":"green"}"""), 0))
    }

    @Test
    fun `age, estompage et libelles`() {
        val spot = Spots.clean(json("""{"id":1,"f":7074,"dx":"F4ABC","m":"SSB","mg":true,"age":100}"""), 0)!!
        assertEquals(130.0, Spots.ageSeconds(spot, 30_000), 0.001)
        assertEquals(1f, Spots.opacity(60.0))
        assertEquals(0.35f, Spots.opacity(5000.0))
        assertEquals("il y a 2 min", Spots.ageLabel(130.0))
        assertEquals("BLU (supposé)", Spots.modeLabel(spot))
        assertEquals("DX", Spots.kindLabel("cluster"))
    }

    @Test
    fun `etiquettes - rangees puis regroupement en +N`() {
        val spots = (0 until 8).map { i ->
            Spots.clean(json("""{"id":$i,"f":${14074 + i * 0.1},"dx":"CALL$i"}"""), 0)!!
        }
        val labels = Spots.layoutLabels(spots, 14_070_000, 14_080_000, 400f)
        assertEquals(3, labels.count { !it.group })                    // trois rangées
        val group = labels.single { it.group }
        assertEquals("+5", group.text)
        assertEquals(5, group.ids.size)
        assertEquals(3, group.row)
        assertTrue(Spots.layoutLabels(spots, 1, 1, 400f).isEmpty())
    }

    @Test
    fun `squelch ouvert et bandes preferees`() {
        assertTrue(Radio.squelchOpen(0.0, null))                       // squelch à 0 : toujours ouvert
        assertEquals(false, Radio.squelchOpen(0.5, -54.0))              // S0 sous le seuil
        assertTrue(Radio.squelchOpen(0.2, 0.0))                          // S9 au-dessus d'un seuil bas
        assertEquals(false, Radio.squelchOpen(null, 0.0))
        assertNull(Radio.squelchMarkerFraction(0.0))
        assertEquals(listOf("11", "20", "40"), Radio.favoriteBands("11, 20,40,20,99").map { it.key })
        assertEquals(Radio.BANDS, Radio.favoriteBands(""))
        assertEquals("11,20", Radio.favoriteBandsText(Radio.favoriteBands("11,20")))
    }
}

class ClusterStatusTest {
    private val data = kotlinx.serialization.json.Json.parseToJsonElement("""{"kind":"cluster_status","health":"orange",
        "sources":[{"name":"F5LEN","type":"telnet","verdict":"ok","last_10min":42,"last_spot_age_s":20},
                   {"name":"RBN","type":"rbn","verdict":"attente","retry_in_s":30},
                   {"name":"CB","type":"web","verdict":"echec","code":"http_403"}],
        "bands":{"20m":17,"40m":6,"11m":2,"2m":9}}""") as kotlinx.serialization.json.JsonObject

    @Test
    fun `etat des flux comme la page`() {
        val v = ClusterStatus.view(data, 10.0)
        assertEquals("Une partie des flux seulement", v.title)
        assertEquals(listOf("green", "orange", "red"), v.lines.map { it.dot })
        assertEquals("F5LEN (cluster) : reçoit · 4 spots/min · dernier il y a 30 s", v.lines[0].text)
        assertEquals("RBN (RBN) : connexion en cours · nouvel essai dans 30 s", v.lines[1].text)
        assertTrue(v.lines[2].text.endsWith("http_403 : voir TRX Console, menu 12"))
        assertEquals(false, v.stale)
        assertTrue(ClusterStatus.view(data, 60.0).stale)
    }

    @Test
    fun `pastilles des bandes - gris, orange, rouge, bandes inconnues ignorees`() {
        assertEquals(mapOf("20" to BandDot(17, 3), "40" to BandDot(6, 2), "11" to BandDot(2, 1)), ClusterStatus.bandDots(data))
    }
}
