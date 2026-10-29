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

class RecentSpotsTest {
    @Test
    fun `tout afficher - les 30 derniers par ordre d'arrivee, source lisible`() {
        val spots = (0 until 40).map { i ->
            Spots.clean(Json.parseToJsonElement("""{"id":$i,"f":14074,"dx":"CALL$i","de":"F5LEN","age":${40 - i}}"""), 100_000)!!
        }
        val recent = Spots.recent(spots.shuffled())
        assertEquals(30, recent.size)
        assertEquals("CALL39", recent.first().dx)                     // âge 1 s : arrivé le dernier
        assertEquals("CALL10", recent.last().dx)
        assertEquals(99_000L, Spots.arrivalMs(recent.first()))
        assertEquals("DX de F5LEN", Spots.sourceLabel(recent.first()))
        val msg = Json.parseToJsonElement("""{"kind":"recent","spots":[{"id":1,"f":7074,"dx":"A1","age":50},{"id":2,"f":27555,"dx":"B2","age":5}]}""")
        assertEquals(listOf("B2", "A1"), Spots.recentOf(msg, 0)!!.map { it.dx })
        assertNull(Spots.recentOf(Json.parseToJsonElement("""{"kind":"spots","spots":[]}"""), 0))
    }
}

class MediaKeysTest {
    private fun d(key: MediaKey, mine: Boolean = false, repeat: Int = 0, device: Long? = null, last: Long? = null) =
        MediaKeys.decide(key, repeat, mine, device, last)

    @Test
    fun `bouton du casque - prise puis fin, appui simple seulement`() {
        assertEquals(MediaAction.TOGGLE, d(MediaKey.TOGGLE))
        assertEquals(MediaAction.TOGGLE, d(MediaKey.TOGGLE, mine = true))
        assertEquals(MediaAction.IGNORE, d(MediaKey.TOGGLE, repeat = 1))          // maintien : jamais
        assertEquals(MediaAction.IGNORE, d(MediaKey.OTHER))
        assertEquals(MediaAction.IGNORE, d(MediaKey.TOGGLE, last = 200))           // rebond
    }

    @Test
    fun `touche automatique a la connexion d'un casque ou d'une voiture - jamais de prise`() {
        assertEquals(MediaAction.IGNORE, d(MediaKey.PLAY, device = 500))
        assertEquals(MediaAction.IGNORE, d(MediaKey.PAUSE, device = 500))
        assertEquals(MediaAction.IGNORE, d(MediaKey.TOGGLE, device = 2999))
        assertEquals(MediaAction.TOGGLE, d(MediaKey.PLAY, device = 3000))
        assertEquals(MediaAction.TOGGLE, d(MediaKey.PAUSE, mine = true, device = 10))   // terminer reste toujours permis
        assertEquals("appareil audio arrivé à l'instant (touche automatique ?)", MediaKeys.ignoredWhy(MediaKey.PLAY, 0, false, 500, null))
    }

    @Test
    fun `lecture et pause = meme appui PTT (le casque choisit l'une ou l'autre), stop ne prend jamais`() {
        assertEquals(MediaAction.TOGGLE, d(MediaKey.PAUSE))                           // essai du 2026-10-29
        assertEquals(MediaAction.TOGGLE, d(MediaKey.PLAY, mine = true))              // « lecture » pendant l'émission : fin
        assertEquals(MediaAction.IGNORE, d(MediaKey.STOP))
        assertEquals(MediaAction.TOGGLE, d(MediaKey.STOP, mine = true))
        assertEquals("rebond", MediaKeys.ignoredWhy(MediaKey.TOGGLE, 0, true, null, 100))
    }
}

class BeepSettingsTest {
    @Test
    fun `reglages des bips lus comme la page`() {
        val b = BeepSettings.parse(Json.parseToJsonElement("""{"roger_enabled":true,"roger_tone":"duo","roger_pattern":2,
            "link_lost_enabled":false,"roger_sequence":[[1000,100],[0,60],[1000,100]],"link_lost_sequence":[[1200,120],["x",1]],
            "tones":["600","duo"],"patterns":[1,2,3]}""") as kotlinx.serialization.json.JsonObject)!!
        assertTrue(b.rogerEnabled)
        assertEquals(false, b.linkLostEnabled)
        assertEquals(listOf(1000 to 100, 0 to 60, 1000 to 100), b.rogerSequence)
        assertEquals(listOf(1200 to 120), b.linkLostSequence)           // segment illisible écarté
        assertEquals("deux tons montants", BeepSettings.toneLabel(b.tone))
        assertEquals("2 bips", BeepSettings.patternLabel(2))
        assertNull(BeepSettings.parse(null))
    }
}

