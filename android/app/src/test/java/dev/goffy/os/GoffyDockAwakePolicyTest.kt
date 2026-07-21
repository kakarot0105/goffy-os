package dev.goffy.os

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyDockAwakePolicyTest {
    @Test
    fun keepAwakeOnlyWhileEnabledAndCharging() {
        assertEquals(
            DockAwakeStatus.AWAKE,
            GoffyDockAwakePolicy.status(enabled = true, charging = true),
        )
        assertTrue(GoffyDockAwakePolicy.shouldKeepScreenAwake(enabled = true, charging = true))

        assertEquals(
            DockAwakeStatus.WAITING_FOR_POWER,
            GoffyDockAwakePolicy.status(enabled = true, charging = false),
        )
        assertFalse(GoffyDockAwakePolicy.shouldKeepScreenAwake(enabled = true, charging = false))

        assertEquals(
            DockAwakeStatus.DISABLED,
            GoffyDockAwakePolicy.status(enabled = false, charging = true),
        )
        assertFalse(GoffyDockAwakePolicy.shouldKeepScreenAwake(enabled = false, charging = true))
    }
}
