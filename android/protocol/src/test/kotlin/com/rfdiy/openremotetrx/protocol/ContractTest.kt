// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.protocol

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.fail
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/**
 * Contrat avec la station : les exemples de tests/protocol/ (validés par pytest contre le vrai code de la station)
 * sont produits À L'IDENTIQUE par les commandes de l'application, et ses messages d'exemple se décodent.
 */
class ContractTest {
    private val folder = File(System.getProperty("trx.repo") ?: "../..", "tests/protocol")
    private fun load(name: String): JsonObject = Json.parseToJsonElement(File(folder, name).readText(Charsets.UTF_8)).jsonObject
    private val commands = load("commands.json")["commands"]!!.jsonObject
    private val messages = load("messages.json")

    @Test
    fun `l'application connait exactement les commandes de la station`() {
        assertEquals(commands.keys, Command.NAMES)
    }

    @Test
    fun `chaque exemple valide est reproduit a l'identique par la commande de l'application`() {
        for ((name, case) in commands) {
            for (example in case.jsonObject["valid"]!!.jsonArray) {
                val expected = example.jsonObject
                val id = expected["id"]?.jsonPrimitive?.intOrNull
                val built = fromExample(name, expected).toJson(id)
                assertEquals(expected, built, "commande $name")
                assertEquals("cmd", built.keys.first(), "« cmd » doit venir en premier")
            }
        }
    }

    @Test
    fun `hello d'exemple`() {
        val hello = assertIs<Hello>(ServerMessages.decode(messages["hello"].toString()))
        assertEquals(Protocol.VERSION, hello.protocol)
        assertEquals("IC-7300MK2", hello.capabilities?.modelName)
        assertEquals(listOf(3000, 2400, 1800), hello.capabilities?.filters?.get("USB"))
        assertTrue(hello.offers("memories") && hello.offers("ptt"))
        assertTrue((Protocol.BASE_FEATURES + Protocol.OPTIONAL_FEATURES).containsAll(hello.features))
        assertEquals("a1b2c3", hello.memories.single().id)
        assertEquals(10, hello.spectrum?.maxFps)
    }

    @Test
    fun `state d'exemple`() {
        val state = assertIs<State>(ServerMessages.decode(messages["state"].toString()))
        assertEquals("TX", state.ptt.state)
        assertEquals("phone", state.ptt.owner)
        assertEquals(74.6, state.ptt.totRemainingS)
        assertNull(state.ptt.localRemainingS)
        assertEquals(14_074_000L, state.rig.frequencyHz)
        assertEquals(true, state.rig.functions["NB"])
        assertEquals(10.0, state.rig.levels["PREAMP"])
    }

    @Test
    fun `reponses, erreurs et diffusions d'exemple`() {
        val results = messages["result"]!!.jsonArray.map { ServerMessages.decode(it.toString()) as Result }
        assertTrue(results[0].ok); assertEquals("KEYING", results[0].ptt?.state)
        assertEquals("local_active", results[1].reason); assertTrue(!results[1].ok)
        val error = assertIs<ErrorMessage>(ServerMessages.decode(messages["error"]!!.jsonArray[0].toString()))
        assertEquals("unknown_command", error.code)
        assertEquals("FT8 20 m", assertIs<Memories>(ServerMessages.decode(messages["memories"].toString())).items.single().name)
        assertIs<Beeps>(ServerMessages.decode(messages["beeps"].toString()))
        assertIs<Selcall>(ServerMessages.decode(messages["selcall"].toString()))
        assertEquals("cluster", assertIs<ModuleMessage>(ServerMessages.decode(messages["module"].toString())).module)
    }

    @Test
    fun `une station plus recente ne casse rien`() {
        assertIs<Unknown>(ServerMessages.decode("""{"type":"nouveau","x":1}"""))
        val state = assertIs<State>(ServerMessages.decode("""{"type":"state","ptt":{"state":"RX","inconnu":3},"futur":true}"""))
        assertEquals("RX", state.ptt.state)
        try {
            ServerMessages.decode("[1,2]"); fail("un tableau n'est pas un message")
        } catch (_: ProtocolException) {
        }
    }

    /** Construit la commande de l'application qui correspond à un exemple (les paramètres sont relus de l'exemple). */
    private fun fromExample(name: String, e: JsonObject): Command {
        fun p(key: String) = e[key]!!.jsonPrimitive
        return when (name) {
            "toggle" -> Command.Toggle
            "stop" -> Command.Stop
            "heartbeat" -> Command.Heartbeat
            "get_state" -> Command.GetState
            "local_release" -> Command.LocalRelease
            "layout_get" -> Command.LayoutGet
            "layout_reset" -> Command.LayoutReset
            "set_frequency" -> Command.SetFrequency(p("hz").long)
            "set_mode" -> Command.SetMode(p("mode").content, e["passband"]?.jsonPrimitive?.int ?: 0)
            "set_squelch" -> Command.SetSquelch(p("value").content.toDouble())
            "set_function" -> Command.SetFunction(p("name").content, p("on").boolean)
            "set_level" -> Command.SetLevel(p("name").content, p("value").let { it.intOrNull ?: it.content.toDouble() })
            "memory_save" -> Command.MemorySave(p("name").content, p("hz").long, p("mode").content,
                e["favorite"]?.jsonPrimitive?.boolean ?: false, e["memory_id"]?.jsonPrimitive?.content)
            "memory_delete" -> Command.MemoryDelete(p("memory_id").content)
            "memory_recall" -> Command.MemoryRecall(p("memory_id").content)
            "layout_save" -> Command.LayoutSave(e["profile"]!!.jsonObject)
            "spectrum_set" -> Command.SpectrumSet(p("name").content, p("value"))
            "spectrum_watch" -> Command.SpectrumWatch(p("on").boolean)
            "beeps_set" -> Command.BeepsSet(e.filterKeys { it != "cmd" && it != "id" }.mapValues { it.value.jsonPrimitive })
            "bug_report" -> Command.BugReport(p("text").content)
            "set_offset" -> Command.SetOffset(p("name").content, p("hz").int)
            "selcall_activate" -> Command.SelcallActivate(p("code").content)
            "selcall_rearm" -> Command.SelcallRearm
            "selcall_deactivate" -> Command.SelcallDeactivate
            "selcall_options" -> Command.SelcallOptions(e["filter_mode"]?.jsonPrimitive?.content, e["attenuation_db"]?.jsonPrimitive?.int,
                e["send_on_tx_end"]?.jsonPrimitive?.boolean)
            "selcall_send" -> Command.SelcallSend
            else -> fail("commande sans équivalent dans l'application : $name")
        }
    }
}
