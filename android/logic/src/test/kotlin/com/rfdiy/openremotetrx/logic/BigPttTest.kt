// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
package com.rfdiy.openremotetrx.logic

import com.rfdiy.openremotetrx.protocol.PttStatus
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BigPttTest {
    @Test
    fun `masque par defaut, jamais en conduite ni deconnecte`() {
        assertFalse(BigPtt.visible(requested = false, connected = true, driving = false))
        assertTrue(BigPtt.visible(requested = true, connected = true, driving = false))
        assertFalse(BigPtt.visible(requested = true, connected = true, driving = true))
        assertFalse(BigPtt.visible(requested = true, connected = false, driving = false))
        assertFalse(BigPtt.canShow(connected = true, protocolOk = true, micAllowed = false, driving = false))
        assertFalse(BigPtt.canShow(connected = true, protocolOk = true, micAllowed = true, driving = true))
        assertTrue(BigPtt.canShow(connected = true, protocolOk = true, micAllowed = true, driving = false))
    }

    @Test
    fun `l'aspect suit l'etat publie par la station`() {
        val rx = PttView.of(PttStatus(state = "RX"), "phone")
        assertEquals(BigPtt.Look.READY, BigPtt.look(rx, armed = true, enabled = true))
        assertEquals(BigPtt.Look.DISARMED, BigPtt.look(rx, armed = false, enabled = true))
        assertEquals(BigPtt.Look.OFF, BigPtt.look(rx, armed = true, enabled = false))
        val mine = PttView.of(PttStatus(state = "TX", owner = "phone"), "phone")
        assertEquals(BigPtt.Look.MINE_TX, BigPtt.look(mine, armed = true, enabled = true))
        assertEquals("FIN D'ÉMISSION", BigPtt.caption(BigPtt.Look.MINE_TX))
        val cutting = PttView.of(PttStatus(state = "UNKEYING", owner = "phone"), "phone")
        assertEquals(BigPtt.Look.MINE_TX, BigPtt.look(cutting, armed = true, enabled = true))
        val other = PttView.of(PttStatus(state = "TX", owner = "pc"), "phone")
        assertEquals(BigPtt.Look.OTHER, BigPtt.look(other, armed = true, enabled = false))
    }
}
