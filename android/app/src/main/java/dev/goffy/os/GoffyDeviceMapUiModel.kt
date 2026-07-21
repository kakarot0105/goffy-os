package dev.goffy.os

import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.localmodel.LocalModelRuntimeState
import dev.goffy.os.protocol.ExecutionTarget

private const val LOCAL_MODEL_OBSERVATION_SUMMARY = "Checking local model observe-only fallback"

internal enum class GoffyDeviceMapRouteMode {
    STANDBY,
    ACTIVE_TARGET,
    LOCAL_MODEL_OBSERVATION,
}

internal enum class GoffyDeviceMapNodeKind {
    PHONE,
    MAC_HUB,
    MCP,
    LOCAL_MODEL,
    CLOUD,
}

internal enum class GoffyDeviceMapNodeStatus {
    READY,
    CONNECTING,
    WAITING,
    OFFLINE,
    DISABLED,
    UNAVAILABLE,
    BLOCKED,
    OBSERVE_ONLY,
}

internal data class GoffyDeviceMapNode(
    val kind: GoffyDeviceMapNodeKind,
    val status: GoffyDeviceMapNodeStatus,
    val active: Boolean,
)

internal data class GoffyDeviceMapUiModel(
    val activeTarget: ExecutionTarget,
    val hasActiveTask: Boolean,
    val routeMode: GoffyDeviceMapRouteMode,
    val nodes: List<GoffyDeviceMapNode>,
)

internal fun GoffyUiState.toGoffyDeviceMapUiModel(): GoffyDeviceMapUiModel {
    val activeEntry = timeline.activeTaskId?.let { activeTaskId ->
        timeline.entries.lastOrNull { it.id == activeTaskId }
    }
    val localModelObservationActive = activeEntry?.isLocalModelObservation() == true
    val activeTarget = activeEntry?.executionTarget ?: executionTarget
    val hasActiveTask = activeEntry != null
    val routeMode = when {
        localModelObservationActive -> GoffyDeviceMapRouteMode.LOCAL_MODEL_OBSERVATION
        hasActiveTask -> GoffyDeviceMapRouteMode.ACTIVE_TARGET
        else -> GoffyDeviceMapRouteMode.STANDBY
    }
    return GoffyDeviceMapUiModel(
        activeTarget = activeTarget,
        hasActiveTask = hasActiveTask,
        routeMode = routeMode,
        nodes = listOf(
            GoffyDeviceMapNode(
                kind = GoffyDeviceMapNodeKind.PHONE,
                status = GoffyDeviceMapNodeStatus.READY,
                active = hasActiveTask &&
                    activeTarget == ExecutionTarget.PHONE &&
                    !localModelObservationActive,
            ),
            GoffyDeviceMapNode(
                kind = GoffyDeviceMapNodeKind.MAC_HUB,
                status = macHubNodeStatus(),
                active = hasActiveTask && activeTarget == ExecutionTarget.MAC,
            ),
            GoffyDeviceMapNode(
                kind = GoffyDeviceMapNodeKind.MCP,
                status = mcpNodeStatus(),
                active = hasActiveTask && activeTarget == ExecutionTarget.MAC,
            ),
            GoffyDeviceMapNode(
                kind = GoffyDeviceMapNodeKind.LOCAL_MODEL,
                status = localModelNodeStatus(),
                active = localModelObservationActive,
            ),
            GoffyDeviceMapNode(
                kind = GoffyDeviceMapNodeKind.CLOUD,
                status = GoffyDeviceMapNodeStatus.DISABLED,
                active = hasActiveTask && activeTarget == ExecutionTarget.CLOUD,
            ),
        ),
    )
}

private fun GoffyUiState.macHubNodeStatus(): GoffyDeviceMapNodeStatus = when (macConnection) {
    MacConnectionState.CONNECTED -> GoffyDeviceMapNodeStatus.READY
    MacConnectionState.CONNECTING -> GoffyDeviceMapNodeStatus.CONNECTING
    MacConnectionState.DISCONNECTED -> if (hubConfigured) {
        GoffyDeviceMapNodeStatus.WAITING
    } else {
        GoffyDeviceMapNodeStatus.OFFLINE
    }
}

private fun TaskTimelineEntry.isLocalModelObservation(): Boolean =
    toolName == null &&
        permission == null &&
        summary == LOCAL_MODEL_OBSERVATION_SUMMARY

private fun GoffyUiState.mcpNodeStatus(): GoffyDeviceMapNodeStatus = when (macConnection) {
    MacConnectionState.CONNECTED -> GoffyDeviceMapNodeStatus.READY
    MacConnectionState.CONNECTING -> GoffyDeviceMapNodeStatus.CONNECTING
    MacConnectionState.DISCONNECTED -> if (hubConfigured) {
        GoffyDeviceMapNodeStatus.WAITING
    } else {
        GoffyDeviceMapNodeStatus.OFFLINE
    }
}

private fun GoffyUiState.localModelNodeStatus(): GoffyDeviceMapNodeStatus =
    when (localModelStatus.state) {
        LocalModelRuntimeState.READY -> GoffyDeviceMapNodeStatus.OBSERVE_ONLY
        LocalModelRuntimeState.BLOCKED -> GoffyDeviceMapNodeStatus.BLOCKED
        LocalModelRuntimeState.UNAVAILABLE -> GoffyDeviceMapNodeStatus.UNAVAILABLE
        LocalModelRuntimeState.DISABLED -> GoffyDeviceMapNodeStatus.DISABLED
    }
