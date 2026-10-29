// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.rfdiy.openremotetrx.logic.LinkAlert
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.sin

/**
 * Sons de liaison, mêmes notes que la page (client.js, LINK_ALERTS) : « perdue » deux notes descendantes,
 * « rétablie » deux notes montantes, « perdue pour de bon » trois notes graves. Vibrations au même rythme.
 * Joués sur le téléphone seulement (jamais envoyés à la station). Une erreur de son ne gêne jamais la liaison.
 */
class LinkSounds(private val context: Context) {
    private class Alert(val notes: List<Triple<Int, Int, Int>>, val vibrate: LongArray)

    private val alerts = mapOf(
        LinkAlert.LOST to Alert(listOf(Triple(880, 160, 60), Triple(587, 260, 0)), longArrayOf(0, 200, 100, 300)),
        LinkAlert.RESTORED to Alert(listOf(Triple(587, 140, 50), Triple(880, 220, 0)), longArrayOf(0, 80, 60, 80)),
        LinkAlert.FAILED to Alert(
            listOf(Triple(330, 420, 140), Triple(330, 420, 140), Triple(247, 700, 0)),
            longArrayOf(0, 400, 150, 400, 150, 700),
        ),
    )

    /** Bips d'émission (E6) : aigu à la prise, grave à la fin. */
    private val txOn = Alert(listOf(Triple(1200, 90, 0)), longArrayOf(0, 60))
    private val txOff = Alert(listOf(Triple(700, 140, 0)), longArrayOf(0, 40, 60, 40))

    /** Bouton du casque ou du volant refusé (émission non autorisée, réception seule) : deux notes graves brèves. */
    private val refusedAlert = Alert(listOf(Triple(300, 120, 60), Triple(300, 120, 0)), longArrayOf(0, 120, 60, 120))

    fun play(kind: LinkAlert, volume: Float = 0.5f) {
        play(alerts[kind] ?: return, volume)
    }

    /**
     * Bip d'émission, joué dès que la station annonce SA prise (KEYING, micro encore fermé) ou son retour en
     * réception (micro fermé). Si la station passe directement en TX, la fin du bip (90 ms) peut tomber micro
     * ouvert : l'annulation d'écho doit l'effacer (à vérifier sur charge fictive).
     */
    fun txBeep(on: Boolean, volume: Float = 0.5f) {
        play(if (on) txOn else txOff, volume)
    }

    fun refused(volume: Float = 0.5f) {
        play(refusedAlert, volume)
    }

    /** « Écouter » un bip de fin de la station : segments (Hz, ms), 0 Hz = silence ; ici seulement, jamais émis. */
    fun playSequence(segments: List<Pair<Int, Int>>, volume: Float = 0.5f) {
        if (segments.isEmpty()) return
        runCatching { playPcm(render(Alert(segments.map { (hz, ms) -> Triple(hz, ms, 0) }, longArrayOf())), volume) }
    }

    private fun play(alert: Alert, volume: Float) {
        runCatching { vibrator()?.vibrate(VibrationEffect.createWaveform(alert.vibrate, -1)) }
        runCatching { playPcm(render(alert), volume) }
    }

    private fun vibrator(): Vibrator? =
        if (android.os.Build.VERSION.SDK_INT >= 31) {
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Vibrator::class.java)
        }

    /** Notes sinusoïdales avec montée et descente douces (pas de claquement). */
    private fun render(alert: Alert): ShortArray {
        val total = alert.notes.sumOf { (_, ms, gap) -> ms + gap } * RATE / 1000
        val out = ShortArray(total)
        var pos = 0
        for ((hz, ms, gap) in alert.notes) {
            val n = ms * RATE / 1000
            val ramp = RATE * 15 / 1000
            for (i in 0 until n) {
                val env = min(1.0, min(i.toDouble() / ramp, (n - i).toDouble() / ramp))
                out[pos + i] = (sin(2 * PI * hz * i / RATE) * env * Short.MAX_VALUE * 0.9).toInt().toShort()
            }
            pos += n + gap * RATE / 1000
        }
        return out
    }

    private fun playPcm(samples: ShortArray, volume: Float) {
        val track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
            )
            .setAudioFormat(
                AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build()
            )
            .setBufferSizeInBytes(samples.size * 2)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()
        track.write(samples, 0, samples.size)
        track.setVolume(volume)
        track.setNotificationMarkerPosition(samples.size)
        track.setPlaybackPositionUpdateListener(object : AudioTrack.OnPlaybackPositionUpdateListener {
            override fun onMarkerReached(t: AudioTrack) { t.release() }
            override fun onPeriodicNotification(t: AudioTrack) {}
        })
        track.play()
    }

    companion object {
        private const val RATE = 22_050
    }
}
