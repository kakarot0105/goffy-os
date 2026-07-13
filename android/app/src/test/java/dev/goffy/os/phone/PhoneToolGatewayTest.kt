package dev.goffy.os.phone

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.PermissionLevel
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneToolGatewayTest {
    @Test
    fun emitsTypedVerifiedBatteryStatusWithoutNetwork() = runTest {
        var reads = 0
        val gateway = testGateway {
            reads += 1
            PhoneBatteryStatus(levelPercent = 73, charging = true)
        }

        val events = gateway.invoke(batteryPlan()).toList()

        assertEquals(1, reads)
        assertEquals(6, events.size)
        assertEquals(ExecutionEvent.Starting(1), events[0])
        assertEquals(ExecutionEvent.Ready, events[1])
        assertTrue(events[2] is ExecutionEvent.Progress)
        assertTrue(events[3] is ExecutionEvent.Progress)
        assertEquals(
            PhoneBatteryStatus(levelPercent = 73, charging = true),
            (events[4] as ExecutionEvent.Result).content,
        )
        assertTrue((events[5] as ExecutionEvent.Verification).succeeded)
    }

    @Test
    fun rejectsUnauthorizedPlanBeforeReadingDeviceState() = runTest {
        var read = false
        val gateway = testGateway {
            read = true
            PhoneBatteryStatus(50, false)
        }
        val plan = batteryPlan().copy(permission = PermissionLevel.CONFIRM)

        val events = gateway.invoke(plan).toList()

        assertFalse(read)
        assertEquals("phone_tool_unauthorized", (events.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun invalidOrUnavailableBatteryDataFailsWithoutVerification() = runTest {
        val invalid = testGateway { PhoneBatteryStatus(-1, false) }
        val unavailable = testGateway { error("not supported") }

        val invalidEvents = invalid.invoke(batteryPlan()).toList()
        val unavailableEvents = unavailable.invoke(batteryPlan()).toList()

        assertEquals("invalid_tool_output", (invalidEvents.last() as ExecutionEvent.Error).code)
        assertEquals("phone_tool_failed", (unavailableEvents.last() as ExecutionEvent.Error).code)
        assertTrue(invalidEvents.none { it is ExecutionEvent.Verification })
        assertTrue(unavailableEvents.none { it is ExecutionEvent.Verification })
    }

    @Test
    fun batteryReadTimeoutBecomesAVisibleTerminalError() = runTest {
        val gateway = DefaultPhoneToolGateway(
            batteryStatusSource = { awaitCancellation() },
            readDispatcher = Dispatchers.Unconfined,
            timeoutMillis = 100,
        )

        val events = gateway.invoke(batteryPlan()).toList()

        assertEquals("phone_tool_timeout", (events.last() as ExecutionEvent.Error).code)
        assertTrue(events.none { it is ExecutionEvent.Verification })
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonPositiveTimeout() {
        DefaultPhoneToolGateway(
            batteryStatusSource = { PhoneBatteryStatus(50, false) },
            readDispatcher = Dispatchers.Unconfined,
            timeoutMillis = 0,
        )
    }

    private fun testGateway(read: BatteryStatusSource): DefaultPhoneToolGateway =
        DefaultPhoneToolGateway(
            batteryStatusSource = read,
            readDispatcher = Dispatchers.Unconfined,
        )

    private fun batteryPlan(): GoffyExecutionPlan = GoffyExecutionPlan(
        command = "Show my battery status",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_BATTERY_STATUS_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf("Battery status is validated locally"),
    )
}
