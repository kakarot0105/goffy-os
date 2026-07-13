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
    val pendingApproval: PendingApproval? = null,
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
        pendingApproval = null,
    )

    fun startTask(taskId: UUID, plan: GoffyExecutionPlan): GoffyUiState = copy(
        executionTarget = plan.executionTarget,
        timeline = timeline.start(taskId, plan),
    )

    fun awaitApproval(approval: PendingApproval): GoffyUiState {
        if (approval.taskId != timeline.activeTaskId || pendingApproval != null) return this
        return copy(
            timeline = timeline.awaitApproval(approval.taskId, approval.description),
            pendingApproval = approval,
        )
    }

    fun grantApproval(taskId: UUID): GoffyUiState {
        if (pendingApproval?.taskId != taskId) return this
        return copy(
            timeline = timeline.grantApproval(taskId),
            pendingApproval = null,
        )
    }

    fun denyApproval(taskId: UUID, summary: String): GoffyUiState {
        if (pendingApproval?.taskId != taskId) return this
        return copy(
            timeline = timeline.denyApproval(taskId, summary),
            pendingApproval = null,
        )
    }

    fun expireApproval(taskId: UUID): GoffyUiState {
        if (pendingApproval?.taskId != taskId) return this
        return copy(
            timeline = timeline.expireApproval(taskId),
            pendingApproval = null,
        )
    }

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
            is ExecutionEvent.Unverified,
            is ExecutionEvent.Verification,
            -> MacConnectionState.DISCONNECTED
        }
        return copy(
            macConnection = connection,
            timeline = nextTimeline,
            pendingApproval = if (nextTimeline.activeTaskId == taskId) pendingApproval else null,
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
            pendingApproval = null,
        )
    }

    private companion object {
        const val MAX_ERROR_LENGTH = 256
    }
}

data class PendingApproval(
    val taskId: UUID,
    val toolName: String,
    val description: String,
    val expiresAtEpochMillis: Long,
    val durationSeconds: Long,
)
