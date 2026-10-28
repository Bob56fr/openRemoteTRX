// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.rfdiy.openremotetrx.logic.BandSpot
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Une station appairée. `fingerprint` : empreinte SHA-256 du certificat (TRX Console menu 19), « AB:CD:… » ;
 * vide = certificat signé par une autorité reconnue (proxy HTTPS), vérifié normalement par Android.
 */
@Serializable
data class StationAccount(
    val id: String = UUID.randomUUID().toString(),
    val name: String,
    val url: String,
    val user: String,
    val fingerprint: String = "",
    val reconnectWindowS: Int = 60,
    /** Mot de passe chiffré par une clé du Keystore Android (jamais en clair), ou vide. */
    val secret: String = "",
)

/** Liste des stations, dans les préférences privées de l'application ; mots de passe chiffrés (Keystore). */
class AccountStore(context: Context) {
    private val prefs = context.getSharedPreferences("stations", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true }

    fun list(): List<StationAccount> =
        try { json.decodeFromString<List<StationAccount>>(prefs.getString("list", "[]") ?: "[]") } catch (e: Exception) { emptyList() }

    /** Enregistre (ou remplace) ; `password` non nul : mémorisé chiffré ; vide : oublié. */
    fun save(account: StationAccount, password: String?): StationAccount {
        val stored = when {
            password == null -> account
            password.isEmpty() -> account.copy(secret = "")
            else -> account.copy(secret = Secrets.encrypt(password))
        }
        val others = list().filter { it.id != stored.id }
        prefs.edit().putString("list", json.encodeToString(others + stored)).apply()
        return stored
    }

    fun delete(id: String) {
        prefs.edit().putString("list", json.encodeToString(list().filter { it.id != id })).apply()
    }

    fun password(account: StationAccount): String? =
        account.secret.takeIf { it.isNotEmpty() }?.let { Secrets.decrypt(it) }

    var lastId: String?
        get() = prefs.getString("last", null)
        set(value) { prefs.edit().putString("last", value).apply() }
}

/** Chiffrement AES-GCM par une clé non exportable du Keystore Android. */
private object Secrets {
    private const val ALIAS = "trx-stations"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return gen.generateKey()
    }

    fun encrypt(text: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val data = cipher.iv + cipher.doFinal(text.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(data, Base64.NO_WRAP)
    }

    /** null si illisible (clé effacée, sauvegarde restaurée sur un autre téléphone) : on redemandera le mot de passe. */
    fun decrypt(text: String): String? = try {
        val data = Base64.decode(text, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, data, 0, 12))
        String(cipher.doFinal(data, 12, data.size - 12), Charsets.UTF_8)
    } catch (e: Exception) {
        null
    }
}

/** Mémoire des bandes, par station : « 20=14074000:USB;40=7100000:LSB ». Illisible = vide (BandMemory refait le tri). */
class BandStore(context: Context) {
    private val prefs = context.getSharedPreferences("bands", Context.MODE_PRIVATE)

    fun load(stationId: String): Map<String, BandSpot> =
        (prefs.getString(stationId, "") ?: "").split(';').mapNotNull { item ->
            val (key, value) = item.split('=', limit = 2).takeIf { it.size == 2 } ?: return@mapNotNull null
            val (hz, mode) = value.split(':', limit = 2).takeIf { it.size == 2 } ?: return@mapNotNull null
            val f = hz.toLongOrNull() ?: return@mapNotNull null
            if (!mode.matches(Regex("[A-Za-z0-9-]{1,16}"))) return@mapNotNull null
            key to BandSpot(f, mode)
        }.toMap()

    fun save(stationId: String, spots: Map<String, BandSpot>) {
        prefs.edit().putString(stationId, spots.entries.joinToString(";") { "${it.key}=${it.value.hz}:${it.value.mode}" }).apply()
    }
}
