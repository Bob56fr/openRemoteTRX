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
import kotlinx.serialization.json.double
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
        assertEquals(0.487, state.host?.load)                                       // santé de la machine (0.83.0+)
        assertEquals("ok", state.host?.level)
        assertEquals(46, state.host?.tempC)
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
        assertEquals("operator_absent", assertIs<Bye>(ServerMessages.decode(messages["bye"].toString())).reason)
    }

    @Test
    fun `visiteurs - role, pseudo et presence de l exemple`() {
        val hello = assertIs<Hello>(ServerMessages.decode(messages["hello"].toString()))
        assertEquals("operator", hello.role); assertEquals("Kriss F4ABC", hello.pseudo); assertTrue(!hello.listener)
        val presence = assertIs<State>(ServerMessages.decode(messages["state"].toString())).presence!!
        assertEquals(2, presence.listeners); assertEquals(true, presence.open)
        assertEquals(2, presence.people[1].count); assertEquals("club1", presence.connections[1].id)
        val old = assertIs<State>(ServerMessages.decode("""{"type":"state","ptt":{"state":"RX"}}"""))
        assertNull(old.presence)                                         // station d'avant 0.71.0
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
    @Test
    fun `Breizh - etat et evenement d exemple`() {
        val wrapped = buildString {
            append("{\"type\":\"state\",\"breizh\":"); append(messages["state_breizh"]!!.jsonObject["breizh"].toString()); append("}")
        }
        val b = assertIs<State>(ServerMessages.decode(wrapped)).breizh!!
        assertEquals("ready", b.state); assertEquals("breizh", b.route); assertEquals(3, b.rttMs); assertEquals("Breizh 2.1.0", b.peer)
        assertNull(b.reactivateInS)
        assertNull(assertIs<State>(ServerMessages.decode(messages["state"].toString())).breizh)    // station sans Breizh
        val e = assertIs<BreizhEvent>(ServerMessages.decode(messages["breizh_event"].toString()))
        assertEquals("fallback", e.event); assertTrue(e.detail.startsWith("Breizh ne répond plus"))
    }

    @Test
    fun `FreeDV - etat, hello, evenements et reponses d exemple`() {
        val wrapped = "{\"type\":\"state\",\"freedv\":" + messages["state_freedv"]!!.jsonObject["freedv"].toString() + "}"
        val f = assertIs<State>(ServerMessages.decode(wrapped)).freedv!!
        assertEquals(true, f.on); assertEquals("ecoute", f.engine); assertEquals("sync", f.sync); assertTrue(f.confirmed)
        assertEquals(7.5, f.snrDb); assertNull(f.fault); assertEquals("W6GOK", f.calls.single().callsign)
        assertEquals(5.0, f.sequences.single().note); assertEquals(listOf("W6GOK"), f.sequences.single().callsigns)
        assertNull(assertIs<State>(ServerMessages.decode(messages["state"].toString())).freedv)      // station sans FreeDV
        val hello = assertIs<Hello>(ServerMessages.decode(messages["hello"].toString())).freedv!!
        assertEquals(false, hello.on); assertEquals("arret", hello.engine); assertNull(hello.snrDb)
        val events = messages["freedv_event"]!!.jsonArray.map { assertIs<FreedvEvent>(ServerMessages.decode(it.toString())) }
        assertEquals(listOf("callsign", "sequence", "fault"), events.map { it.kind })
        assertEquals("W6GOK", events[0].callsign); assertEquals(9.0, events[0].snrDb); assertTrue(events[2].cause.startsWith("radae_rx"))
        val results = messages["freedv_set_result"]!!.jsonArray.map { assertIs<Result>(ServerMessages.decode(it.toString())) }
        assertTrue(results[0].ok); assertEquals(listOf("freedv_tx", "freedv_missing"), results.drop(1).map { it.reason })
    }

    @Test
    fun `Activite FreeDV - message de module d exemple`() {
        val msg = assertIs<ModuleMessage>(ServerMessages.decode(messages["module_freedv_activity"].toString()))
        assertEquals("freedv_activity", msg.module)
        val a = FreedvActivity.of(msg.data)!!
        assertEquals("ok", a.status); assertEquals(61, a.total); assertTrue(a.locator); assertEquals(1794338400.0, a.t)
        assertEquals(listOf(7196000L, 14236000L), a.freqs.map { it.f })
        val tx = a.freqs[0].tx
        assertEquals("DL2GRF", tx[0].c); assertEquals(839, tx[0].km); assertTrue(tx[0].on); assertNull(tx[0].min); assertEquals("RADEV1", tx[0].m)
        assertEquals(1, tx[1].min); assertEquals(8.0, a.freqs[0].rx.single().snr); assertEquals(28.0, a.freqs[0].note)
        assertNull(FreedvActivity.of(messages["module"]!!.jsonObject["data"]))                   // autre module : rien
    }

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
                e["send_on_tx_end"]?.jsonPrimitive?.boolean, e["tx_level_dbfs"]?.jsonPrimitive?.content?.toDouble())
            "selcall_send" -> Command.SelcallSend
            "selcall_calibrate" -> Command.SelcallCalibrate
            "listener_kick" -> Command.ListenerKick(p("account").content)
            "listeners_reopen" -> Command.ListenersReopen
            "host_info" -> Command.HostInfo
            "voice_profiles" -> Command.VoiceProfiles
            "voice_profile_save" -> Command.VoiceProfileSave(p("name").content, e["settings"]!!.jsonObject)
            "voice_profile_delete" -> Command.VoiceProfileDelete(p("name").content)
            "swr_plan" -> Command.SwrPlan(p("low_hz").long, p("high_hz").long, p("points").int, p("power_pct").double)
            "swr_start" -> Command.SwrStart(p("low_hz").long, p("high_hz").long, p("points").int, p("power_pct").double)
            "swr_cancel" -> Command.SwrCancel
            "swr_last" -> Command.SwrLast
            "listeners_open" -> Command.ListenersOpen(p("on").boolean)
            "freedv_set" -> Command.FreedvSet(p("on").boolean)
            "breizh_set" -> Command.BreizhSet(e["return_gain_db"]?.jsonPrimitive?.double,
                                              e["bypass"]?.jsonPrimitive?.boolean)
            "breizh_reactivate" -> Command.BreizhReactivate
            "breizh_log" -> Command.BreizhLog
            "net_ping" -> Command.NetPing(p("seq").int, p("t").long, e["w"]?.jsonPrimitive?.long)
            "net_pong" -> Command.NetPong(p("seq").int, p("t").long, p("tr").long)
            "net_report" -> Command.NetReport(e["report"]!!.jsonObject)
            "net_backlog" -> Command.NetBacklog(e["reports"]!!.jsonArray)
            "net_stats" -> Command.NetStats(e["days"]?.jsonPrimitive?.int ?: 30, e["device"]?.jsonPrimitive?.content)
            "net_clear" -> Command.NetClear
            "net_thresholds" -> {
                fun n(key: String): Number? = e[key]?.jsonPrimitive?.let { it.intOrNull ?: it.double }
                Command.NetThresholds(p("net_type").content, n("rtt_warn"), n("rtt_alert"), n("loss_warn"), n("loss_alert"),
                                      e["reset"]?.jsonPrimitive?.boolean ?: false)
            }
            "net_vpn_ignore" -> Command.NetVpnIgnore(p("address").content)
            "net_export" -> Command.NetExport(p("part").int)
            "friends" -> Command.Friends(p("action").content, e["args"]?.jsonObject)
            else -> fail("commande sans équivalent dans l'application : $name")
        }
    }
}
