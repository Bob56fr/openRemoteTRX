// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.time.ZoneOffset
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

private class FrLink : SessionLink {
    val sent = mutableListOf<String>()
    override fun startAttempt() {}
    override fun send(text: String): Boolean { sent += text; return true }
    override fun setMicOpen(open: Boolean) {}
    override fun close() {}
    override fun alert(kind: LinkAlert) {}
    fun last(cmd: String): JsonObject = Json.parseToJsonElement(sent.last { it.contains("\"cmd\":\"$cmd\"") }).jsonObject
    fun count(cmd: String, action: String? = null) = sent.count {
        it.contains("\"cmd\":\"$cmd\"") && (action == null || it.contains("\"action\":\"$action\""))
    }
}

/** Présence de groupe « Amis » : mêmes règles et mêmes textes que la page (friends.js) et la station. */
class FriendsTest {
    private val repo = System.getProperty("trx.repo") ?: "../.."
    private val vectors = Json.parseToJsonElement(File(repo, "tests/protocol/presence_vectors.json").readText()).jsonObject
    private val page = File(repo, "trxstation/gateway/api/static/friends.js").readText()
    private val now = 1_794_000_000L
    private val utc = ZoneOffset.UTC

    private fun member(extra: String = "") = Json.parseToJsonElement(
        """{"id":"${"1".repeat(32)}","pseudo":"F5XYZ","code":"R","age":40,"sd":${now - 120},"lt":${now - 900},"lv":"f",""" +
            """"f":14205000,"m":"USB","updated":40,"role":"m"$extra}""").jsonObject

    private fun with(base: JsonObject, vararg pairs: Pair<String, Any?>): JsonObject = JsonObject(base + pairs.associate { (k, v) ->
        k to when (v) { null -> JsonNull; is Number -> JsonPrimitive(v); is String -> JsonPrimitive(v); else -> JsonPrimitive(v.toString()) }
    }.filterValues { it != JsonNull } - pairs.filter { it.second == null }.map { it.first }.toSet())

    @Test
    fun `memes ages, pseudos et textes libres que la station`() {
        for (c in vectors["format_age"]!!.jsonArray) {
            val o = c.jsonObject
            assertEquals(o["out"]!!.jsonPrimitive.content, Friends.formatAge(o["s"]!!.jsonPrimitive.long))
        }
        for (key in listOf("pseudo", "text")) for (c in vectors[key]!!.jsonArray) {
            val o = c.jsonObject
            val input = o["in"]!!.jsonPrimitive.content
            val out = o["out"]!!.jsonPrimitive.contentOrNull
            assertEquals(out, if (key == "pseudo") Friends.cleanPseudo(input) else Friends.cleanText(input), "$key « $input »")
        }
        assertEquals("42 s", Friends.freshness(42)); assertEquals("2 min", Friends.freshness(125))
    }

    @Test
    fun `memes textes que la page (consentement, niveaux, statuts)`() {
        for (text in Friends.CONSENT + Friends.LEVELS.values + Friends.LABELS.values) assertTrue(page.contains("\"$text\""), text)
    }

    @Test
    fun `un membre - pastille, detail, hors ligne quand la vue vieillit`() {
        val r = Friends.member(member(), now, 0, utc)
        assertEquals(listOf("R", "R", "14,205 MHz USB"), listOf(r.code, r.letter, r.detail)); assertTrue(r.qsy)
        assertTrue("Dernière émission il y a 15 min" in r.lines)
        assertEquals("On Air", Friends.member(with(member(), "code" to "Q", "lv" to "o", "f" to null, "m" to null), now, 0, utc).detail)
        assertEquals("« Test antenne »", Friends.member(with(member(), "code" to "Q", "lv" to "x", "x" to "Test antenne"), now, 0, utc).detail)
        assertEquals("Absent depuis 2 h", Friends.member(with(member(), "code" to "A", "sd" to now - 7200), now, 0, utc).detail)
        assertEquals("Absent", Friends.member(with(member(), "code" to "A", "sd" to null), now, 0, utc).detail)
        assertEquals("Au shack jusqu'à 23:00", Friends.member(with(member(), "code" to "S", "su" to 1_794_006_000L), now, 0, utc).detail)
        val off = Friends.member(with(member(), "code" to "O", "age" to 900), now, 0, utc)
        assertEquals(listOf("", "Hors ligne"), listOf(off.letter, off.detail)); assertFalse(off.qsy)
        assertEquals("O", Friends.member(with(member(), "age" to 230), now, 20, utc).code)
    }

