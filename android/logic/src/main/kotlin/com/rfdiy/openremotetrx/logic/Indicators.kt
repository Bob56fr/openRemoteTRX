// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.Hello
import com.rfdiy.openremotetrx.protocol.State
import java.util.Locale
import kotlin.math.roundToInt

/** Voyant de l'afficheur (comme sur un poste) : texte vert si actif, gris sinon. */
data class Indicator(val label: String, val on: Boolean, val alert: Boolean = false)

/**
 * Voyants à côté de la fréquence (demande de l'utilisateur) : ATT, ou P.AMP 1 / P.AMP 2, ou rien ; RIT ; ΔTX (XIT) ;
 * SPLIT ; NOTCH ; NB ; NR. Seuls les voyants dont la station publie l'état sont montrés ; le VFO actif en tête, si le
 * poste le dit (Yaesu FTDX10 / FTDX101 : oui ; IC-7300MK2 : non). POWER, SWR, ALC ne sont pas des voyants mais des bargraphs (`Indicators.txMeters`).
 */
object Indicators {
    /** Seuil du voyant « OVERLOAD ALC » (page : ALC_OVERLOAD ; station : selcall/calibrate.py). */
    const val ALC_OVERLOAD = 0.5

    fun of(hello: Hello?, state: State?): List<Indicator> {
        val rig = state?.rig ?: return emptyList()
        val fn = rig.functions
        val out = mutableListOf<Indicator>()
        vfoLabel(rig.vfo).takeIf { it.isNotEmpty() }?.let { out += Indicator(it, true) }
        val att = rig.levels["ATT"] ?: 0.0
        val preamp = rig.levels["PREAMP"] ?: 0.0
        when {
            att > 0 -> out += Indicator("ATT", true)
            preamp > 0 -> out += Indicator("P.AMP ${preampNumber(preamp, hello?.capabilities?.preamps.orEmpty())}", true)
        }
        // Clarifieur et split (lus par la station)
        fn["RIT"]?.let { out += Indicator("RIT", it) }
        fn["XIT"]?.let { out += Indicator("ΔTX", it) }
        rig.split?.let { out += Indicator("SPLIT", it) }
        if ("ANF" in fn || "MN" in fn) out += Indicator("NOTCH", fn["ANF"] == true || fn["MN"] == true)
        fn["NB"]?.let { out += Indicator("NB", it) }
        fn["NR"]?.let { out += Indicator("NR", it) }
        // ALC en surcharge pendant une émission, quel que soit l'usage (même seuil que la page et la station)
        rig.levels["ALC"]?.let { if (it >= ALC_OVERLOAD) out += Indicator("OVERLOAD ALC", on = true, alert = true) }
        return out
    }

    private val VFO_RE = Regex("[A-Za-z][A-Za-z0-9_]{0,11}")
    private val VFO_NAMES = mapOf("VFOA" to "VFO A", "VFOB" to "VFO B", "VFOC" to "VFO C")

    /** VFO actif -> texte du voyant (comme la page : vfoLabel) ; vide si absent ou sans signification (currVFO). */
    fun vfoLabel(vfo: String?): String {
        if (vfo == null || !VFO_RE.matches(vfo) || vfo.equals("currVFO", true) || vfo.equals("None", true)) return ""
        val up = vfo.uppercase(Locale.ROOT)
        return VFO_NAMES[up] ?: up
    }

    /** Numéro du préampli : rang dans la liste du poste (10 dB -> 1, 20 dB -> 2), ou la valeur lue si c'est déjà 1 ou 2. */
    fun preampNumber(level: Double, preamps: List<Int>): Int {
        val v = level.roundToInt()
        val i = preamps.indexOf(v)
        return if (i >= 0) i + 1 else v
    }

    /**
     * Bargraphs POWER, SWR, ALC, toujours affichés comme sur un poste (à zéro en réception : la station ne publie ces
     * mesures que pendant l'émission).
     */
    fun txMeters(state: State?): List<Meter> {
        val lv = state?.rig?.levels.orEmpty()
        val po = lv["RFPOWER_METER"]?.coerceIn(0.0, 1.0)
        val swr = lv["SWR"]
        val alc = lv["ALC"]?.coerceIn(0.0, 1.0)
        return listOf(
            Meter("PO", "POWER", po?.let { "${(it * 100).roundToInt()} %" } ?: "—", (po ?: 0.0).toFloat()),
            Meter("SWR", "SWR", swr?.let { String.format(Locale.ROOT, "%.1f", it) } ?: "—", ((swr ?: 1.0) - 1).div(2).coerceIn(0.0, 1.0).toFloat()),
            Meter("ALC", "ALC", alc?.let { "${(it * 100).roundToInt()} %" } ?: "—", (alc ?: 0.0).toFloat()),
        )
    }
}
