package dev.goffy.os.phone

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.PermissionLevel
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class PhoneToolGatewayTest {
    @Test
    fun emitsTypedVerifiedBatteryStatusWithoutNetwork() = runTest {
        var reads = 0
        var deviceReads = 0
        val gateway = testGateway(
            batteryRead = {
                reads += 1
                PhoneBatteryStatus(levelPercent = 73, charging = true)
            },
            deviceRead = {
                deviceReads += 1
                validDeviceInfo()
            },
        )

        val events = gateway.invoke(batteryPlan()).toList()

        assertEquals(1, reads)
        assertEquals(0, deviceReads)
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
    fun emitsTypedVerifiedDeviceInfoWithoutReadingBattery() = runTest {
        var batteryReads = 0
        var deviceReads = 0
        val gateway = testGateway(
            batteryRead = {
                batteryReads += 1
                PhoneBatteryStatus(50, false)
            },
            deviceRead = {
                deviceReads += 1
                validDeviceInfo()
            },
        )

        val events = gateway.invoke(deviceInfoPlan()).toList()

        assertEquals(0, batteryReads)
        assertEquals(1, deviceReads)
        assertEquals(6, events.size)
        assertEquals(validDeviceInfo(), (events[4] as ExecutionEvent.Result).content)
        val verification = events[5] as ExecutionEvent.Verification
        assertTrue(verification.succeeded)
        assertTrue(verification.checks.contains("approved display fields only"))
    }

    @Test
    fun rejectsUnauthorizedPlanBeforeReadingDeviceState() = runTest {
        var read = false
        val gateway = testGateway(
            batteryRead = {
                read = true
                PhoneBatteryStatus(50, false)
            },
            deviceRead = {
                read = true
                validDeviceInfo()
            },
        )
        val plan = batteryPlan().copy(permission = PermissionLevel.CONFIRM)

        val events = gateway.invoke(plan).toList()

        assertFalse(read)
        assertEquals("phone_tool_unauthorized", (events.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun rejectsUnknownOrWrongTargetToolBeforeReadingEitherSource() = runTest {
        var reads = 0
        val gateway = testGateway(
            batteryRead = {
                reads += 1
                PhoneBatteryStatus(50, false)
            },
            deviceRead = {
                reads += 1
                validDeviceInfo()
            },
        )
        val unknown = deviceInfoPlan().copy(toolName = "phone.device.serial")
        val wrongTarget = deviceInfoPlan().copy(executionTarget = ExecutionTarget.MAC)

        val unknownEvents = gateway.invoke(unknown).toList()
        val wrongTargetEvents = gateway.invoke(wrongTarget).toList()

        assertEquals(0, reads)
        assertEquals("phone_tool_unauthorized", (unknownEvents.single() as ExecutionEvent.Error).code)
        assertEquals("phone_tool_unauthorized", (wrongTargetEvents.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun invalidOrUnavailableBatteryDataFailsWithoutVerification() = runTest {
        val invalid = testGateway(batteryRead = { PhoneBatteryStatus(-1, false) })
        val unavailable = testGateway(batteryRead = { error("not supported") })

        val invalidEvents = invalid.invoke(batteryPlan()).toList()
        val unavailableEvents = unavailable.invoke(batteryPlan()).toList()

        assertEquals("invalid_tool_output", (invalidEvents.last() as ExecutionEvent.Error).code)
        assertEquals("phone_tool_failed", (unavailableEvents.last() as ExecutionEvent.Error).code)
        assertTrue(invalidEvents.none { it is ExecutionEvent.Verification })
        assertTrue(unavailableEvents.none { it is ExecutionEvent.Verification })
    }

    @Test
    fun invalidOrUnavailableDeviceInfoFailsWithoutVerification() = runTest {
        val invalidValues = listOf(
            PhoneDeviceInfo("", "moto g", "15", 35),
            PhoneDeviceInfo("motorola", "moto\ng", "15", 35),
            PhoneDeviceInfo("motorola", "moto\u202Eg", "15", 35),
            PhoneDeviceInfo("motorola", "moto g", "15", 25),
            PhoneDeviceInfo("motorola", "moto g", "15", Int.MAX_VALUE),
            PhoneDeviceInfo("m".repeat(129), "moto g", "15", 35),
        )

        invalidValues.forEach { invalid ->
            val events = testGateway(deviceRead = { invalid }).invoke(deviceInfoPlan()).toList()
            assertEquals("invalid_tool_output", (events.last() as ExecutionEvent.Error).code)
            assertTrue(events.none { it is ExecutionEvent.Verification })
        }

        val unavailable = testGateway(deviceRead = { error("not supported") })
            .invoke(deviceInfoPlan())
            .toList()
        assertEquals("phone_tool_failed", (unavailable.last() as ExecutionEvent.Error).code)
        assertTrue(unavailable.none { it is ExecutionEvent.Verification })
    }

    @Test
    fun batteryReadTimeoutBecomesAVisibleTerminalError() = runTest {
        val gateway = DefaultPhoneToolGateway(
            batteryStatusSource = { awaitCancellation() },
            deviceInfoSource = { validDeviceInfo() },
            readDispatcher = Dispatchers.Unconfined,
            timeoutMillis = 100,
        )

        val events = gateway.invoke(batteryPlan()).toList()

        assertEquals("phone_tool_timeout", (events.last() as ExecutionEvent.Error).code)
        assertTrue(events.none { it is ExecutionEvent.Verification })
    }

    @Test
    fun callerCancellationStopsTheSelectedLocalSource() = runTest {
        var sourceCancelled = false
        val gateway = testGateway(
            deviceRead = {
                try {
                    awaitCancellation()
                } finally {
                    sourceCancelled = true
                }
            },
        )

        val collection = launch { gateway.invoke(deviceInfoPlan()).toList() }
        runCurrent()
        collection.cancelAndJoin()

        assertTrue(sourceCancelled)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonPositiveTimeout() {
        DefaultPhoneToolGateway(
            batteryStatusSource = { PhoneBatteryStatus(50, false) },
            deviceInfoSource = { validDeviceInfo() },
            readDispatcher = Dispatchers.Unconfined,
            timeoutMillis = 0,
        )
    }

    private fun testGateway(
        batteryRead: BatteryStatusSource = BatteryStatusSource { PhoneBatteryStatus(50, false) },
        deviceRead: DeviceInfoSource = DeviceInfoSource { validDeviceInfo() },
    ): DefaultPhoneToolGateway =
        DefaultPhoneToolGateway(
            batteryStatusSource = batteryRead,
            deviceInfoSource = deviceRead,
            readDispatcher = Dispatchers.Unconfined,
        )

    private fun batteryPlan(): GoffyExecutionPlan = GoffyExecutionPlan(
        command = "Show my battery status",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_BATTERY_STATUS_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf("Battery status is validated locally"),
    )

    private fun deviceInfoPlan(): GoffyExecutionPlan = GoffyExecutionPlan(
        command = "Show my phone info",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_DEVICE_INFO_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf("Device info is validated locally"),
    )

    private fun validDeviceInfo(): PhoneDeviceInfo = PhoneDeviceInfo(
        manufacturer = "motorola",
        model = "moto g",
        androidRelease = "15",
        sdkInt = 35,
    )
}
