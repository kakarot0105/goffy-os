package dev.goffy.os

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import java.util.UUID

enum class MacConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
}

enum class AuditPersistenceState {
    LOADING,
    READY,
    DEGRADED,
}

enum class HubLinkState {
    LOADING,
    UNPAIRED,
    PAIRING,
    PAIRED,
    DEVELOPMENT,
    FORGETTING,
    DEGRADED,
}

data class GoffyUiState(
    val macConnection: MacConnectionState = MacConnectionState.DISCONNECTED,
    val executionTarget: ExecutionTarget = ExecutionTarget.PHONE,
    val timeline: TaskTimelineState = TaskTimelineState(),
    val hubLinkState: HubLinkState = HubLinkState.LOADING,
    val hubEndpoint: String,
    val linkError: String? = null,
    val developmentTokenAllowed: Boolean = false,
    val pendingApproval: PendingApproval? = null,
    val auditPersistence: AuditPersistenceState = AuditPersistenceState.LOADING,
    val discardedAuditRecords: Int = 0,
) {
    val hubConfigured: Boolean
        get() = hubLinkState == HubLinkState.PAIRED || hubLinkState == HubLinkState.DEVELOPMENT

    val linkOperationInProgress: Boolean
        get() = hubLinkState == HubLinkState.LOADING ||
            hubLinkState == HubLinkState.PAIRING ||
            hubLinkState == HubLinkState.FORGETTING

    val isBusy: Boolean
        get() = timeline.activeTaskId != null

    fun hubConfigured(endpoint: String, persistent: Boolean = false): GoffyUiState = copy(
        hubLinkState = if (persistent) HubLinkState.PAIRED else HubLinkState.DEVELOPMENT,
        hubEndpoint = endpoint,
        linkError = null,
    )

    fun hubConfigurationRejected(message: String): GoffyUiState = copy(
        linkError = message.take(MAX_ERROR_LENGTH),
    )

    fun hubRestoreEmpty(): GoffyUiState = copy(
        hubLinkState = HubLinkState.UNPAIRED,
        linkError = null,
    )

    fun hubRestoreFailed(message: String): GoffyUiState = copy(
        hubLinkState = HubLinkState.DEGRADED,
        linkError = message.take(MAX_ERROR_LENGTH),
    )

    fun hubPairingStarted(endpoint: String): GoffyUiState = copy(
        hubLinkState = HubLinkState.PAIRING,
        hubEndpoint = endpoint,
        linkError = null,
    )

    fun hubPairingRejected(message: String): GoffyUiState = copy(
        hubLinkState = HubLinkState.UNPAIRED,
        linkError = message.take(MAX_ERROR_LENGTH),
    )

    fun hubForgetStarted(
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.FORGETTING,
        linkError = null,
        timeline = timeline.cancelActive(terminalAtEpochMillis),
        pendingApproval = null,
    )

    fun forgetHub(
        defaultEndpoint: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.UNPAIRED,
        hubEndpoint = defaultEndpoint,
        linkError = null,
        timeline = timeline.cancelActive(terminalAtEpochMillis),
        pendingApproval = null,
    )

    fun startTask(taskId: UUID, plan: GoffyExecutionPlan): GoffyUiState = copy(
        executionTarget = plan.executionTarget,
        timeline = timeline.start(taskId, plan),
    )

    fun awaitApproval(
        approval: PendingApproval,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState {
        if (approval.taskId != timeline.activeTaskId || pendingApproval != null) return this
        return copy(
            timeline = timeline.awaitApproval(
                approval.taskId,
                approval.description,
                terminalAtEpochMillis,
            ),
            pendingApproval = approval,
        )
    }

    fun grantApproval(
        taskId: UUID,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState {
        if (pendingApproval?.taskId != taskId) return this
        return copy(
            timeline = timeline.grantApproval(taskId, terminalAtEpochMillis),
            pendingApproval = null,
        )
    }

    fun denyApproval(
        taskId: UUID,
        summary: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState {
        if (pendingApproval?.taskId != taskId) return this
        return copy(
            timeline = timeline.denyApproval(taskId, summary, terminalAtEpochMillis),
            pendingApproval = null,
        )
    }

    fun expireApproval(
        taskId: UUID,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState {
        if (pendingApproval?.taskId != taskId) return this
        return copy(
            timeline = timeline.expireApproval(taskId, terminalAtEpochMillis),
            pendingApproval = null,
        )
    }

    fun applyTaskEvent(
        taskId: UUID,
        event: ExecutionEvent,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState {
        if (taskId != timeline.activeTaskId) return this
        val isMacTask = timeline.entries.lastOrNull { it.id == taskId }
            ?.executionTarget == ExecutionTarget.MAC
        val nextTimeline = timeline.apply(taskId, event, terminalAtEpochMillis)
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

    fun rejectCommand(
        command: String,
        summary: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        timeline = timeline.reject(command, summary, terminalAtEpochMillis),
    )

    fun rejectPlan(
        plan: GoffyExecutionPlan,
        summary: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        executionTarget = plan.executionTarget,
        timeline = timeline.reject(
            command = plan.command,
            summary = summary,
            terminalAtEpochMillis = terminalAtEpochMillis,
            executionTarget = plan.executionTarget,
            toolName = plan.toolName,
            permission = plan.permission,
        ),
    )

    fun auditLoaded(
        restoredEntries: List<TaskTimelineEntry>,
        discardedRecords: Int,
    ): GoffyUiState {
        require(discardedRecords >= 0) { "discarded audit count cannot be negative" }
        return copy(
            timeline = timeline.mergeRestoredAudit(restoredEntries),
            auditPersistence = if (discardedRecords == 0) {
                AuditPersistenceState.READY
            } else {
                AuditPersistenceState.DEGRADED
            },
            discardedAuditRecords = discardedRecords,
        )
    }

    fun auditFailed(): GoffyUiState = copy(auditPersistence = AuditPersistenceState.DEGRADED)

    fun auditRecorded(taskId: UUID, recordedAtEpochMillis: Long): GoffyUiState = copy(
        timeline = timeline.markAuditRecorded(taskId, recordedAtEpochMillis),
    )

    fun cancelActiveTask(
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState {
        val cancellingMacTask = timeline.entries.lastOrNull { it.id == timeline.activeTaskId }
            ?.executionTarget == ExecutionTarget.MAC
        return copy(
            macConnection = if (cancellingMacTask) MacConnectionState.DISCONNECTED else macConnection,
            timeline = timeline.cancelActive(terminalAtEpochMillis),
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
