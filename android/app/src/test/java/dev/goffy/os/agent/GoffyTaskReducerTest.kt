package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.HubStreamEvent
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.ToolProgress
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyTaskReducerTest {
    private val taskId = UUID.fromString("11111111-1111-4111-8111-111111111111")
    private val plan = (GoffyIntentRouter.route("Show my Mac status") as RoutingDecision.Routed).plan

    @Test
    fun verificationIsRequiredAfterResultBeforeSuccess() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, HubStreamEvent.Connecting(1))
        state = state.apply(taskId, HubStreamEvent.Connected)
        state = state.apply(taskId, progress("accepted", 0))
        state = state.apply(taskId, progress("completed", 1))
        state = state.apply(
            taskId,
            HubStreamEvent.Result(
                "mac.system_info",
                ExecutionTarget.MAC,
                MacSystemInfo("available", "Darwin", "arm64"),
            ),
        )

        assertEquals(TaskPhase.COMPLETED_UNVERIFIED, state.entries.single().phase)
        assertEquals(taskId, state.activeTaskId)

        state = state.apply(
            taskId,
            HubStreamEvent.Verification(true, "Schema verified", listOf("output schema")),
        )

        assertEquals(TaskPhase.VERIFIED, state.entries.single().phase)
        assertNull(state.activeTaskId)
        assertEquals("Darwin", state.entries.single().result?.operatingSystem)
    }

    @Test
    fun verificationBeforeResultFailsClosed() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, HubStreamEvent.Verification(true, "claimed", emptyList()))

        assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        assertNull(state.activeTaskId)
    }

    @Test
    fun duplicateOrOutOfOrderProgressFailsClosed() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, progress("accepted", 1))
        state = state.apply(taskId, progress("completed", 1))

        assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        assertNull(state.activeTaskId)
    }

    @Test
    fun skippedOrUnexpectedProgressStageFailsClosed() {
        var skipped = TaskTimelineState().start(taskId, plan)
        skipped = skipped.apply(taskId, HubStreamEvent.Connecting(1))
        skipped = skipped.apply(taskId, progress("accepted", 1))
        assertEquals(TaskPhase.FAILED, skipped.entries.single().phase)

        var unexpected = TaskTimelineState().start(taskId, plan)
        unexpected = unexpected.apply(taskId, HubStreamEvent.Connecting(1))
        unexpected = unexpected.apply(taskId, progress("completed", 0))
        assertEquals(TaskPhase.FAILED, unexpected.entries.single().phase)
    }

    @Test
    fun duplicateResultFailsClosedInsteadOfOverwritingData() {
        var state = TaskTimelineState().start(taskId, plan)
        state = state.apply(taskId, HubStreamEvent.Connecting(1))
        state = state.apply(taskId, HubStreamEvent.Connected)
        state = state.apply(taskId, progress("accepted", 0))
        state = state.apply(taskId, progress("completed", 1))
        state = state.apply(taskId, result("Darwin"))
        state = state.apply(taskId, result("forged"))

        assertEquals(TaskPhase.FAILED, state.entries.single().phase)
        assertEquals("Darwin", state.entries.single().result?.operatingSystem)
        assertNull(state.activeTaskId)
    }

    @Test
    fun cancelMakesNoClaimAboutHubCompletion() {
        val state = TaskTimelineState().start(taskId, plan).cancelActive()

        assertEquals(TaskPhase.CANCELLED, state.entries.single().phase)
        assertTrue(state.entries.single().summary.contains("not guaranteed"))
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

    private fun progress(stage: String, sequence: Int): HubStreamEvent.Progress =
        HubStreamEvent.Progress(
            ToolProgress("mac.system_info", ExecutionTarget.MAC, stage, sequence, stage),
        )

    private fun result(operatingSystem: String): HubStreamEvent.Result = HubStreamEvent.Result(
        "mac.system_info",
        ExecutionTarget.MAC,
        MacSystemInfo("available", operatingSystem, "arm64"),
    )
}