class MicProfilesTest {
    @Test
    fun `profils du micro comme la page - casque a reduction de bruit = aucun traitement, defaut = piece calme`() {
        assertEquals(listOf("quiet", "noisy", "headset_nr", "headset", "custom"), MicProfiles.ALL.map { it.key })
        assertEquals(MicProcessing(echo = false, noise = false), MicProfiles.processing("headset_nr"))
        assertEquals(MicProcessing(echo = true, noise = true), MicProfiles.processing("noisy"))
        assertEquals(MicProcessing(echo = true, noise = false), MicProfiles.processing("inconnu"))
        assertEquals(MicProcessing(echo = false, noise = true), MicProfiles.processing("custom", customEcho = false, customNoise = true))
        // Même table que la page (client.js, MIC_PROFILES)
        val js = java.io.File("../../trxstation/gateway/api/static/client.js").readText()
        for (p in MicProfiles.ALL) {
            val pr = p.processing
            val expected = if (pr == null) "${p.key}: { label: \"${p.label}\", echo: null, noise: null }"
                else "${p.key}: { label: \"${p.label}\", echo: ${pr.echo}, noise: ${pr.noise} }"
            assertTrue(expected in js, expected)
        }
    }
}

class SelcallTest {
    private val vectors = Json.parseToJsonElement(
        java.io.File(System.getProperty("trx.repo"), "tests/protocol/selcall_vectors.json").readText()
    ) as kotlinx.serialization.json.JsonObject

    @Test
    fun `memes symboles et memes tons que la station (vecteurs partages)`() {
        val cases = vectors["cases"] as kotlinx.serialization.json.JsonArray
        for (c in cases) {
            val o = c as kotlinx.serialization.json.JsonObject
            val code = (o["code"] as kotlinx.serialization.json.JsonPrimitive).content
            val symbols = (o["symbols"] as kotlinx.serialization.json.JsonArray).map { (it as kotlinx.serialization.json.JsonPrimitive).content }
            assertEquals(symbols, SelcallTones.symbols(code), code)
            val tones = (o["tones"] as kotlinx.serialization.json.JsonArray).map { t ->
                val pair = t as kotlinx.serialization.json.JsonArray
                (pair[0] as kotlinx.serialization.json.JsonPrimitive).content.toDouble() to (pair[1] as kotlinx.serialization.json.JsonPrimitive).content.toDouble()
            }
            assertEquals(tones, SelcallTones.tones(code), code)
        }
        for (bad in vectors["invalid"] as kotlinx.serialization.json.JsonArray) {
            assertEquals(false, SelcallTones.validCode((bad as kotlinx.serialization.json.JsonPrimitive).content))
        }
    }

    @Test
    fun `fichier de test - silence, trois trames, WAV valide, niveau -6 dBFS`() {
        val rate = 48_000
        val s = SelcallTones.testSamples("4721", rate)
        assertEquals(2 * rate + 3 * (2.5 * rate).toInt() + 2 * rate / 2 + rate / 2, s.size)
        assertTrue(s.take(2 * rate).all { it == 0f })
        assertTrue(s.maxOf { kotlin.math.abs(it) } <= 0.5013f)
        val wav = SelcallTones.testWav("4721")
        assertEquals("RIFF", String(wav.copyOfRange(0, 4), Charsets.US_ASCII))
        assertEquals(44 + 2 * s.size, wav.size)
    }

    @Test
    fun `etat lu de la station, indicateur, etat refuse s'il est inconnu`() {
        val st = SelcallStatus.parse(Json.parseToJsonElement("""{"state":"open","code":"4721","history":["4721","12","1234"],
            "filter_mode":"chime","attenuation_db":99,"last_call":{"code":"4721","delta_hz":-42.5,"snr_db":11.3,"at":1.0}}""")
            as kotlinx.serialization.json.JsonObject)!!
        assertEquals("SEL OUVERT", st.indicator)
        assertEquals(listOf("4721", "1234"), st.history)
        assertEquals(60, st.attenuationDb)
        assertEquals(-42.5, st.lastCall!!.deltaHz)
        assertNull(SelcallStatus.parse(Json.parseToJsonElement("""{"state":"bizarre"}""") as kotlinx.serialization.json.JsonObject))
        assertEquals("SEL 4721", st.copy(state = "standby").indicator)
        assertNull(st.copy(state = "disabled").indicator)
    }
}

class AlcOverloadTest {
    @Test
    fun `voyant OVERLOAD ALC au meme seuil que la page`() {
        val js = java.io.File(System.getProperty("trx.repo"), "trxstation/gateway/api/static/client.js").readText()
        assertTrue("const ALC_OVERLOAD = ${Indicators.ALC_OVERLOAD};" in js)
        val station = java.io.File(System.getProperty("trx.repo"), "trxstation/selcall/calibrate.py").readText()
        assertTrue("ALC_OVERLOAD = ${Indicators.ALC_OVERLOAD} " in station)
    }
}
