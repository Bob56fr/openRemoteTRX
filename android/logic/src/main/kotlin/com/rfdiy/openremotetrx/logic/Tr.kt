// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

/**
 * Textes de l'application dans la langue de l'opérateur (cahier docs/application-traduction-cahier-des-charges.md).
 *
 * Catalogues : ressources `/i18n/<domaine>.<langue>.json`, objets {clé: texte} avec des champs `{nom}`. Le domaine
 * « client » est le TRONC COMMUN copié à la compilation depuis `trxstation/i18n/` (mêmes textes que la station et la
 * page web : refus, coupures) ; le domaine « shared » (copié de même, lot T4) les autres textes communs à la page
 * et à l'application (même clé des deux côtés) ; le domaine « app » (`logic/src/main/resources/i18n/app.<langue>.json`, lot T2) porte
 * les textes propres à l'application, clés `<fichier>.<nom>` (`rigsession.connecting`). Le français est la référence : une clé absente d'une langue retombe sur le français,
 * une clé absente partout s'affiche telle quelle (jamais d'exception : l'écran doit toujours s'afficher).
 */
object Tr {
    val LANGS = listOf("fr", "en", "de", "es")

    /**
     * Langues PROPOSÉES par l'application : une langue n'y entre que lorsque ses catalogues sont complets (lot T5 :
     * anglais ; allemand et espagnol au lot T6) — I18nAppTest le vérifie.
     */
    val OFFERED = listOf("fr", "en", "de", "es")

    private val DOMAINS = listOf("client", "shared", "app")
    private val json = Json { ignoreUnknownKeys = true }
    private val cache = ConcurrentHashMap<String, Map<String, String>>()
    private val FIELD = Regex("""\{([a-z_]+)\}""")

    /**
     * Pseudo-langue d'essai (cahier § 7, lot T6) : le français aux lettres accentuées, allongé de 40 % et entre
     * crochets, pour voir les textes qui débordent ou qui ne passent pas par [Tr]. Jamais proposée hors débogage.
     */
    const val PSEUDO = "xx"

    /** Langue en cours ; une langue inconnue devient le français. */
    @Volatile
    var lang: String = "fr"
        set(value) { field = if (value in LANGS || value == PSEUDO) value else "fr" }

    /** Langue annoncée à la station (la pseudo-langue y est du français). */
    val stationLang: String get() = if (lang == PSEUDO) "fr" else lang

    /**
     * Locale de la langue CHOISIE (formats de date du cahier § 3.5 : fr-FR, en-GB, de-DE, es-ES ; pseudo-langue =
     * français), jamais celle du téléphone. Les nombres décimaux passent par [Format.decimal].
     */
    val locale: Locale get() = when (lang) {
        "en" -> Locale.UK
        "de" -> Locale.GERMANY
        "es" -> Locale.forLanguageTag("es-ES")
        else -> Locale.FRANCE
    }

    private const val PLAIN = "AaCcEeIiNnOoUuYy"
    private const val ACCENTED = "ÅåÇçÉéÎîÑñÖöÛûÝý"   // i18n-ok : lettres de la pseudo-langue

    /** Texte de la pseudo-langue : champs `{nom}` intacts, lettres accentuées, 40 % plus long. */
    fun pseudo(text: String): String {
        val parts = FIELD.split(text)
        val names = FIELD.findAll(text).map { it.value }.toList()
        val body = buildString {
            parts.forEachIndexed { i, part ->
                append(part.map { c -> PLAIN.indexOf(c).let { if (it < 0) c else ACCENTED[it] } }.joinToString(""))
                if (i < names.size) append(names[i])
            }
        }
        val pad = (text.length * 2 + 4) / 5
        return "[" + body + "·".repeat(pad) + "]"
    }

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
        if (lang == PSEUDO) return@getOrPut catalog("fr").mapValues { pseudo(it.value) }
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
        val one = if (lang == "fr" || lang == PSEUDO) n in -1L..1L else n == 1L || n == -1L
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
