// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class QrImageTest {
    private val text = "openremotetrx://pair?v=1&n=Maison&u=https%3A%2F%2F192.0.2.10%3A8443&id=phone&fp=AA%3ABB"

    /** QR code dessiné dans une « capture » plus grande, avec une marge et un facteur d'échelle. */
    private fun image(dark: Int, light: Int, scale: Int = 6, margin: Int = 40): Triple<Int, Int, IntArray> {
        val m = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 0, 0)
        val w = m.width * scale + 2 * margin
        val h = m.height * scale + 2 * margin
        val px = IntArray(w * h) { light }
        for (y in 0 until m.height) for (x in 0 until m.width) if (m[x, y]) {
            for (dy in 0 until scale) for (dx in 0 until scale) px[(margin + y * scale + dy) * w + margin + x * scale + dx] = dark
        }
        return Triple(w, h, px)
    }

    @Test
    fun `QR code noir sur blanc (photo, capture claire)`() {
        val (w, h, px) = image(0xFF000000.toInt(), 0xFFFFFFFF.toInt())
        assertEquals(text, QrImage.decode(w, h, px))
    }

    @Test
    fun `QR code clair sur fond sombre (capture du terminal de TRX Console)`() {
        val (w, h, px) = image(0xFFE0E0E0.toInt(), 0xFF101010.toInt())
        assertEquals(text, QrImage.decode(w, h, px))
    }

    @Test
    fun `image sans QR code ou invalide - null, jamais d exception`() {
        assertNull(QrImage.decode(100, 100, IntArray(100 * 100) { 0xFF808080.toInt() }))
        assertNull(QrImage.decode(0, 0, IntArray(0)))
        assertNull(QrImage.decode(10, 10, IntArray(5)))
    }
}
