// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Parité des textes entre la page web et l'application (lot T4 du cahier docs/application-traduction-cahier-des-charges.md) :
 * un texte commun n'est plus recopié des deux côtés, il vit sous UNE clé du catalogue partagé
 * (`trxstation/i18n/shared.<langue>.json`) que la page (`I18N.t("clé")`) et l'application (`Tr.t("clé")`) lisent toutes les deux.
 */
object PageI18n {
    val repo = File(System.getProperty("trx.repo") ?: "../..")
    private val pageLiteral = Regex(""""([a-z0-9]+\.[a-z0-9_.]*)"""")
    private val appLiteral = Regex(""""([a-z0-9]+\.[a-z0-9_.]*[a-z0-9])"""")

    val shared: Set<String> by lazy {
        Json.parseToJsonElement(File(repo, "trxstation/i18n/shared.fr.json").readText(Charsets.UTF_8)).jsonObject.keys
    }

    private fun isShared(key: String) = key in shared || "${key}_one" in shared

    /** Clés (et débuts de clés construites : « friends.label_ » + code) écrites dans un script de la page. */
    fun pageKeys(file: String): Set<String> =
        pageLiteral.findAll(File(repo, "trxstation/gateway/api/static/$file").readText(Charsets.UTF_8)).map { it.groupValues[1] }.toSet()

    /** Clés écrites dans un fichier de `:logic`. */
    fun appKeys(file: String): Set<String> =
        appLiteral.findAll(File("src/main/kotlin/com/rfdiy/openremotetrx/logic/$file").readText(Charsets.UTF_8))
            .map { it.groupValues[1] }.toSet()

    /**
     * Les clés de [appFile] qui commencent par l'un des [prefixes] (ou lui sont égales) sont des textes partagés, et la
     * page ([pageFile]) les écrit aussi : mêmes textes des deux côtés.
     */
    fun assertSameTexts(pageFile: String, appFile: String, vararg prefixes: String) {
        val keys = appKeys(appFile).filter { k -> prefixes.any { k == it || k.startsWith(it) } }.toSortedSet()
        assertTrue(keys.isNotEmpty(), "aucune clé ${prefixes.toList()} dans $appFile")
        assertSameKeys(pageFile, appFile, keys)
    }

    /** Ces clés de l'application sont partagées et la page les écrit (en entier ou par leur début terminé par « _ »). */
    fun assertSameKeys(pageFile: String, appFile: String, keys: Collection<String>) {
        val written = pageKeys(pageFile)
        val used = keys.filter { k -> k in written || written.any { it.endsWith("_") && k.startsWith(it) } }.toSet()
        assertEquals(emptyList(), keys.filterNot(::isShared), "clés de $appFile absentes de shared.fr.json")
        assertEquals(emptyList(), keys.filterNot { it in used }, "clés de $appFile que $pageFile n'écrit pas")
    }
}
