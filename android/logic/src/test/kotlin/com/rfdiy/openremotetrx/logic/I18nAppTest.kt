// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Textes de l'application (lot T2 du cahier docs/application-traduction-cahier-des-charges.md) : catalogue
 * `app.<langue>.json` cohérent, toute clé écrite dans le code existe, et CLIQUET : un fichier de `:logic` converti
 * (liste [CONVERTED]) ne contient plus aucune chaîne de texte humain écrite en dur. Une chaîne qui n'est pas un texte
 * montré (mot de la commande vocale, valeur du protocole, motif) porte la marque `// i18n-ok` sur sa ligne.
 */
class I18nAppTest {
    private val sources = File("src/main/kotlin/com/rfdiy/openremotetrx/logic")
    private val resources = File("src/main/resources/i18n")
    private val common = File(System.getProperty("trx.repo"), "trxstation/i18n")

    /** `:core` et `:app` (lot T3) : TOUS leurs fichiers sont convertis, un nouveau fichier l'est d'office. */
    private val otherModules = listOf(
        File("../core/src/main/kotlin/com/rfdiy/openremotetrx/core"),
        File("../app/src/main/kotlin/com/rfdiy/openremotetrx/app"),
    )
    private fun kotlinFiles(dir: File) = dir.listFiles()!!.filter { it.extension == "kt" }.sortedBy { it.name }

    /**
     * Fichiers de `:logic` passés par [Tr] : un nouveau fichier y entre dès qu'il est converti, et n'en sort jamais.
     * Voice.kt (mots de la commande vocale) attend le lot T7.
     */
    private val CONVERTED = listOf(
        "Artwork.kt",
        "AudioWaterfall.kt",
        "Beeps.kt",
        "BigPtt.kt",
        "Breizh.kt",
        "Car.kt",
        "ClusterStatus.kt",
        "Controls.kt",
        "Diffusion.kt",
        "Driving.kt",
        "Favorites.kt",
        "Format.kt",
        "FreeDv.kt",
        "FreeDvActivity.kt",
        "Friends.kt",
        "HeadsetMic.kt",
        "Help.kt",
        "HfScope.kt",
        "HostHealth.kt",
        "Indicators.kt",
        "Link.kt",
        "MediaKeys.kt",
        "MicProfiles.kt",
        "MobileFeatures.kt",
        "Monitoring.kt",
        "NetProbe.kt",
        "NetUi.kt",
        "Power.kt",
        "PresenceUi.kt",
        "ProblemReport.kt",
        "PttView.kt",
        "QrImage.kt",
        "Radio.kt",
        "RigSession.kt",
        "Scrambler.kt",
        "ScreenLayout.kt",
        "Selcall.kt",
        "Spatial.kt",
        "Spots.kt",
        "Swr.kt",
        "SwrUi.kt",
        "Texts.kt",
        "Tr.kt",
        "VoiceDsp.kt",
        "VoiceEq.kt",
    )

    private fun load(file: File): Map<String, String> {
        val obj = Json.parseToJsonElement(file.readText(Charsets.UTF_8)) as JsonObject
        return obj.mapValues { (k, v) ->
            val p = v as? JsonPrimitive
            assertTrue(p != null && p.isString, "${file.name} : $k n'est pas un texte")
            p.content
        }
    }

    private val field = Regex("""\{([a-z_]+)\}""")
    private fun fields(text: String) = field.findAll(text).map { it.groupValues[1] }.toSortedSet()

    @Test
    fun `catalogue app - cles bien formees, aucun texte vide, memes cles et champs dans chaque langue`() {
        val fr = load(File(resources, "app.fr.json"))
        assertTrue(fr.isNotEmpty())
        val key = Regex("^[a-z0-9]+(\\.[a-z0-9_]+)+$")
        for ((k, v) in fr) {
            assertTrue(key.matches(k), "clé mal formée : $k")
            assertTrue(v.isNotBlank(), "texte vide : $k")
            assertTrue(!v.contains(Regex("""\{[^a-z_}]""")), "champ mal formé dans $k : $v")
        }
        val clientKeys = load(File(common, "client.fr.json")).keys + load(File(common, "shared.fr.json")).keys
        assertEquals(emptySet(), fr.keys intersect clientKeys, "clé déjà dans le tronc commun ou les textes partagés")
        for (lang in Tr.LANGS - "fr") {
            val f = File(resources, "app.$lang.json")
            if (!f.exists()) continue                                     // langue pas encore traduite (lots T5, T6)
            val other = load(f)
            assertEquals(fr.keys, other.keys, "app.$lang.json")
            for ((k, v) in fr) assertEquals(fields(v), fields(other.getValue(k)), "champs de $k en $lang")
        }
    }

