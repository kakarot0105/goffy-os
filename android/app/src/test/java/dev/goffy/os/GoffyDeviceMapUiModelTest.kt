package dev.goffy.os

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.localmodel.LocalModelRuntimeState
import dev.goffy.os.localmodel.LocalModelRuntimeStatus
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PermissionLevel
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyDeviceMapUiModelTest {
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
        successCriteria = listOf("Cloud route remains explicit"),
    )

    @Test
    fun idleMapShowsPhoneReadyAndExternalNodesUnavailable() {
        val model = GoffyUiState(hubEndpoint = endpoint).toGoffyDeviceMapUiModel()

        assertFalse(model.hasActiveTask)
        assertEquals(ExecutionTarget.PHONE, model.activeTarget)
        assertEquals(GoffyDeviceMapRouteMode.STANDBY, model.routeMode)
        assertEquals(GoffyDeviceMapNodeStatus.READY, model.node(GoffyDeviceMapNodeKind.PHONE).status)
        assertEquals(GoffyDeviceMapNodeStatus.OFFLINE, model.node(GoffyDeviceMapNodeKind.MAC_HUB).status)
        assertEquals(GoffyDeviceMapNodeStatus.OFFLINE, model.node(GoffyDeviceMapNodeKind.MCP).status)
        assertEquals(GoffyDeviceMapNodeStatus.DISABLED, model.node(GoffyDeviceMapNodeKind.CLOUD).status)
        assertFalse(model.nodes.any { it.active })
    }

    @Test
    fun activePhoneTaskMarksOnlyPhoneRouteActive() {
        val model = GoffyUiState(hubEndpoint = endpoint)
            .startTask(taskId, phonePlan)
            .toGoffyDeviceMapUiModel()

        assertTrue(model.hasActiveTask)
        assertEquals(ExecutionTarget.PHONE, model.activeTarget)
        assertEquals(GoffyDeviceMapRouteMode.ACTIVE_TARGET, model.routeMode)
        assertTrue(model.node(GoffyDeviceMapNodeKind.PHONE).active)
        assertFalse(model.node(GoffyDeviceMapNodeKind.MAC_HUB).active)
        assertFalse(model.node(GoffyDeviceMapNodeKind.MCP).active)
    }

    @Test
    fun pairedIdleHubShowsMacAndMcpWaiting() {
        val model = GoffyUiState(hubEndpoint = endpoint)
            .hubConfigured(endpoint, persistent = true)
            .toGoffyDeviceMapUiModel()

        assertFalse(model.hasActiveTask)
        assertEquals(GoffyDeviceMapRouteMode.STANDBY, model.routeMode)
        assertEquals(GoffyDeviceMapNodeStatus.WAITING, model.node(GoffyDeviceMapNodeKind.MAC_HUB).status)
        assertEquals(GoffyDeviceMapNodeStatus.WAITING, model.node(GoffyDeviceMapNodeKind.MCP).status)
    }

    @Test
    fun connectingMacTaskMarksMacAndMcpConnecting() {
        val state = GoffyUiState(hubEndpoint = endpoint)
            .hubConfigured(endpoint, persistent = true)
            .startTask(taskId, macPlan)
            .applyTaskEvent(taskId, ExecutionEvent.Starting(1))

        val model = state.toGoffyDeviceMapUiModel()

        assertTrue(model.hasActiveTask)
        assertEquals(GoffyDeviceMapRouteMode.ACTIVE_TARGET, model.routeMode)
        assertEquals(GoffyDeviceMapNodeStatus.CONNECTING, model.node(GoffyDeviceMapNodeKind.MAC_HUB).status)
        assertEquals(GoffyDeviceMapNodeStatus.CONNECTING, model.node(GoffyDeviceMapNodeKind.MCP).status)
    }

    @Test
    fun connectedMacTaskMarksMacAndMcpRouteActive() {
        var state = GoffyUiState(hubEndpoint = endpoint)
            .hubConfigured(endpoint, persistent = true)
            .startTask(taskId, macPlan)
        state = state.applyTaskEvent(taskId, ExecutionEvent.Starting(1))
        state = state.applyTaskEvent(taskId, ExecutionEvent.Ready)

        val model = state.toGoffyDeviceMapUiModel()

        assertTrue(model.hasActiveTask)
        assertEquals(ExecutionTarget.MAC, model.activeTarget)
        assertEquals(GoffyDeviceMapRouteMode.ACTIVE_TARGET, model.routeMode)
        assertTrue(model.node(GoffyDeviceMapNodeKind.MAC_HUB).active)
        assertTrue(model.node(GoffyDeviceMapNodeKind.MCP).active)
        assertEquals(GoffyDeviceMapNodeStatus.READY, model.node(GoffyDeviceMapNodeKind.MAC_HUB).status)
        assertEquals(GoffyDeviceMapNodeStatus.READY, model.node(GoffyDeviceMapNodeKind.MCP).status)
    }

    @Test
    fun localModelBlockedStateIsVisibleButNeverActiveRoute() {
        val model = GoffyUiState(
            hubEndpoint = endpoint,
            localModelStatus = LocalModelRuntimeStatus(
                state = LocalModelRuntimeState.BLOCKED,
                summary = "Local model blocked by policy.",
                enabledByUser = true,
                runtimeAvailable = true,
                modelAvailable = false,
            ),
        ).toGoffyDeviceMapUiModel()

        val localModel = model.node(GoffyDeviceMapNodeKind.LOCAL_MODEL)

        assertEquals(GoffyDeviceMapNodeStatus.BLOCKED, localModel.status)
        assertFalse(localModel.active)
    }

    @Test
    fun localModelReadyStateIsObserveOnlyAndInactiveAtStandby() {
        val model = GoffyUiState(
            hubEndpoint = endpoint,
            localModelStatus = readyLocalModelStatus(),
        ).toGoffyDeviceMapUiModel()

        val localModel = model.node(GoffyDeviceMapNodeKind.LOCAL_MODEL)

        assertEquals(GoffyDeviceMapNodeStatus.OBSERVE_ONLY, localModel.status)
        assertFalse(localModel.active)
    }

    @Test
    fun activeLocalModelObservationDoesNotPretendToBePhoneExecution() {
        val model = GoffyUiState(
            hubEndpoint = endpoint,
            localModelStatus = readyLocalModelStatus(),
            timeline = TaskTimelineState().startLocalModelObservation(
                taskId = taskId,
                command = "unknown command",
                statusSummary = "Local model ready for observe-only fallback.",
            ),
        ).toGoffyDeviceMapUiModel()

        assertTrue(model.hasActiveTask)
        assertEquals(ExecutionTarget.PHONE, model.activeTarget)
        assertEquals(GoffyDeviceMapRouteMode.LOCAL_MODEL_OBSERVATION, model.routeMode)
        assertFalse(model.node(GoffyDeviceMapNodeKind.PHONE).active)
        assertTrue(model.node(GoffyDeviceMapNodeKind.LOCAL_MODEL).active)
    }

    @Test
    fun cloudRouteIsExplicitButDisabledByDefault() {
        val model = GoffyUiState(hubEndpoint = endpoint)
            .startTask(taskId, cloudPlan)
            .toGoffyDeviceMapUiModel()

        val cloud = model.node(GoffyDeviceMapNodeKind.CLOUD)

        assertEquals(ExecutionTarget.CLOUD, model.activeTarget)
        assertEquals(GoffyDeviceMapRouteMode.ACTIVE_TARGET, model.routeMode)
        assertTrue(cloud.active)
        assertEquals(GoffyDeviceMapNodeStatus.DISABLED, cloud.status)
    }

    private fun GoffyDeviceMapUiModel.node(
        kind: GoffyDeviceMapNodeKind,
    ): GoffyDeviceMapNode = nodes.single { it.kind == kind }

    private fun readyLocalModelStatus(): LocalModelRuntimeStatus = LocalModelRuntimeStatus(
        state = LocalModelRuntimeState.READY,
        summary = "Local model ready for observe-only fallback.",
        enabledByUser = true,
        runtimeAvailable = true,
        modelAvailable = true,
    )
}
