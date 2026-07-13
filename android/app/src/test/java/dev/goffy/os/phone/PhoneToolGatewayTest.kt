package dev.goffy.os.phone

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.PermissionLevel
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.ANDROID_SET_TIMER_ACTION
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import java.util.UUID
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
    private val taskId = UUID.fromString("11111111-1111-4111-8111-111111111111")

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

        val events = gateway.invokeSafe(batteryPlan()).toList()

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

        val events = gateway.invokeSafe(deviceInfoPlan()).toList()

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

        val events = gateway.invokeSafe(plan).toList()

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

        val unknownEvents = gateway.invokeSafe(unknown).toList()
        val wrongTargetEvents = gateway.invokeSafe(wrongTarget).toList()

        assertEquals(0, reads)
        assertEquals("phone_tool_unauthorized", (unknownEvents.single() as ExecutionEvent.Error).code)
        assertEquals("phone_tool_unauthorized", (wrongTargetEvents.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun invalidOrUnavailableBatteryDataFailsWithoutVerification() = runTest {
        val invalid = testGateway(batteryRead = { PhoneBatteryStatus(-1, false) })
        val unavailable = testGateway(batteryRead = { error("not supported") })

        val invalidEvents = invalid.invokeSafe(batteryPlan()).toList()
        val unavailableEvents = unavailable.invokeSafe(batteryPlan()).toList()

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
            val events = testGateway(deviceRead = { invalid }).invokeSafe(deviceInfoPlan()).toList()
            assertEquals("invalid_tool_output", (events.last() as ExecutionEvent.Error).code)
            assertTrue(events.none { it is ExecutionEvent.Verification })
        }

        val unavailable = testGateway(deviceRead = { error("not supported") })
            .invokeSafe(deviceInfoPlan())
            .toList()
        assertEquals("phone_tool_failed", (unavailable.last() as ExecutionEvent.Error).code)
        assertTrue(unavailable.none { it is ExecutionEvent.Verification })
    }

    @Test
    fun batteryReadTimeoutBecomesAVisibleTerminalError() = runTest {
        val gateway = DefaultPhoneToolGateway(
            batteryStatusSource = { awaitCancellation() },
            deviceInfoSource = { validDeviceInfo() },
            noteStore = fakeNoteStore(),
            timerSource = fakeTimerSource(),
            readDispatcher = Dispatchers.Unconfined,
            actionDispatcher = Dispatchers.Unconfined,
            timeoutMillis = 100,
        )

        val events = gateway.invokeSafe(batteryPlan()).toList()

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

        val collection = launch { gateway.invokeSafe(deviceInfoPlan()).toList() }
        runCurrent()
        collection.cancelAndJoin()

        assertTrue(sourceCancelled)
    }

    @Test
    fun noteCreationRequiresExactSingleUseApprovalAndVerifiesStoredText() = runTest {
        val noteStore = RecordingNoteStore()
        val gateway = testGateway(noteStore = noteStore)
        val plan = notePlan("Buy milk")

        val safeEvents = gateway.invoke(taskId, plan, PhoneToolAuthorization.Safe).toList()
        assertEquals("phone_tool_unauthorized", (safeEvents.single() as ExecutionEvent.Error).code)
        assertEquals(0, noteStore.creates)

        val approval = approval(plan)
        val independentlyMintedReplay = approval(plan)
        val approvedEvents = gateway.invoke(taskId, plan, approval).toList()
        val replayEvents = gateway.invoke(taskId, plan, independentlyMintedReplay).toList()

        assertEquals(1, noteStore.creates)
        assertEquals("Buy milk", noteStore.lastText)
        assertEquals(PhoneNoteCreated(1, "Buy milk", 1_720_000_000_000), (approvedEvents[4] as ExecutionEvent.Result).content)
        assertTrue((approvedEvents.last() as ExecutionEvent.Verification).succeeded)
        assertEquals("phone_tool_unauthorized", (replayEvents.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun staleOrWrongToolApprovalCannotReachTheNoteStore() = runTest {
        val noteStore = RecordingNoteStore()
        val gateway = testGateway(noteStore = noteStore)
        val plan = notePlan("Buy milk")
        val otherTask = UUID.fromString("22222222-2222-4222-8222-222222222222")

        val stale = gateway.invoke(
            taskId,
            plan,
            approval(plan, approvedTaskId = otherTask),
        ).toList()
        val wrongTool = gateway.invoke(
            taskId,
            plan,
            approval(plan, approvedToolName = PHONE_DEVICE_INFO_TOOL),
        ).toList()

        assertEquals(0, noteStore.creates)
        assertEquals("phone_tool_unauthorized", (stale.single() as ExecutionEvent.Error).code)
        assertEquals("phone_tool_unauthorized", (wrongTool.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun mismatchedPostWriteResultFailsWithoutClaimingVerification() = runTest {
        val noteStore = RecordingNoteStore { text ->
            PhoneNoteCreated(1, "$text changed", 1_720_000_000_000)
        }
        val gateway = testGateway(noteStore = noteStore)
        val plan = notePlan("Buy milk")

        val events = gateway.invoke(
            taskId,
            plan,
            approval(plan),
        ).toList()

        assertEquals(1, noteStore.creates)
        assertEquals("invalid_tool_output", (events.last() as ExecutionEvent.Error).code)
        assertTrue(events.none { it is ExecutionEvent.Verification })
    }

    @Test
    fun approvalBindsExactArgumentsAndExpiresAtTheGatewayBoundary() = runTest {
        var now = 100L
        val noteStore = RecordingNoteStore()
        val gateway = testGateway(noteStore = noteStore, nowMillis = { now })
        val alpha = notePlan("alpha")
        val beta = notePlan("beta")

        val changedArguments = gateway.invoke(taskId, beta, approval(alpha, expiresAt = 200)).toList()
        now = 200L
        val expired = gateway.invoke(
            UUID.fromString("33333333-3333-4333-8333-333333333333"),
            alpha,
            approval(
                alpha,
                approvedTaskId = UUID.fromString("33333333-3333-4333-8333-333333333333"),
                expiresAt = 200,
            ),
        ).toList()

        assertEquals(0, noteStore.creates)
        assertEquals("phone_tool_unauthorized", (changedArguments.single() as ExecutionEvent.Error).code)
        assertEquals("phone_tool_unauthorized", (expired.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun timerDispatchRequiresApprovalAndValidatesTheExactDuration() = runTest {
        var dispatches = 0
        var dispatchedSeconds: Int? = null
        val timerSource = TimerSource { arguments ->
            dispatches += 1
            dispatchedSeconds = arguments.durationSeconds
            validTimerResult(arguments.durationSeconds)
        }
        val gateway = testGateway(timerSource = timerSource)
        val plan = timerPlan(300)

        val safeEvents = gateway.invoke(taskId, plan, PhoneToolAuthorization.Safe).toList()
        val approvedEvents = gateway.invoke(taskId, plan, approval(plan)).toList()
        val replayEvents = gateway.invoke(taskId, plan, approval(plan)).toList()

        assertEquals("phone_tool_unauthorized", (safeEvents.single() as ExecutionEvent.Error).code)
        assertEquals(1, dispatches)
        assertEquals(300, dispatchedSeconds)
        assertEquals(
            validTimerResult(300),
            (approvedEvents[4] as ExecutionEvent.Result).content,
        )
        val unverified = approvedEvents.last() as ExecutionEvent.Unverified
        assertTrue(unverified.summary.contains("not readable"))
        assertEquals("phone_tool_unauthorized", (replayEvents.single() as ExecutionEvent.Error).code)
    }

    @Test
    fun unavailableOrMismatchedTimerHandlerNeverClaimsVerification() = runTest {
        val unavailable = testGateway(
            timerSource = TimerSource { error("no allowlisted Clock") },
        )
        val mismatch = testGateway(
            timerSource = TimerSource { arguments ->
                validTimerResult(arguments.durationSeconds + 1)
            },
        )

        val unavailableEvents = unavailable.invoke(taskId, timerPlan(60), approval(timerPlan(60))).toList()
        val mismatchTask = UUID.fromString("44444444-4444-4444-8444-444444444444")
        val mismatchPlan = timerPlan(60)
        val mismatchEvents = mismatch.invoke(
            mismatchTask,
            mismatchPlan,
            approval(mismatchPlan, approvedTaskId = mismatchTask),
        ).toList()

        assertEquals("phone_tool_failed", (unavailableEvents.last() as ExecutionEvent.Error).code)
        assertEquals("invalid_tool_output", (mismatchEvents.last() as ExecutionEvent.Error).code)
        assertTrue(unavailableEvents.none { it is ExecutionEvent.Verification || it is ExecutionEvent.Unverified })
        assertTrue(mismatchEvents.none { it is ExecutionEvent.Verification || it is ExecutionEvent.Unverified })
    }

    @Test
    fun timerApprovalRejectsChangedDurationWrongTaskToolAndExpiry() = runTest {
        var now = 100L
        var dispatches = 0
        val timerSource = TimerSource { arguments ->
            dispatches += 1
            validTimerResult(arguments.durationSeconds)
        }
        val gateway = testGateway(timerSource = timerSource, nowMillis = { now })
        val approvedPlan = timerPlan(300)
        val changedDuration = gateway.invoke(
            taskId,
            timerPlan(60),
            approval(approvedPlan),
        ).toList()
        val wrongTask = gateway.invoke(
            taskId,
            approvedPlan,
            approval(approvedPlan, approvedTaskId = UUID.randomUUID()),
        ).toList()
        val wrongTool = gateway.invoke(
            taskId,
            approvedPlan,
            approval(approvedPlan, approvedToolName = PHONE_NOTE_CREATE_TOOL),
        ).toList()
        now = 200L
        val expired = gateway.invoke(
            taskId,
            approvedPlan,
            approval(approvedPlan, expiresAt = 200L),
        ).toList()

        assertEquals(0, dispatches)
        listOf(changedDuration, wrongTask, wrongTool, expired).forEach { events ->
            assertEquals("phone_tool_unauthorized", (events.single() as ExecutionEvent.Error).code)
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonPositiveTimeout() {
        DefaultPhoneToolGateway(
            batteryStatusSource = { PhoneBatteryStatus(50, false) },
            deviceInfoSource = { validDeviceInfo() },
            noteStore = fakeNoteStore(),
            timerSource = fakeTimerSource(),
            readDispatcher = Dispatchers.Unconfined,
            actionDispatcher = Dispatchers.Unconfined,
            timeoutMillis = 0,
        )
    }

    private fun testGateway(
        batteryRead: BatteryStatusSource = BatteryStatusSource { PhoneBatteryStatus(50, false) },
        deviceRead: DeviceInfoSource = DeviceInfoSource { validDeviceInfo() },
        noteStore: NoteStore = fakeNoteStore(),
        timerSource: TimerSource = fakeTimerSource(),
        nowMillis: () -> Long = { 100L },
    ): DefaultPhoneToolGateway =
        DefaultPhoneToolGateway(
            batteryStatusSource = batteryRead,
            deviceInfoSource = deviceRead,
            noteStore = noteStore,
            timerSource = timerSource,
            readDispatcher = Dispatchers.Unconfined,
            actionDispatcher = Dispatchers.Unconfined,
            nowMillis = nowMillis,
        )

    private fun PhoneToolGateway.invokeSafe(plan: GoffyExecutionPlan) =
        invoke(taskId, plan, PhoneToolAuthorization.Safe)

    private fun fakeNoteStore(): NoteStore = object : NoteStore {
        override suspend fun create(text: String): PhoneNoteCreated =
            PhoneNoteCreated(1, text, 1)

        override fun close() = Unit
    }

    private fun fakeTimerSource(): TimerSource = TimerSource { arguments ->
        validTimerResult(arguments.durationSeconds)
    }

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

    private fun notePlan(text: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = "Create a note saying $text",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_NOTE_CREATE_TOOL,
        permission = PermissionLevel.CONFIRM,
        successCriteria = listOf("Stored note is re-read"),
        arguments = PhoneNoteCreateArguments(text),
    )

    private fun timerPlan(durationSeconds: Int): GoffyExecutionPlan = GoffyExecutionPlan(
        command = "Set a timer for $durationSeconds seconds",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_TIMER_CREATE_TOOL,
        permission = PermissionLevel.CONFIRM,
        successCriteria = listOf("System Clock dispatch is accepted"),
        arguments = PhoneTimerCreateArguments(durationSeconds, skipClockUi = true),
    )

    private fun approval(
        plan: GoffyExecutionPlan,
        approvedTaskId: UUID = taskId,
        approvedToolName: String = plan.toolName,
        expiresAt: Long = 200L,
    ): PhoneToolAuthorization.Approved = PhoneToolAuthorization.Approved(
        approvedTaskId,
        approvedToolName,
        plan.arguments,
        expiresAt,
    )

    private fun validDeviceInfo(): PhoneDeviceInfo = PhoneDeviceInfo(
        manufacturer = "motorola",
        model = "moto g",
        androidRelease = "15",
        sdkInt = 35,
    )

    private fun validTimerResult(durationSeconds: Int): PhoneTimerDispatched = PhoneTimerDispatched(
        durationSeconds,
        "com.google.android.deskclock",
        "com.google.android.deskclock.TimerActivity",
        true,
        true,
        ANDROID_SET_TIMER_ACTION,
    )

    private class RecordingNoteStore(
        private val result: (String) -> PhoneNoteCreated = { text ->
            PhoneNoteCreated(1, text, 1_720_000_000_000)
        },
    ) : NoteStore {
        var creates = 0
        var lastText: String? = null

        override suspend fun create(text: String): PhoneNoteCreated {
            creates += 1
            lastText = text
            return result(text)
        }

        override fun close() = Unit
    }
}
