// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Balayage du spectre HF (canal « spectrum », binaire, petit-boutiste ; docs/protocole.md § 8,
 * trxstation/spectrum/frame.py). `points` : un octet par point, de 0 à `level_max` (hello.spectrum).
 */
class SpectrumFrame(
    val mode: Int,
    val outOfRange: Boolean,
    val seq: Long,
    val lowHz: Long,
    val highHz: Long,
    val points: ByteArray,
) {
    /** Niveau du point `i`, 0..255 (octet non signé). */
    fun level(i: Int): Int = points[i].toInt() and 0xFF

    val size: Int get() = points.size

    companion object {
        const val VERSION = 1
        const val HEADER = 16

        /** Trame -> balayage, ou null si illisible (version inconnue, bords incohérents, aucun point). */
        fun parse(bytes: ByteArray): SpectrumFrame? {
            if (bytes.size <= HEADER || bytes[0].toInt() != VERSION) return null
            val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val seq = b.getInt(4).toLong() and 0xFFFFFFFFL
            val low = b.getInt(8).toLong() and 0xFFFFFFFFL
            val high = b.getInt(12).toLong() and 0xFFFFFFFFL
            if (high <= low) return null
            return SpectrumFrame(
                mode = bytes[1].toInt() and 0xFF,
                outOfRange = (bytes[2].toInt() and 1) == 1,
                seq = seq, lowHz = low, highHz = high,
                points = bytes.copyOfRange(HEADER, bytes.size),
            )
        }

        /** Vrai si `seq` est plus récent que `last` (numéro sur 32 bits qui peut boucler). */
        fun newer(seq: Long, last: Long?): Boolean {
            if (last == null) return true
            val d = (seq - last) and 0xFFFFFFFFL
            return d != 0L && d < 0x80000000L
        }
    }
}