    @Test
    fun `vue par groupe triee, par membre sans doublon, pastilles`() {
        val view = Json.parseToJsonElement("""{"pseudo":"F4ABC","registered":true,"texts":["Mobile"],"groups":[
            {"g":"${"a".repeat(32)}","name":"Club","role":"a","status":"member","members":[
              {"id":"${"1".repeat(32)}","pseudo":"zed","code":"A","age":10},
              {"id":"${"2".repeat(32)}","pseudo":"Bob","code":"Q","age":10},
              {"id":"${"3".repeat(32)}","pseudo":"amy","code":"O","age":999}]},
            {"g":"${"b".repeat(32)}","name":"Mobiles","role":"m","status":"member","members":[
              {"id":"${"2".repeat(32)}","pseudo":"Bob","code":"R","age":10}]}]}""").jsonObject
        val v = Friends.view(view, now, 0, utc)!!
        assertEquals(listOf("Bob", "zed", "amy"), v.groups[0].members.map { it.pseudo })
        assertTrue(v.groups[0].admin); assertFalse(v.groups[1].admin)
        val bob = v.members.first { it.pseudo == "Bob" }
        assertEquals("Q", bob.code); assertEquals(listOf("Club", "Mobiles"), bob.groups)
        val b = Friends.badges(v)
        assertEquals(listOf(2, 1, 3), listOf(b.list.size, b.active, b.total))
        assertNull(Friends.view(null, now, 0))
        assertTrue(Friends.inGroup(FriendsState(view)))
        assertFalse(Friends.inGroup(FriendsState(Json.parseToJsonElement("""{"groups":[]}""").jsonObject)))
        assertFalse(Friends.inGroup(FriendsState())); assertFalse(Friends.inGroup(null))
    }

    @Test
    fun `QSY - refus en emission, confirmation, bande, hors bandes de la station`() {
        val m = Friends.member(member(), now, 0, utc)
        assertEquals("tx_active", Friends.qsyPlan(m, "TX", null).reason)
        assertEquals("no_frequency", Friends.qsyPlan(Friends.member(with(member(), "lv" to "o"), now, 0, utc), "RX", null).reason)
        val same = Friends.qsyPlan(m, "RX", 14_074_000)
        assertEquals("Aller sur 14,205 MHz USB ?", same.text)
        assertTrue(same.warnings.none { it.level == "warn" })
        assertTrue(Friends.qsyPlan(m, "RX", 7_074_000).warnings.any { it.text.startsWith("Changement de bande") })
        val outside = Friends.member(Json.parseToJsonElement(member().toString().dropLast(1) + ""","tx_ok":false}""").jsonObject, now, 0, utc)
        assertTrue(Friends.qsyPlan(outside, "RX", 14_074_000).warnings.any { it.text.endsWith("réception seulement.") })
        assertEquals("https://x/i#abcdefghijklmnopqrst", Friends.cleanInvitation("  https://x/i#abcdefghij\n klmnopqrst "))
        assertNull(Friends.cleanInvitation("court"))
    }

