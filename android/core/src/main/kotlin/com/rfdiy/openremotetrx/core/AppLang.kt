// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.os.LocaleList
import com.rfdiy.openremotetrx.logic.Tr

/**
 * Langue de l'application (lot T2 du cahier docs/application-traduction-cahier-des-charges.md) : celle choisie dans
 * Réglages > Langue, sinon la première langue du téléphone proposée ([Tr.OFFERED]), sinon l'anglais. Appliquée au
 * démarrage de l'écran, du service et d'Android Auto ; la station reçoit la langue à la connexion suivante.
 */
object AppLang {
    const val PREF = "lang"

    /** Version de débogage (pseudo-langue permise). */
    fun debuggable(context: Context): Boolean =
        (context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0

    /** Langue choisie dans l'application, ou null (langue du téléphone). */
    fun stored(context: Context): String? =
        context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).getString(PREF, null)
            ?.takeIf { it in Tr.LANGS || (it == Tr.PSEUDO && debuggable(context)) }

    /** Langues du téléphone, dans l'ordre de ses réglages (« de-DE », « en-US »…). */
    fun system(): List<String> {
        val list = LocaleList.getDefault()
        return (0 until list.size()).map { list[it].toLanguageTag() }
    }

    fun apply(context: Context) {
        val chosen = stored(context)
        Tr.lang = if (chosen == Tr.PSEUDO) Tr.PSEUDO else Tr.chooseLang(chosen, system())
    }

    /**
     * Choix de l'opérateur (null = langue du téléphone). Refusé pendant une émission (les textes d'émission ne
     * changent pas sous les yeux de l'opérateur) : renvoie false, rien n'est changé.
     */
    fun choose(context: Context, lang: String?, transmitting: Boolean): Boolean {
        if (transmitting) return false
        val prefs = context.getSharedPreferences(RigHub.PREFS, Context.MODE_PRIVATE).edit()
        if (lang == null || (lang !in Tr.LANGS && !(lang == Tr.PSEUDO && debuggable(context)))) prefs.remove(PREF)
        else prefs.putString(PREF, lang)
        prefs.apply()
        apply(context)
        return true
    }
}
