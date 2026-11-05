// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.res.AssetFileDescriptor
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import com.rfdiy.openremotetrx.logic.Artwork
import java.io.File
import java.io.FileNotFoundException

/**
 * Pochettes d'Android Auto (F5), en lecture seule, sans réseau : `content://<paquet>.artwork/<clé>`.
 * Ordre : fichier de l'utilisateur (`Android/data/<paquet>/files/pochettes/<clé>.png` ou `.jpg`), image fournie
 * (`assets/pochettes/<clé>.jpg`, scripts/build_car_art.py), puis le logo de l'utilisateur ou fourni. Seules les clés
 * de `Artwork.KEYS` sont servies (pas de chemin libre).
 * Exporté : la voiture (autre application) doit pouvoir lire l'image ; rien d'autre n'est exposé.
 */
class ArtworkProvider : ContentProvider() {
    override fun onCreate() = true

    override fun getType(uri: Uri): String {
        val ctx = context ?: return "image/jpeg"
        val key = uri.lastPathSegment ?: return "image/jpeg"
        return if (userFile(ctx, key)?.extension == "png") "image/png" else "image/jpeg"
    }

    override fun openAssetFile(uri: Uri, mode: String): AssetFileDescriptor {
        if (mode != "r") throw SecurityException("lecture seule")
        val ctx = context ?: throw FileNotFoundException()
        val key = uri.lastPathSegment?.takeIf { Artwork.isKey(it) } ?: throw FileNotFoundException()
        for (k in listOf(key, Artwork.LOGO).distinct()) {
            userFile(ctx, k)?.let {
                return AssetFileDescriptor(ParcelFileDescriptor.open(it, ParcelFileDescriptor.MODE_READ_ONLY), 0, AssetFileDescriptor.UNKNOWN_LENGTH)
            }
            runCatching { return ctx.assets.openFd("$ASSETS/$k.jpg") }
        }
        throw FileNotFoundException(key)
    }

    override fun query(uri: Uri, p: Array<out String>?, s: String?, a: Array<out String>?, o: String?): Cursor? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, s: String?, a: Array<out String>?) = 0
    override fun update(uri: Uri, v: ContentValues?, s: String?, a: Array<out String>?) = 0

    companion object {
        const val ASSETS = "pochettes"

        /** Dossier où l'utilisateur dépose ses images (créé au premier usage, visible depuis le PC). */
        fun userDir(context: Context): File? = context.getExternalFilesDir(ASSETS)

        /** Image déposée par l'utilisateur (PNG prioritaire sur JPEG), clé déjà vérifiée par l'appelant. */
        private fun userFile(context: Context, key: String): File? {
            if (!Artwork.isKey(key)) return null
            val dir = userDir(context) ?: return null
            return listOf("png", "jpg").map { File(dir, "$key.$it") }.firstOrNull { it.isFile && it.length() > 0 }
        }

        /**
         * Adresse de l'image ; `v` change quand l'utilisateur remplace son fichier, pour que la voiture ne garde pas
         * l'ancienne en cache.
         */
        fun uri(context: Context, key: String): Uri {
            val v = userFile(context, key)?.lastModified() ?: 0L
            return Uri.parse("content://${context.packageName}.artwork/$key?v=$v")
        }
    }
}
