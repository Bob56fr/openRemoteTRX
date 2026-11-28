// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import java.io.File
import java.util.Random
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Banc du décodeur de SA manipulation (branche exp/cw) : un message réaliste envoyé par des « poignets » simulés,
 * plus ou moins réguliers, en pioche (rythme entièrement humain) et aux palettes (éléments calibrés par le
 * manipulateur iambique, erreurs humaines sur le lâcher des palettes et les espaces). Taux d'erreur par caractère
 * (distance d'édition) sur 40 tirages par scénario, graines fixes : rapport dans build/reports/cw-bench.md.
 */
class CwDecoderBenchTest {
    private val message = "CQ CQ DE F4XYZ/P F4XYZ/P K F4XYZ DE DL1ABC GM UR RST 579 5NN QTH LORIENT NAME BOB HW? 73 TU ="
    private val code = CwDecoder.MORSE.entries.associate { (k, v) -> v to k }
    private val runs = 40
    private val setWpm = 20

    /** Poignet en pioche. Durées en points de l'opérateur, multipliées par N(1, sigma). */
    data class Fist(val sigma: Double = 0.0, val dash: Double = 3.0, val letter: Double = 3.0, val word: Double = 7.0,
                    val wpmFrom: Double = 20.0, val wpmTo: Double = 20.0)

    /** Poignet aux palettes : `release` = écart type du lâcher (en points), `gapSigma` = des espaces entre lettres. */
    data class Hand(val release: Double, val gapSigma: Double = 0.15, val letter: Double = 3.0, val word: Double = 7.0,
                    val iface: CwInterface = CwInterface.IAMBIC_B)

    private fun straight(fist: Fist, rnd: Random): List<KeyEdge> {
        val out = mutableListOf<KeyEdge>()
        var t = 100.0
        val total = message.length.toDouble()
        fun g() = (1 + fist.sigma * rnd.nextGaussian()).coerceAtLeast(0.2)
        message.forEachIndexed { i, c ->
            val wpm = fist.wpmFrom + (fist.wpmTo - fist.wpmFrom) * i / total
            val dot = 1200.0 / wpm
            if (c == ' ') { t += dot * (fist.word - fist.letter) * g(); return@forEachIndexed }
            code.getValue(c).forEachIndexed { k, s ->
                if (k > 0) t += dot * g()
                out += KeyEdge(t, true)
                t += dot * (if (s == '.') 1.0 else fist.dash) * g()
                out += KeyEdge(t, false)
            }
            t += dot * fist.letter * g()
        }
        return out
    }

    private fun paddles(hand: Hand, rnd: Random): List<KeyEdge> {
        val keyer = CwKeyer(hand.iface, setWpm)
        val dot = keyer.dotMs
        val out = mutableListOf<KeyEdge>()
        // l'opérateur vise le milieu de la fenêtre utile pour lâcher la dernière palette d'une série
        var t = 100.0
        for (word in message.split(' ')) {
            for (c in word) {
                val elements = code.getValue(c)
                val series = mutableListOf<Pair<Paddle, Int>>()
                for (s in elements) {
                    val p = if (s == '.') Paddle.DOT else Paddle.DASH
                    if (series.isNotEmpty() && series.last().first == p) series[series.size - 1] = p to series.last().second + 1
                    else series += p to 1
                }
                var start = t
                for ((p, n) in series) {
                    // départ de la série : instant où le manipulateur la commence (rejoué plus bas)
                    keyer.press(start, p, true).also { out += it }
                    val runStart = out.lastOrNull { it.down && it.at >= start - 1e-6 }?.at ?: run {
                        var s = start
                        while (true) {
                            val next = keyer.nextEventAt ?: break
                            val e = keyer.advance(next); out += e
                            val d = e.firstOrNull { it.down }
                            if (d != null) { s = d.at; break }
                        }
                        s
                    }
                    val len = if (p == Paddle.DOT) dot else dot * keyer.weight
                    val window = len + dot
                    val release = runStart + n * window - window / 2 + hand.release * dot * rnd.nextGaussian()
                    // éléments produits jusqu'au lâcher
                    out += keyer.advance(release)
                    out += keyer.press(release, p, false)
                    // série suivante : la main passe à l'autre palette autour du lâcher
                    start = release + 0.3 * dot * rnd.nextGaussian().let { abs(it) }
                }
                // fin de lettre : le manipulateur finit son élément, puis l'espace entre lettres de l'opérateur
                while (true) { val next = keyer.nextEventAt ?: break; out += keyer.advance(next) }
                val lastUp = out.last { !it.down }.at
                t = lastUp + dot * hand.letter * (1 + hand.gapSigma * rnd.nextGaussian()).coerceAtLeast(0.3)
            }
            t += dot * (hand.word - hand.letter) * (1 + hand.gapSigma * rnd.nextGaussian()).coerceAtLeast(0.3)
        }
        return out.sortedBy { it.at }
    }

    private fun decode(edges: List<KeyEdge>): String {
        val d = CwDecoder(setWpm)
        edges.forEach(d::edge)
        d.poll((edges.lastOrNull()?.at ?: 0.0) + 60_000.0)
        return d.shown.trim()
    }

    private fun distance(a: String, b: String): Int {
        val prev = IntArray(b.length + 1) { it }
        val cur = IntArray(b.length + 1)
        for (i in 1..a.length) {
            cur[0] = i
            for (j in 1..b.length) cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (a[i - 1] == b[j - 1]) 0 else 1)
            cur.copyInto(prev)
        }
        return prev[b.length]
    }

    data class Result(val name: String, val cer: Double, val words: Double, val example: String)

    private fun bench(name: String, send: (Random) -> List<KeyEdge>): Result {
        var errors = 0; var wordsOk = 0; var worst = ""; var worstErr = -1
        val wordsSent = message.split(' ')
        repeat(runs) { seed ->
            val got = decode(send(Random(1000L + seed)))
            val e = distance(message, got)
            errors += e
            val gotWords = got.split(' ').filter { it.isNotEmpty() }.toSet()
            wordsOk += wordsSent.count { it in gotWords }
            if (seed < 10 && e > worstErr) { worstErr = e; worst = got }
        }
        return Result(name, errors.toDouble() / (runs * message.length), wordsOk.toDouble() / (runs * wordsSent.size), worst)
    }

    @Test
    fun `banc du décodeur, pioche et palettes, rapport`() {
        val results = listOf(
            bench("Pioche, rythme parfait") { straight(Fist(), it) },
            bench("Pioche, irrégularité 10 %") { straight(Fist(sigma = 0.10), it) },
            bench("Pioche, irrégularité 20 %") { straight(Fist(sigma = 0.20), it) },
            bench("Pioche, irrégularité 30 %") { straight(Fist(sigma = 0.30), it) },
            bench("Pioche, traits lourds (4 points), 15 %") { straight(Fist(sigma = 0.15, dash = 4.0), it) },
            bench("Pioche, traits courts (2,2 points), 15 %") { straight(Fist(sigma = 0.15, dash = 2.2), it) },
            bench("Pioche, lettres serrées (2,2 points), 15 %") { straight(Fist(sigma = 0.15, letter = 2.2), it) },
            bench("Pioche, espaces larges (5 / 12 points), 15 %") { straight(Fist(sigma = 0.15, letter = 5.0, word = 12.0), it) },
            bench("Pioche à 16 mots/min (réglage 20), 15 %") { straight(Fist(sigma = 0.15, wpmFrom = 16.0, wpmTo = 16.0), it) },
            bench("Pioche à 26 mots/min (réglage 20), 15 %") { straight(Fist(sigma = 0.15, wpmFrom = 26.0, wpmTo = 26.0), it) },
            bench("Pioche qui accélère 18 → 25 mots/min, 15 %") { straight(Fist(sigma = 0.15, wpmFrom = 18.0, wpmTo = 25.0), it) },
            bench("Palettes B, lâcher ±0,3 point") { paddles(Hand(release = 0.3), it) },
            bench("Palettes B, lâcher ±0,5 point") { paddles(Hand(release = 0.5), it) },
            bench("Palettes B, lâcher ±0,8 point") { paddles(Hand(release = 0.8), it) },
            bench("Palettes A, lâcher ±0,5 point") { paddles(Hand(release = 0.5, iface = CwInterface.IAMBIC_A), it) },
            bench("Palettes B, lettres serrées (2,2 points)") { paddles(Hand(release = 0.3, letter = 2.2), it) },
            bench("Palettes B, espaces larges (5 / 12 points)") { paddles(Hand(release = 0.3, letter = 5.0, word = 12.0), it) },
            bench("Palettes B, espaces très irréguliers (40 %)") { paddles(Hand(release = 0.3, gapSigma = 0.4), it) },
        )
        val report = buildString {
            appendLine("# Banc du décodeur CW (réglage $setWpm mots/min, $runs tirages par ligne)")
            appendLine()
            appendLine("Message : `$message`")
            appendLine()
            appendLine("| Scénario | Erreurs / caractère | Mots exacts | Exemple (pire des 10 premiers tirages) |")
            appendLine("|---|---:|---:|---|")
            results.forEach { appendLine("| ${it.name} | ${"%.1f".format(it.cer * 100)} % | ${"%.0f".format(it.words * 100)} % | `${it.example}` |") }
        }
        File("build/reports").mkdirs()
        File("build/reports/cw-bench.md").writeText(report)
        println(report)
        // seuls garde-fous : un poignet parfait ou propre se lit sans faute
        assertEquals(0.0, results[0].cer)
        assertTrue(results[11].cer < 0.02, "palettes propres : ${results[11].cer}")
    }
}