    @Test
    fun `chaque cle ecrite dans le code existe en francais`() {
        val known = load(File(resources, "app.fr.json")).keys + load(File(common, "client.fr.json")).keys +
            load(File(common, "shared.fr.json")).keys
        val call = Regex("""Tr\.(?:t|find|has|plural)\(\s*"([a-z0-9_.]+)"\s*[,)]""")
        val missing = (listOf(sources) + otherModules).flatMap(::kotlinFiles).flatMap { f ->
            call.findAll(f.readText(Charsets.UTF_8)).map { it.groupValues[1] }
                .filter { k -> k !in known && "${k}_one" !in known }
                .map { "${f.name} : $it" }.toList()
        }
        assertEquals(emptyList(), missing)
    }

    @Test
    fun `langue proposee - catalogues complets, aucun texte humain laisse en francais`() {
        val files = listOf(resources to "app", common to "shared", common to "client")
        val identical = Json.parseToJsonElement(File(common, "identical.json").readText(Charsets.UTF_8)) as JsonObject
        for (lang in Tr.OFFERED - "fr") for ((dir, domain) in files) {
            val allowed = (identical[lang] as? kotlinx.serialization.json.JsonArray)?.map { (it as JsonPrimitive).content }?.toSet() ?: emptySet()
            val fr = load(File(dir, "$domain.fr.json"))
            val other = load(File(dir, "$domain.$lang.json"))
            assertEquals(fr.keys, other.keys, "$domain.$lang.json")
            val same = fr.filter { (k, v) -> other[k] == v && isHuman(v) && v !in allowed }.keys
            assertEquals(emptySet(), same, "$domain.$lang.json : textes laissés en français")
        }
    }

    @Test
    fun `pseudo-langue - champs intacts, texte allonge, station en francais`() {
        val text = "Fréquence {freq} hors bande"
        val p = Tr.pseudo(text)
        assertTrue(p.startsWith("[") && p.endsWith("]") && "{freq}" in p && p.length >= text.length * 14 / 10, p)
        assertTrue("Fréquence" !in p, p)
        try {
            Tr.lang = Tr.PSEUDO
            assertEquals(Tr.PSEUDO, Tr.lang)
            assertEquals("fr", Tr.stationLang)
            assertEquals(Tr.pseudo(Tr.catalog("fr").getValue("refus.out_of_band")), Tr.t("refus.out_of_band"))
            assertEquals("en", Tr.chooseLang(Tr.PSEUDO, emptyList()))                // jamais choisie par la langue du téléphone
        } finally {
            Tr.lang = "fr"
        }
    }

    @Test
    fun `pluriel - regle de la langue`() {
        try {
            Tr.lang = "fr"
            assertEquals("pttview.x_one", Tr.plural("pttview.x", 0))            // clé absente : affichée telle quelle
            assertEquals("pttview.x_other", Tr.plural("pttview.x", 2))
            Tr.lang = "en"
            assertEquals("pttview.x_other", Tr.plural("pttview.x", 0))
            assertEquals("pttview.x_one", Tr.plural("pttview.x", 1))
        } finally {
            Tr.lang = "fr"
        }
    }

    @Test
    fun `cliquet - aucun texte en dur dans un fichier converti`() {
        val found = CONVERTED.flatMap { name ->
            val f = File(sources, name)
            assertTrue(f.exists(), "fichier converti absent : $name")
            humanStrings(f).map { (line, text) -> "$name:$line : \"$text\"" }
        } + otherModules.flatMap(::kotlinFiles).flatMap { f ->
            humanStrings(f).map { (line, text) -> "${f.parentFile.name}/${f.name}:$line : \"$text\"" }
        }
        assertEquals(emptyList(), found, "textes à passer par Tr (ou marque // i18n-ok)")
    }

    companion object {
        private val STRING = Regex(""""((?:[^"\\\n]|\\.)*)"""")
        private val ACCENT = Regex("[àâäçéèêëîïôöùûüÿœÀÂÇÉÈÊËÎÏÔÖÙÛÜŒ«»…’]")
        private val CAPITALIZED = Regex("^[A-ZÀ-Ý][a-zà-ÿ]{2,}$")
        private val WORDS = Regex("[A-Za-zÀ-ÿ]{2,}")
        private val TEMPLATE = Regex("""\$\{[^}]*\}|\$[A-Za-z_]\w*""")

        /** Le texte ressemble-t-il à une phrase ou un libellé pour l'opérateur ? */
        fun isHuman(text: String): Boolean {
            val plain = TEMPLATE.replace(text, " ")
            if (WORDS.findAll(plain).none { it.value.length >= 3 }) return false
            if (ACCENT.containsMatchIn(plain) || CAPITALIZED.matches(plain)) return true
            return WORDS.findAll(plain).count() >= 2 && plain.trim().contains(' ')
        }

        /** Chaînes de texte humain d'un fichier Kotlin (hors commentaires et lignes marquées `// i18n-ok`). */
        fun humanStrings(file: File): List<Pair<Int, String>> =
            file.readLines(Charsets.UTF_8).withIndex().flatMap { (i, line) ->
                val t = line.trim()
                if (t.startsWith("//") || t.startsWith("*") || t.startsWith("/*") || line.contains("// i18n-ok")) {
                    emptyList()
                } else {
                    STRING.findAll(line).map { it.groupValues[1] }.filter(::isHuman).map { i + 1 to it }.toList()
                }
            }
    }
}
