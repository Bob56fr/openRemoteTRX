// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.LuminanceSource
import com.google.zxing.NotFoundException
import com.google.zxing.ReaderException
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.GlobalHistogramBinarizer
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader

/**
 * QR code d'appairage lu dans une IMAGE (photo ou capture d'écran de la bibliothèque du téléphone), en plus de
 * l'appareil photo. Pixels ARGB (Bitmap.getPixels) ; essaie les deux seuillages de ZXing, puis l'image inversée
 * (capture d'un terminal sombre : QR clair sur fond noir). Le texte lu passe ensuite par PairingCode.parse, comme
 * celui de l'appareil photo. null : aucun QR code trouvé.
 */
object QrImage {
    private val HINTS = mapOf(
        DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
        DecodeHintType.TRY_HARDER to true,
    )

    fun decode(width: Int, height: Int, argb: IntArray): String? {
        if (width <= 0 || height <= 0 || argb.size < width * height) return null
        val source: LuminanceSource = RGBLuminanceSource(width, height, argb)
        for (s in listOf(source, source.invert())) {
            for (bitmap in listOf(BinaryBitmap(HybridBinarizer(s)), BinaryBitmap(GlobalHistogramBinarizer(s)))) {
                try {
                    return QRCodeReader().decode(bitmap, HINTS).text
                } catch (e: NotFoundException) {
                    continue
                } catch (e: ReaderException) {                       // somme de contrôle, format : essai suivant
                    continue
                }
            }
        }
        return null
    }
}
