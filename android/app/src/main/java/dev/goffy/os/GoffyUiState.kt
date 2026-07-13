package dev.goffy.os

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import java.util.UUID

enum class MacConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
}

data class GoffyUiState(
    val macConnection: MacConnectionState = MacConnectionState.DISCONNECTED,
    val executionTarget: ExecutionTarget = ExecutionTarget.PHONE,
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

    fun applyTaskEvent(taskId: UUID, event: ExecutionEvent): GoffyUiState {
        if (taskId != timeline.activeTaskId) return this
        val isMacTask = timeline.entries.lastOrNull { it.id == taskId }
            ?.executionTarget == ExecutionTarget.MAC
        val nextTimeline = timeline.apply(taskId, event)
        val connection = if (!isMacTask) {
            macConnection
        } else if (nextTimeline.activeTaskId != taskId) {
            MacConnectionState.DISCONNECTED
        } else when (event) {
            is ExecutionEvent.Starting -> MacConnectionState.CONNECTING
            ExecutionEvent.Ready -> MacConnectionState.CONNECTED
            is ExecutionEvent.Progress,
            is ExecutionEvent.Result,
            -> macConnection
            is ExecutionEvent.Error,
            is ExecutionEvent.Verification,
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

    fun cancelActiveTask(): GoffyUiState {
        val cancellingMacTask = timeline.entries.lastOrNull { it.id == timeline.activeTaskId }
            ?.executionTarget == ExecutionTarget.MAC
        return copy(
            macConnection = if (cancellingMacTask) MacConnectionState.DISCONNECTED else macConnection,
            timeline = timeline.cancelActive(),
        )
    }

    private companion object {
        const val MAX_ERROR_LENGTH = 256
    }
}
