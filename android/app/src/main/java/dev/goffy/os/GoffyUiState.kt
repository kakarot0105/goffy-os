package dev.goffy.os

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.HubStreamEvent
import java.util.UUID

enum class MacConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
}

data class GoffyUiState(
    val macConnection: MacConnectionState = MacConnectionState.DISCONNECTED,
    val executionTarget: ExecutionTarget = ExecutionTarget.MAC,
    val timeline: TaskTimelineState = TaskTimelineState(),
    val hubConfigured: Boolean = false,
    val hubEndpoint: String,
    val linkError: String? = null,
) {
    val isBusy: Boolean
        get() = timeline.activeTaskId != null

    fun hubConfigured(endpoint: String): GoffyUiState = copy(
        hubConfigured = true,
        hubEndpoint = endpoint,
        linkError = null,
    )

    fun hubConfigurationRejected(message: String): GoffyUiState = copy(
        hubConfigured = false,
        linkError = message.take(MAX_ERROR_LENGTH),
    )

    fun forgetHub(defaultEndpoint: String): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubConfigured = false,
        hubEndpoint = defaultEndpoint,
        linkError = null,
        timeline = timeline.cancelActive(),
    )

    fun startTask(taskId: UUID, plan: GoffyExecutionPlan): GoffyUiState = copy(
        executionTarget = plan.executionTarget,
        timeline = timeline.start(taskId, plan),
    )

    fun applyTaskEvent(taskId: UUID, event: HubStreamEvent): GoffyUiState {
        if (taskId != timeline.activeTaskId) return this
        val nextTimeline = timeline.apply(taskId, event)
        val connection = when (event) {
            is HubStreamEvent.Connecting -> MacConnectionState.CONNECTING
            HubStreamEvent.Connected -> MacConnectionState.CONNECTED
            is HubStreamEvent.Progress,
            is HubStreamEvent.Result,
            -> macConnection
            is HubStreamEvent.Error,
            is HubStreamEvent.Verification,
            -> MacConnectionState.DISCONNECTED
        }
        return copy(
            macConnection = connection,
            timeline = nextTimeline,
        )
    }

    fun rejectCommand(command: String, summary: String): GoffyUiState = copy(
        timeline = timeline.reject(command, summary),
    )

    fun cancelActiveTask(): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        timeline = timeline.cancelActive(),
    )

    private companion object {
        const val MAX_ERROR_LENGTH = 256
    }
}
