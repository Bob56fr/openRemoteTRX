// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.concurrent.ConcurrentHashMap

/**
 * Textes de l'application dans la langue de l'opérateur (cahier docs/application-traduction-cahier-des-charges.md).
 *
 * Catalogues : ressources `/i18n/<domaine>.<langue>.json`, objets {clé: texte} avec des champs `{nom}`. Le domaine
 * « client » est le TRONC COMMUN copié à la compilation depuis `trxstation/i18n/` (mêmes textes que la station et la
 * page web : refus, coupures) ; le domaine « app » (`logic/src/main/resources/i18n/app.<langue>.json`, lot T2) porte
 * les textes propres à l'application, clés `<fichier>.<nom>` (`rigsession.connecting`). Le français est la référence : une clé absente d'une langue retombe sur le français,
 * une clé absente partout s'affiche telle quelle (jamais d'exception : l'écran doit toujours s'afficher).
 */
object Tr {
    val LANGS = listOf("fr", "en", "de", "es")

    /**
     * Langues PROPOSÉES par l'application : elle n'est traduite qu'au lot T5 ; d'ici là elle reste en français (refus
     * et coupures déjà traduits, mais pas mélangés à des écrans français).
     */
    val OFFERED = listOf("fr")

    private val DOMAINS = listOf("client", "app")
    private val json = Json { ignoreUnknownKeys = true }
    private val cache = ConcurrentHashMap<String, Map<String, String>>()
    private val FIELD = Regex("""\{([a-z_]+)\}""")

    /** Langue en cours ; une langue inconnue devient le français. */
    @Volatile
    var lang: String = "fr"
        set(value) { field = if (value in LANGS) value else "fr" }

    /**
     * Langue retenue : celle choisie dans l'application, sinon la première du téléphone proposée, sinon l'anglais
     * (décision de l'utilisateur du 2026-11-20), sinon le français.
     */
    fun chooseLang(stored: String?, wanted: List<String>, offered: List<String> = OFFERED): String {
        if (stored != null && stored in offered) return stored
        for (raw in wanted) {
            val l = raw.lowercase().split('-', '_').first()
            if (l in offered) return l
        }
        return if ("en" in offered) "en" else "fr"
    }

    /** Tous les textes d'une langue (tous domaines) ; vide si la langue manque. */
    fun catalog(lang: String): Map<String, String> = cache.getOrPut(lang) {
        DOMAINS.flatMap { domain -> read("/i18n/$domain.$lang.json").entries }.associate { it.key to it.value }
    }

    private fun read(path: String): Map<String, String> = try {
        val text = Tr::class.java.getResourceAsStream(path)?.use { it.readBytes().toString(Charsets.UTF_8) }
        val obj = text?.let { json.parseToJsonElement(it) } as? JsonObject
        obj?.mapNotNull { (k, v) -> (v as? JsonPrimitive)?.takeIf { it.isString }?.let { k to it.content } }?.toMap().orEmpty()
    } catch (e: Exception) {
        emptyMap()
    }

    /** Texte d'une clé dans la langue en cours, sinon en français, sinon null. */
    fun find(key: String, vararg fields: Pair<String, Any?>): String? =
        (catalog(lang)[key] ?: catalog("fr")[key])?.let { fill(it, fields) }

    /** Texte d'une clé (la clé elle-même si elle n'existe nulle part). */
    fun t(key: String, vararg fields: Pair<String, Any?>): String = find(key, *fields) ?: key

    /**
     * Texte qui dépend d'un nombre : clé `<clé>_one` ou `<clé>_other` selon la règle de la langue (français : 0 et 1
     * au singulier ; anglais, allemand, espagnol : 1 seul), champ `{n}` rempli d'office.
     */
    fun plural(key: String, n: Long, vararg fields: Pair<String, Any?>): String {
        val one = if (lang == "fr") n in -1L..1L else n == 1L || n == -1L
        return t(if (one) "${key}_one" else "${key}_other", "n" to n, *fields)
    }

    fun plural(key: String, n: Int, vararg fields: Pair<String, Any?>): String = plural(key, n.toLong(), *fields)

    fun has(key: String): Boolean = find(key) != null

    /** Codes d'une section (« refus » -> out_of_band, tx_active…), hors clés techniques « _… ». */
    fun section(prefix: String): Map<String, String> = (catalog("fr").keys + catalog(lang).keys)
        .filter { it.startsWith("$prefix.") && !it.startsWith("$prefix._") }
        .associate { it.removePrefix("$prefix.") to t(it) }

    private fun fill(text: String, fields: Array<out Pair<String, Any?>>): String {
        if (fields.isEmpty()) return text
        val values = fields.toMap()
        return FIELD.replace(text) { m -> values[m.groupValues[1]]?.toString() ?: m.value }
    }
}
