// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.core

import com.rfdiy.openremotetrx.protocol.Fingerprint
import java.io.IOException
import java.net.URL
import java.security.cert.CertPathValidatorException
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.X509TrustManager
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/** Échec d'un essai de connexion ; `code` : clé de Texts.LOSSES (network, auth, busy, http, pin…). */
class AttemptException(val code: String, val detail: String = "") : Exception(code)

/**
 * Requêtes HTTPS vers la station (GET /config, POST /offer). Avec une empreinte : SEUL ce certificat est accepté
 * (épinglage, nom d'hôte ignoré : un certificat auto-signé de la station porte rarement l'adresse utilisée).
 * Sans empreinte : vérification normale d'Android (autorité reconnue + nom d'hôte). Jamais « faire confiance à tout ».
 */
class StationHttp(private val baseUrl: String, fingerprint: String) {
    private val pin = fingerprint.takeIf { it.isNotEmpty() }

    private class PinMismatch(val seen: String) : CertificateException("empreinte différente")

    // Épinglage voulu (alerte « CustomX509TrustManager » de lint) : seul le certificat dont l'empreinte SHA-256 est
    // exactement celle de l'appairage passe ; tout autre certificat, même valide ailleurs, est refusé.
    private val pinnedTrust: X509TrustManager? = pin?.let { expected ->
        object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
                throw CertificateException("non utilisé")

            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                val leaf = chain?.firstOrNull() ?: throw CertificateException("aucun certificat")
                val seen = Fingerprint.of(leaf.encoded)
                if (seen != expected) throw PinMismatch(seen)
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
    }

    private val sslContext: SSLContext? = pinnedTrust?.let { tm ->
        SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }
    }

    /** Serveurs STUN annoncés par la station (vide si /config est indisponible : réseau local ou VPN). */
    fun iceServers(): List<String> = try {
        val (status, body) = request("GET", "/config", null)
        if (status != 200) emptyList() else {
            val arr = Json.parseToJsonElement(body).jsonObject["ice_servers"] as? JsonArray
            arr?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }?.take(8) ?: emptyList()
        }
    } catch (e: AttemptException) {
        if (e.code == "pin") throw e                            // empreinte différente : on s'arrête là, jamais d'offre
        emptyList()
    } catch (e: Exception) {
        emptyList()
    }

    /** POST /offer ; renvoie le SDP de réponse. 401 => auth, 403 => refused (message de la station), 503 => busy, autre => http. */
    fun offer(clientId: String, password: String, sdp: String): String {
        val body = buildJsonObject {
            put("client_id", clientId); put("password", password); put("sdp", sdp); put("type", "offer")
        }.toString()
        val (status, text) = request("POST", "/offer", body)
        // 403 / 503 avec {error, message} : accès refusé alors que le mot de passe est juste (visiteurs, station 0.71.0+)
        val said = try {
            (Json.parseToJsonElement(text).jsonObject["message"] as? JsonPrimitive)?.contentOrNull?.take(200) ?: ""
        } catch (e: Exception) { "" }
        when (status) {
            200 -> Unit
            401 -> throw AttemptException("auth")
            403 -> throw AttemptException("refused", said)
            503 -> throw AttemptException("busy", said)
            else -> throw AttemptException("http", "HTTP $status")
        }
        val obj = try { Json.parseToJsonElement(text).jsonObject } catch (e: Exception) { throw AttemptException("http", "réponse illisible") }
        return (obj["sdp"] as? JsonPrimitive)?.contentOrNull ?: throw AttemptException("http", "réponse sans SDP")
    }

    private fun request(method: String, path: String, body: String?): Pair<Int, String> {
        val conn = try {
            URL(baseUrl + path).openConnection() as HttpsURLConnection
        } catch (e: Exception) {
            throw AttemptException("network", e.message ?: "")
        }
        try {
            sslContext?.let {
                conn.sslSocketFactory = it.socketFactory
                conn.hostnameVerifier = HostnameVerifier { _, _ -> true }   // l'empreinte suffit
            }
            conn.requestMethod = method
            conn.connectTimeout = 8000
            conn.readTimeout = 10_000
            conn.useCaches = false
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.use { s -> s.readBytes().take(MAX_BODY).toByteArray().toString(Charsets.UTF_8) } ?: ""
            return status to text
        } catch (e: SSLHandshakeException) {
            val mismatch = generateSequence(e as Throwable) { it.cause }.filterIsInstance<PinMismatch>().firstOrNull()
            if (mismatch != null) throw AttemptException("pin", "reçue ${mismatch.seen.take(23)}…")
            // Sans empreinte, un certificat auto-signé (cas normal de la station) est refusé par Android.
            if (pin == null && generateSequence(e as Throwable) { it.cause }.any { it is CertPathValidatorException }) {
                throw AttemptException("untrusted")
            }
            throw AttemptException("network", "TLS : ${e.message ?: ""}".take(160))
        } catch (e: IOException) {
            throw AttemptException("network", (e.message ?: e.javaClass.simpleName).take(160))
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        private const val MAX_BODY = 256 * 1024
    }
}
