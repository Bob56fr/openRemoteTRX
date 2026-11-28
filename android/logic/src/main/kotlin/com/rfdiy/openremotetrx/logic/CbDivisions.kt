// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

/**
 * Pays d'un indicatif de cibiste (DX 11 m, étape 410) d'après son numéro de DIVISION : « 14LG56 » = 14 = France,
 * « 1AT/H688 » = 1 = Italie, « 10/108AT150 » = trafic depuis la division 10 (Mexique) d'un opérateur de la 108.
 * Les spots CB (clusterdx.org) arrivent sans pays : cty.dat ne connaît pas ces indicatifs. Table en anglais dans la
 * ressource `cb_divisions.txt` (liste de la communauté). Kotlin pur (compilé aussi par openRemoteTRX Lite).
 */
object CbDivisions {
    private val PORTABLE = Regex("^(\\d{1,3})/")           // division d'où l'on trafique, avant la barre
    private val HOME = Regex("^(\\d{1,3})[A-Z]")            // numéro en tête, suivi d'une lettre

    val table: Map<Int, String> by lazy {
        val text = CbDivisions::class.java.getResourceAsStream("/cb_divisions.txt")?.use { it.readBytes().toString(Charsets.UTF_8) }
        text.orEmpty().lineSequence().mapNotNull { line ->
            if (line.startsWith("#")) return@mapNotNull null
            val i = line.indexOf('|')
            val n = if (i > 0) line.substring(0, i).trim().toIntOrNull() else null
            if (n == null) null else n to line.substring(i + 1).trim()
        }.toMap()
    }

    /** Numéro de division de l'indicatif, ou null s'il n'en commence pas par un. */
    fun division(call: String): Int? {
        val c = call.trim().uppercase()
        return (PORTABLE.find(c) ?: HOME.find(c))?.groupValues?.get(1)?.toIntOrNull()
    }

    /** Pays (anglais) de l'indicatif de cibiste, "" si inconnu. */
    fun country(call: String): String = division(call)?.let { table[it] }.orEmpty()
}