    @Test
    fun `session - vue a la connexion et sur l avis, QSY jamais en emission, point de retour, refus au journal`() {
        val link = FrLink()
        val s = RigSession(link) { 0L }
        s.begin(0, 30); s.answered(0)
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","features":["ptt"]}""")
        assertNull(s.snapshot.friends); assertEquals(0, link.count("friends"))
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","role":"listener","features":["ptt","friends"]}""")
        assertNull(s.snapshot.friends); assertEquals(0, link.count("friends"))
        s.onMessage(0, """{"type":"hello","protocol":1,"client_id":"phone","features":["ptt","friends"]}""")
        s.onMessage(0, """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true,"frequency_hz":7074000,"mode":"PKTUSB"}}""")
        assertEquals(1, link.count("friends", "view"))
        val id = { cmd: String -> link.last(cmd)["id"]!!.jsonPrimitive.content }
        s.onMessage(1, """{"type":"result","id":${id("friends")},"ok":true,"action":"view","data":{"pseudo":"F4ABC","groups":[]}}""")
        assertEquals("F4ABC", (s.snapshot.friends!!.data!!["pseudo"] as JsonPrimitive).content)
        s.onMessage(2, """{"type":"module","module":"presence","data":{"kind":"friends_changed","scope":"operators"}}""")
        assertEquals(2, link.count("friends", "view"))
        s.onMessage(3, """{"type":"result","id":${id("friends")},"ok":false,"reason":"module_absent"}""")
        assertTrue(s.snapshot.friends!!.notice.isNotEmpty()); assertEquals("F4ABC", (s.snapshot.friends!!.data!!["pseudo"] as JsonPrimitive).content)
        // vue relue toutes les 30 s tant qu'elle est affichée
        s.friendsWatch(10, true); assertEquals(3, link.count("friends", "view"))
        val alive = """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true}}"""
        for (t in 1_000L..Friends.REFRESH_MS step 1_000L) s.onMessage(t, alive)        // la station parle : liaison vivante
        s.tick(10 + Friends.REFRESH_MS - 1, true); assertEquals(3, link.count("friends", "view"))
        s.onMessage(10 + Friends.REFRESH_MS, alive)
        s.tick(10 + Friends.REFRESH_MS, true); assertEquals(4, link.count("friends", "view"))
        s.friendsWatch(31_000, false); s.onMessage(31_500, alive); s.tick(31_600, true); assertEquals(4, link.count("friends", "view"))
        // QSY en émission : refusé sans rien envoyer
        s.onMessage(32050, """{"type":"state","ptt":{"state":"TX","owner":"phone"},"rig":{"connected":true}}""")
        s.friendsQsy(32051, 14_205_000, "USB")
        assertEquals(0, link.count("friends", "qsy_mark")); assertEquals(0, link.count("set_frequency"))
        s.onMessage(32052, """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true,"frequency_hz":7074000,"mode":"PKTUSB"}}""")
        s.friendsQsy(32053, 14_205_000, "USB")
        assertEquals(1, link.count("friends", "qsy_mark")); assertEquals(0, link.count("set_frequency"))   // d'abord le point de retour
        s.onMessage(32054, """{"type":"result","id":${id("friends")},"ok":true,"action":"qsy_mark","data":{"back":{"freq":7074000,"mode":"PKTUSB"}}}""")
        assertEquals("USB", link.last("set_mode")["mode"]!!.jsonPrimitive.content)
        assertEquals(14_205_000L, link.last("set_frequency")["hz"]!!.jsonPrimitive.long)
        assertTrue(s.snapshot.friends!!.back)
        s.onMessage(32055, """{"type":"state","ptt":{"state":"RX","owner":null},"rig":{"connected":true,"frequency_hz":14205000,"mode":"USB"}}""")
        s.friendsBack(32056)
        s.onMessage(32057, """{"type":"result","id":${id("friends")},"ok":true,"action":"qsy_back","data":{"back":{"freq":7074000,"mode":"PKTUSB"}}}""")
        assertEquals("PKTUSB", link.last("set_mode")["mode"]!!.jsonPrimitive.content)
        assertEquals(7_074_000L, link.last("set_frequency")["hz"]!!.jsonPrimitive.long)
        assertFalse(s.snapshot.friends!!.back)
        // adhésion : partage choisi au consentement envoyé après l'adhésion
        s.friendsJoin(32060, "https://api.rf-diy.com/i#abc", "Amis", "f")
        assertEquals("join", link.last("friends")["action"]!!.jsonPrimitive.content)
        s.onMessage(32061, """{"type":"result","id":${id("friends")},"ok":true,"action":"join","data":{"g":"${"b".repeat(32)}"}}""")
        val share = link.sent.map { Json.parseToJsonElement(it).jsonObject }.last { (it["action"] as? JsonPrimitive)?.content == "share" }
        assertEquals("f", share["args"]!!.jsonObject["level"]!!.jsonPrimitive.content)
        assertTrue(s.snapshot.friends!!.notice.startsWith("Demande d'adhésion envoyée"))
        // invitation : lien gardé pour être partagé
        s.friendsAction(32070, "invite", JsonObject(mapOf("g" to JsonPrimitive("a".repeat(32)))))
        s.onMessage(32071, """{"type":"result","id":${id("friends")},"ok":true,"action":"invite","data":{"url":"https://api.rf-diy.com/i#xyz","days":7}}""")
        assertEquals("a".repeat(32) to "https://api.rf-diy.com/i#xyz", s.snapshot.friends!!.invite)
        s.friendsDismiss(32072); assertNull(s.snapshot.friends!!.invite)
        assertTrue(link.sent.none { (Json.parseToJsonElement(it).jsonObject["cmd"] as JsonPrimitive).content == "toggle" })   // jamais d'émission
    }
}
