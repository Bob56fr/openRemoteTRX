// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlin.math.max
import kotlin.math.roundToInt

/** Affichages repris de la page (client.js : formatFrequency, sMeterText). */
object Format {
    /** 14074000 -> « 14 074 000 Hz » ; null -> « — ». */
    fun frequency(hz: Long?): String {
        if (hz == null) return "—"
        return hz.toString().reversed().chunked(3).joinToString(" ").reversed() + " Hz"
    }

    /** dB relatifs à S9 (S9 = 0 ; un point S = 6 dB) -> « S7 », « S9 », « S9+20 dB ». */
    fun sMeter(db: Double?): String {
        if (db == null) return "—"
        if (db >= 0) return if (db == 0.0) "S9" else "S9+${db.roundToInt()} dB"
        return "S${max(0, (9 + db / 6).roundToInt())}"
    }

    /** Secondes -> « 1:05 ». */
    fun duration(seconds: Int): String = "%d:%02d".format(seconds / 60, seconds % 60)
}
