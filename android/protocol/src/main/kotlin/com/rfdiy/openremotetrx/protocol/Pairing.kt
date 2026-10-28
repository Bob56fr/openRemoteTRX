// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import java.net.URI
import java.net.URLDecoder
import java.security.MessageDigest

object Fingerprint {
    /** « ab cd … », « AB:CD:… » ou 64 chiffres hexadécimaux -> « AB:CD:… » (95 caractères), sinon null. */
    fun normalize(text: String): String? {
        if (text.any { it !in HEX && it != ':' && !it.isWhitespace() }) return null
        val hex = text.uppercase().filter { it in HEX }
        if (hex.length != 64) return null
        return hex.chunked(2).joinToString(":")
    }

    fun of(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString(":") { "%02X".format(it) }

    private const val HEX = "0123456789ABCDEFabcdef"
}

object StationAddress {
    /**
     * Adresse saisie -> « https://hôte:port » (port 8443 par défaut, celui de la station), sinon null.
     * HTTPS obligatoire : la page n'est servie en HTTP que derrière un VPN, cas non pris en charge ici.
     */
    fun normalize(text: String): String? {
        var t = text.trim().trimEnd('/')
        if (t.isEmpty()) return null
        if (!t.contains("://")) t = "https://$t"
        val uri = try { URI(t) } catch (e: Exception) { return null }
        if (uri.scheme?.lowercase() != "https" || uri.host.isNullOrEmpty()) return null
        if (!uri.path.isNullOrEmpty() || uri.query != null || uri.userInfo != null) return null
        val port = if (uri.port == -1) 8443 else uri.port
        val host = if (uri.host.contains(':') && !uri.host.startsWith("[")) "[${uri.host}]" else uri.host
        return "https://$host:$port"
    }
}

/** Ce qu'apporte le QR code d'appairage (TRX Console, menu 19). Jamais de mot de passe. */
data class Pairing(val name: String, val url: String, val user: String, val fingerprint: String)

object PairingCode {
    const val PREFIX = "openremotetrx://pair?"

    /**
     * « openremotetrx://pair?v=1&n=…&u=…&id=…&fp=… » (docs/protocole.md § 12) -> Pairing, sinon null.
     * `u` obligatoire (https) ; `fp` vide = certificat reconnu (proxy) ; paramètres inconnus ignorés ; un mot de
     * passe éventuel n'est JAMAIS lu.
     */
    fun parse(text: String): Pairing? {
        val t = text.trim()
        if (!t.startsWith(PREFIX)) return null
        val params = t.removePrefix(PREFIX).split('&').filter { it.isNotEmpty() }.associate { part ->
            val (k, v) = if ('=' in part) part.split('=', limit = 2) else listOf(part, "")
            k to try { URLDecoder.decode(v, "UTF-8") } catch (e: IllegalArgumentException) { return null }
        }
        if (params["v"] != "1") return null
        val url = StationAddress.normalize(params["u"] ?: return null) ?: return null
        val fp = params["fp"].orEmpty()
        val fingerprint = if (fp.isEmpty()) "" else Fingerprint.normalize(fp) ?: return null
        val user = params["id"].orEmpty().takeIf { it.matches(Regex("[A-Za-z0-9_-]{0,32}")) } ?: return null
        val name = params["n"].orEmpty().trim().take(40).ifEmpty { URI(url).host }
        return Pairing(name, url, user, fingerprint)
    }
}
