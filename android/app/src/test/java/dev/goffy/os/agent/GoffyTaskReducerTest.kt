package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.ToolProgress
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyTaskReducerTest {
    private val taskId = UUID.fromString("11111111-1111-4111-8111-111111111111")
    private val phoneTaskId = UUID.fromString("22222222-2222-4222-8222-222222222222")
    private val plan = (GoffyIntentRouter.route("Show my Mac status") as RoutingDecision.Routed).plan
    private val phonePlan = GoffyExecutionPlan(
        command = "What's my phone battery level?",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_BATTERY_STATUS_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf("Battery status matches the typed local contract"),
    )

    @Test
    fun macExecutionRequiresVerificationAfterTypedResultBeforeSuccess() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, ExecutionEvent.Starting(1))
        assertEquals("Starting MAC Hub connection", state.entries.single().summary)
        state = state.apply(taskId, ExecutionEvent.Ready)
        assertEquals("MAC Hub ready; invocation sent", state.entries.single().summary)
        state = state.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "accepted", 0))
        state = state.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "completed", 1))
        state = state.apply(
            taskId,
            ExecutionEvent.Result(
                "mac.system_info",
                ExecutionTarget.MAC,
                MacSystemInfo("available", "Darwin", "arm64"),
            ),
        )

        assertEquals(TaskPhase.COMPLETED_UNVERIFIED, state.entries.single().phase)
        assertEquals("Darwin arm64: available", state.entries.single().summary)
        assertEquals(taskId, state.activeTaskId)

        state = state.apply(
            taskId,
            ExecutionEvent.Verification(true, "Schema verified", listOf("output schema")),
        )

        assertEquals(TaskPhase.VERIFIED, state.entries.single().phase)
        assertNull(state.activeTaskId)
        assertEquals("Darwin", (state.entries.single().result as MacSystemInfo).operatingSystem)
    }

    @Test
    fun verificationBeforeResultFailsClosed() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, ExecutionEvent.Verification(true, "claimed", emptyList()))

        assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        assertNull(state.activeTaskId)
    }

    @Test
    fun duplicateOrOutOfOrderProgressFailsClosed() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "accepted", 1))
        state = state.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "completed", 1))

        assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        assertNull(state.activeTaskId)
    }

    @Test
    fun skippedOrUnexpectedProgressStageFailsClosed() {
        var skipped = TaskTimelineState().start(taskId, plan)
        skipped = skipped.apply(taskId, ExecutionEvent.Starting(1))
        skipped = skipped.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "accepted", 1))
        assertEquals(TaskPhase.FAILED, skipped.entries.single().phase)

        var unexpected = TaskTimelineState().start(taskId, plan)
        unexpected = unexpected.apply(taskId, ExecutionEvent.Starting(1))
        unexpected = unexpected.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "completed", 0))
        assertEquals(TaskPhase.FAILED, unexpected.entries.single().phase)
    }

    @Test
    fun duplicateResultFailsClosedInsteadOfOverwritingData() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, ExecutionEvent.Starting(1))
        state = state.apply(taskId, ExecutionEvent.Ready)
        state = state.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "accepted", 0))
        state = state.apply(taskId, progress(plan.toolName, ExecutionTarget.MAC, "completed", 1))
        state = state.apply(taskId, macResult("Darwin"))
        state = state.apply(taskId, macResult("forged"))

        assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        assertEquals("Darwin", (state.entries.single().result as MacSystemInfo).operatingSystem)
        assertNull(state.activeTaskId)
    }

    @Test
    fun phoneExecutionUsesTargetAwareSummariesAndTypedBatteryResult() {
        var state = TaskTimelineState().start(phoneTaskId, phonePlan)
        state = state.apply(phoneTaskId, ExecutionEvent.Starting(1))
        assertEquals("Starting local PHONE execution", state.entries.single().summary)
        state = state.apply(phoneTaskId, ExecutionEvent.Ready)
        assertEquals("PHONE local execution ready", state.entries.single().summary)
        state = state.apply(phoneTaskId, progress(phonePlan.toolName, ExecutionTarget.PHONE, "accepted", 0))
        state = state.apply(phoneTaskId, progress(phonePlan.toolName, ExecutionTarget.PHONE, "completed", 1))
        state = state.apply(
            phoneTaskId,
            ExecutionEvent.Result(
                toolName = phonePlan.toolName,
                executionTarget = ExecutionTarget.PHONE,
                content = PhoneBatteryStatus(levelPercent = 85, charging = false),
            ),
        )

        val entryAfterResult = state.entries.single()
        assertEquals(TaskPhase.COMPLETED_UNVERIFIED, entryAfterResult.phase)
        assertEquals("Battery 85%: not charging", entryAfterResult.summary)
        assertEquals(85, (entryAfterResult.result as PhoneBatteryStatus).levelPercent)
        assertEquals(phoneTaskId, state.activeTaskId)

        state = state.apply(
            phoneTaskId,
            ExecutionEvent.Verification(
                succeeded = true,
                summary = "Battery status matched the local tool contract.",
                checks = listOf("typed output"),
            ),
        )

        assertEquals(TaskPhase.VERIFIED, state.entries.single().phase)
        assertNull(state.activeTaskId)
    }

    @Test
    fun mismatchedPhoneResultTargetOrToolFailsClosed() {
        var wrongTool = TaskTimelineState().start(phoneTaskId, phonePlan)
        wrongTool = wrongTool.apply(phoneTaskId, ExecutionEvent.Starting(1))
        wrongTool = wrongTool.apply(phoneTaskId, progress(phonePlan.toolName, ExecutionTarget.PHONE, "accepted", 0))
        wrongTool = wrongTool.apply(phoneTaskId, progress(phonePlan.toolName, ExecutionTarget.PHONE, "completed", 1))
        wrongTool = wrongTool.apply(
            phoneTaskId,
            ExecutionEvent.Result(
                toolName = "phone.other",
                executionTarget = ExecutionTarget.PHONE,
                content = PhoneBatteryStatus(levelPercent = 80, charging = true),
            ),
        )
        assertEquals(TaskPhase.FAILED, wrongTool.entries.single().phase)

        var wrongTarget = TaskTimelineState().start(phoneTaskId, phonePlan)
        wrongTarget = wrongTarget.apply(phoneTaskId, ExecutionEvent.Starting(1))
        wrongTarget = wrongTarget.apply(phoneTaskId, progress(phonePlan.toolName, ExecutionTarget.PHONE, "accepted", 0))
        wrongTarget = wrongTarget.apply(phoneTaskId, progress(phonePlan.toolName, ExecutionTarget.PHONE, "completed", 1))
        wrongTarget = wrongTarget.apply(
            phoneTaskId,
            ExecutionEvent.Result(
                toolName = phonePlan.toolName,
                executionTarget = ExecutionTarget.MAC,
                content = PhoneBatteryStatus(levelPercent = 80, charging = true),
            ),
        )
        assertEquals(TaskPhase.FAILED, wrongTarget.entries.single().phase)
    }

    @Test
    fun malformedPreparationOrBatteryContentFailsClosed() {
        val readyBeforeStart = TaskTimelineState()
            .start(phoneTaskId, phonePlan)
            .apply(phoneTaskId, ExecutionEvent.Ready)
        assertEquals(TaskPhase.FAILED, readyBeforeStart.entries.single().phase)

        var invalidBattery = TaskTimelineState().start(phoneTaskId, phonePlan)
        invalidBattery = invalidBattery.apply(phoneTaskId, ExecutionEvent.Starting(1))
        invalidBattery = invalidBattery.apply(phoneTaskId, ExecutionEvent.Ready)
        invalidBattery = invalidBattery.apply(
            phoneTaskId,
            progress(phonePlan.toolName, ExecutionTarget.PHONE, "accepted", 0),
        )
        invalidBattery = invalidBattery.apply(
            phoneTaskId,
            progress(phonePlan.toolName, ExecutionTarget.PHONE, "completed", 1),
        )
        invalidBattery = invalidBattery.apply(
            phoneTaskId,
            ExecutionEvent.Result(
                phonePlan.toolName,
                ExecutionTarget.PHONE,
                PhoneBatteryStatus(levelPercent = 135, charging = false),
            ),
        )
        assertEquals(TaskPhase.FAILED, invalidBattery.entries.single().phase)
    }

    @Test
    fun deviceInfoResultRequiresTheExactTypedContract() {
        val devicePlan = GoffyExecutionPlan(
            command = "Show my phone info",
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_DEVICE_INFO_TOOL,
            permission = PermissionLevel.SAFE,
            successCriteria = listOf("Device info matches the local contract"),
        )
        var state = TaskTimelineState().start(phoneTaskId, devicePlan)
        state = state.apply(phoneTaskId, ExecutionEvent.Starting(1))
        state = state.apply(phoneTaskId, ExecutionEvent.Ready)
        state = state.apply(
            phoneTaskId,
            progress(devicePlan.toolName, ExecutionTarget.PHONE, "accepted", 0),
        )
        state = state.apply(
            phoneTaskId,
            progress(devicePlan.toolName, ExecutionTarget.PHONE, "completed", 1),
        )
        state = state.apply(
            phoneTaskId,
            ExecutionEvent.Result(
                devicePlan.toolName,
                ExecutionTarget.PHONE,
                PhoneDeviceInfo("motorola", "moto g", "15", 35),
            ),
        )

        assertEquals(TaskPhase.COMPLETED_UNVERIFIED, state.entries.single().phase)
        assertEquals("motorola moto g / Android 15 (API 35)", state.entries.single().summary)
        assertTrue(state.entries.single().result is PhoneDeviceInfo)
    }

    @Test
    fun malformedOrMismatchedDeviceInfoFailsClosed() {
        val devicePlan = GoffyExecutionPlan(
            command = "Show my phone info",
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_DEVICE_INFO_TOOL,
            permission = PermissionLevel.SAFE,
            successCriteria = emptyList(),
        )
        val invalidValues = listOf(
            PhoneDeviceInfo("", "moto g", "15", 35),
            PhoneDeviceInfo("motorola", "moto\ng", "15", 35),
            PhoneDeviceInfo("motorola", "moto\u202Eg", "15", 35),
            PhoneDeviceInfo("motorola", "moto g", "15", 25),
            PhoneDeviceInfo("motorola", "moto g", "15", Int.MAX_VALUE),
        )

        invalidValues.forEach { invalid ->
            var state = TaskTimelineState().start(phoneTaskId, devicePlan)
            state = state.apply(phoneTaskId, ExecutionEvent.Starting(1))
            state = state.apply(phoneTaskId, ExecutionEvent.Ready)
            state = state.apply(
                phoneTaskId,
                progress(devicePlan.toolName, ExecutionTarget.PHONE, "accepted", 0),
            )
            state = state.apply(
                phoneTaskId,
                progress(devicePlan.toolName, ExecutionTarget.PHONE, "completed", 1),
            )
            state = state.apply(
                phoneTaskId,
                ExecutionEvent.Result(devicePlan.toolName, ExecutionTarget.PHONE, invalid),
            )
            assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        }

        var wrongContent = TaskTimelineState().start(phoneTaskId, devicePlan)
        wrongContent = wrongContent.apply(phoneTaskId, ExecutionEvent.Starting(1))
        wrongContent = wrongContent.apply(phoneTaskId, ExecutionEvent.Ready)
        wrongContent = wrongContent.apply(
            phoneTaskId,
            progress(devicePlan.toolName, ExecutionTarget.PHONE, "accepted", 0),
        )
        wrongContent = wrongContent.apply(
            phoneTaskId,
            progress(devicePlan.toolName, ExecutionTarget.PHONE, "completed", 1),
        )
        wrongContent = wrongContent.apply(
            phoneTaskId,
            ExecutionEvent.Result(
                devicePlan.toolName,
                ExecutionTarget.PHONE,
                PhoneBatteryStatus(50, false),
            ),
        )
        assertEquals(TaskPhase.FAILED, wrongContent.entries.single().phase)
    }

    @Test
    fun cancelMakesNoClaimAboutHubCompletionForMac() {
        val state = TaskTimelineState().start(taskId, plan).cancelActive()

        assertEquals(TaskPhase.CANCELLED, state.entries.single().phase)
        assertEquals("Cancelled locally; Hub completion is not guaranteed", state.entries.single().summary)
        assertNull(state.activeTaskId)
    }

    @Test
    fun cancelForPhoneStatesThatLocalExecutionStopped() {
        val state = TaskTimelineState().start(phoneTaskId, phonePlan).cancelActive()

        assertEquals(TaskPhase.CANCELLED, state.entries.single().phase)
        assertEquals("Local PHONE execution cancelled", state.entries.single().summary)
        assertNull(state.activeTaskId)
    }

    @Test
    fun taskAndEventHistoryAreBounded() {
        var state = TaskTimelineState()
        repeat(55) { index ->
            state = state.reject("command $index", "unsupported")
        }

        assertEquals(50, state.entries.size)
        assertEquals("command 5", state.entries.first().command)
    }

    @Test
    fun startingConcurrentTaskIsRejected() {
        val state = TaskTimelineState().start(taskId, plan)

        assertThrows(IllegalArgumentException::class.java) {
            state.start(UUID.randomUUID(), plan)
        }
    }

    private fun progress(
        toolName: String,
        executionTarget: ExecutionTarget,
        stage: String,
        sequence: Int,
    ): ExecutionEvent.Progress =
        ExecutionEvent.Progress(
            ToolProgress(toolName, executionTarget, stage, sequence, stage),
        )

    private fun macResult(operatingSystem: String): ExecutionEvent.Result = ExecutionEvent.Result(
        "mac.system_info",
        ExecutionTarget.MAC,
        MacSystemInfo("available", operatingSystem, "arm64"),
    )
}
