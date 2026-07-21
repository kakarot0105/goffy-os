package dev.goffy.os

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAC_APPS_OPEN_TOOL
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.PermissionLevel
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyOrbUiModelTest {
    private val endpoint = "wss://mac.example/ws/v1"
    private val taskId = UUID.fromString("11111111-1111-4111-8111-111111111111")
    private val macPlan =
        (GoffyIntentRouter.route("Show my Mac status") as RoutingDecision.Routed).plan
    private val phonePlan =
        (GoffyIntentRouter.route("Show my battery status") as RoutingDecision.Routed).plan
    private val cloudPlan = GoffyExecutionPlan(
        command = "Use cloud reasoning",
        executionTarget = ExecutionTarget.CLOUD,
        toolName = "cloud.reason",
        permission = PermissionLevel.SAFE,
        successCriteria = listOf("Cloud route is visible only when selected"),
    )
    private val confirmMacPlan = GoffyExecutionPlan(
        command = "Open Safari on my Mac",
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_APPS_OPEN_TOOL,
        permission = PermissionLevel.CONFIRM,
        successCriteria = listOf("Open one approved Mac application"),
    )

    @Test
    fun idleStateShowsPhoneTargetWithoutActiveTask() {
        val model = GoffyUiState(hubEndpoint = endpoint).toGoffyOrbUiModel(
            GoffyVoiceInputState(),
        )

        assertEquals(GoffyOrbMode.IDLE, model.mode)
        assertEquals(ExecutionTarget.PHONE, model.target)
        assertFalse(model.hasActiveTask)
    }

    @Test
    fun foregroundVoiceListeningTakesVisualPriority() {
        val state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, macPlan)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState(listening = true))

        assertEquals(GoffyOrbMode.LISTENING, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertTrue(model.hasActiveTask)
    }

    @Test
    fun activeMacTaskShowsMacRoute() {
        val state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, macPlan)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.MAC_ROUTE, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertEquals(TaskPhase.ROUTING, model.phase)
        assertTrue(model.hasActiveTask)
    }

    @Test
    fun activePhoneTaskShowsPhoneRoute() {
        val state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, phonePlan)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.PHONE_ROUTE, model.mode)
        assertEquals(ExecutionTarget.PHONE, model.target)
        assertEquals(TaskPhase.ROUTING, model.phase)
        assertTrue(model.hasActiveTask)
    }

    @Test
    fun activeCloudTaskShowsCloudRoute() {
        val state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, cloudPlan)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.CLOUD_ROUTE, model.mode)
        assertEquals(ExecutionTarget.CLOUD, model.target)
        assertEquals(TaskPhase.ROUTING, model.phase)
        assertTrue(model.hasActiveTask)
    }

    @Test
    fun pendingApprovalOverridesRouteState() {
        val approval = PendingApproval(
            taskId = taskId,
            toolName = MAC_APPS_OPEN_TOOL,
            description = "Approve one Mac app open",
            expiresAtEpochMillis = 2_000,
            durationSeconds = 30,
        )
        val state = GoffyUiState(hubEndpoint = endpoint)
            .startTask(taskId, confirmMacPlan)
            .awaitApproval(approval, terminalAtEpochMillis = 1_000)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.APPROVAL, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertEquals(TaskPhase.AWAITING_APPROVAL, model.phase)
    }

    @Test
    fun latestVerifiedTaskShowsVerifiedState() {
        val state = stateWithTerminalPhase(TaskPhase.VERIFIED)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.VERIFIED, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertFalse(model.hasActiveTask)
    }

    @Test
    fun latestFailedTaskShowsAttentionState() {
        val state = stateWithTerminalPhase(TaskPhase.FAILED)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.ATTENTION, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertFalse(model.hasActiveTask)
    }

    @Test
    fun latestUnverifiedTaskShowsAttentionState() {
        val state = stateWithTerminalPhase(TaskPhase.UNVERIFIED)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.ATTENTION, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertFalse(model.hasActiveTask)
    }

    @Test
    fun latestCancelledTaskShowsAttentionState() {
        val state = stateWithTerminalPhase(TaskPhase.CANCELLED)

        val model = state.toGoffyOrbUiModel(GoffyVoiceInputState())

        assertEquals(GoffyOrbMode.ATTENTION, model.mode)
        assertEquals(ExecutionTarget.MAC, model.target)
        assertFalse(model.hasActiveTask)
    }

    private fun stateWithTerminalPhase(phase: TaskPhase): GoffyUiState = GoffyUiState(
        hubEndpoint = endpoint,
        timeline = TaskTimelineState(
            entries = listOf(
                TaskTimelineEntry(
                    id = taskId,
                    command = "Show my Mac status",
                    executionTarget = ExecutionTarget.MAC,
                    toolName = MAC_SYSTEM_INFO_TOOL,
                    phase = phase,
                    summary = "Terminal state",
                    events = emptyList(),
                    terminalAtEpochMillis = 1_000,
                ),
            ),
        ),
    )
}
