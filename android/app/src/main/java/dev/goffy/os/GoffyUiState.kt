package dev.goffy.os

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.hub.HubOperatorAuditEvent
import dev.goffy.os.hub.HubOperatorAuditSnapshot
import dev.goffy.os.localmodel.LocalModelRuntimeGate
import dev.goffy.os.localmodel.LocalModelRuntimeStatus
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
    ROTATING,
    DEGRADED,
}

enum class HubOperatorAuditState {
    IDLE,
    LOADING,
    READY,
    DEGRADED,
}

data class HubOperatorAuditUiState(
    val state: HubOperatorAuditState = HubOperatorAuditState.IDLE,
    val storageKind: String? = null,
    val integrity: String? = null,
    val events: List<HubOperatorAuditEvent> = emptyList(),
    val message: String? = null,
    val refreshedAtEpochMillis: Long? = null,
)

data class LocalModelNotice(
    val message: String,
    val warning: Boolean,
)

data class GoffyUiState(
    val macConnection: MacConnectionState = MacConnectionState.DISCONNECTED,
    val executionTarget: ExecutionTarget = ExecutionTarget.PHONE,
    val timeline: TaskTimelineState = TaskTimelineState(),
    val hubLinkState: HubLinkState = HubLinkState.LOADING,
    val hubEndpoint: String,
    val linkError: String? = null,
    val linkNotice: HubLinkNotice? = null,
    val developmentTokenAllowed: Boolean = false,
    val pendingApproval: PendingApproval? = null,
    val auditPersistence: AuditPersistenceState = AuditPersistenceState.LOADING,
    val discardedAuditRecords: Int = 0,
    val hubIdentityFingerprint: String? = null,
    val localModelStatus: LocalModelRuntimeStatus = LocalModelRuntimeGate.goffyLiteDefault().status,
    val localModelControlsAvailable: Boolean = false,
    val localModelSettingsLoaded: Boolean = false,
    val localModelOperationInProgress: Boolean = false,
    val localModelNotice: LocalModelNotice? = null,
    val charging: Boolean = false,
    val keepAwakeWhenCharging: Boolean = true,
    val hubOperatorAudit: HubOperatorAuditUiState = HubOperatorAuditUiState(),
) {
    val hubConfigured: Boolean
        get() = hubLinkState == HubLinkState.PAIRED || hubLinkState == HubLinkState.DEVELOPMENT

    val linkOperationInProgress: Boolean
        get() = hubLinkState == HubLinkState.LOADING ||
            hubLinkState == HubLinkState.PAIRING ||
            hubLinkState == HubLinkState.FORGETTING ||
            hubLinkState == HubLinkState.ROTATING

    val isBusy: Boolean
        get() = timeline.activeTaskId != null

    val dockAwakeStatus: DockAwakeStatus
        get() = GoffyDockAwakePolicy.status(
            enabled = keepAwakeWhenCharging,
            charging = charging,
        )

    val keepScreenAwake: Boolean
        get() = GoffyDockAwakePolicy.shouldKeepScreenAwake(
            enabled = keepAwakeWhenCharging,
            charging = charging,
        )

    fun hubConfigured(
        endpoint: String,
        persistent: Boolean = false,
        hubIdentityFingerprint: String? = null,
    ): GoffyUiState = copy(
        hubLinkState = if (persistent) HubLinkState.PAIRED else HubLinkState.DEVELOPMENT,
        hubEndpoint = endpoint,
        hubIdentityFingerprint = if (persistent) {
            hubIdentityFingerprint?.take(MAX_FINGERPRINT_LENGTH)
        } else {
            null
        },
        linkError = null,
        linkNotice = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubConfigurationRejected(message: String): GoffyUiState = copy(
        linkError = message.take(MAX_ERROR_LENGTH),
        linkNotice = null,
    )

    fun localModelOperationStarted(): GoffyUiState = copy(
        localModelOperationInProgress = true,
        localModelNotice = null,
    )

    fun localModelSettingsStillLoading(
        status: LocalModelRuntimeStatus,
        message: String,
    ): GoffyUiState = copy(
        localModelStatus = status,
        localModelOperationInProgress = false,
        localModelNotice = LocalModelNotice(message, warning = true).bounded(),
    )

    fun localModelSettingsApplied(
        status: LocalModelRuntimeStatus,
        notice: LocalModelNotice,
    ): GoffyUiState = copy(
        localModelStatus = status,
        localModelSettingsLoaded = true,
        localModelOperationInProgress = false,
        localModelNotice = notice.bounded(),
    )

    fun localModelSettingsRejected(
        status: LocalModelRuntimeStatus,
        message: String,
    ): GoffyUiState = copy(
        localModelStatus = status,
        localModelSettingsLoaded = true,
        localModelOperationInProgress = false,
        localModelNotice = LocalModelNotice(message, warning = true).bounded(),
    )

    fun hubRestoreEmpty(): GoffyUiState = copy(
        hubLinkState = HubLinkState.UNPAIRED,
        hubIdentityFingerprint = null,
        linkError = null,
        linkNotice = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubRestoreFailed(message: String): GoffyUiState = copy(
        hubLinkState = HubLinkState.DEGRADED,
        hubIdentityFingerprint = null,
        linkError = message.take(MAX_ERROR_LENGTH),
        linkNotice = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubPairingStarted(endpoint: String): GoffyUiState = copy(
        hubLinkState = HubLinkState.PAIRING,
        hubEndpoint = endpoint,
        hubIdentityFingerprint = null,
        linkError = null,
        linkNotice = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubPairingRejected(message: String): GoffyUiState = copy(
        hubLinkState = HubLinkState.UNPAIRED,
        hubIdentityFingerprint = null,
        linkError = message.take(MAX_ERROR_LENGTH),
        linkNotice = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubForgetStarted(
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.FORGETTING,
        hubIdentityFingerprint = null,
        linkError = null,
        linkNotice = null,
        timeline = timeline.cancelActive(terminalAtEpochMillis),
        pendingApproval = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubRotationStarted(
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.ROTATING,
        linkError = null,
        linkNotice = null,
        timeline = timeline.cancelActive(terminalAtEpochMillis),
        pendingApproval = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubRotationSucceeded(notice: HubLinkNotice): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.PAIRED,
        linkError = null,
        linkNotice = notice.bounded(),
        pendingApproval = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubRotationFailed(message: String): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.DEGRADED,
        hubIdentityFingerprint = null,
        linkError = message.take(MAX_ERROR_LENGTH),
        linkNotice = null,
        pendingApproval = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun forgetHub(
        defaultEndpoint: String,
        notice: HubLinkNotice,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.UNPAIRED,
        hubEndpoint = defaultEndpoint,
        hubIdentityFingerprint = null,
        linkError = null,
        linkNotice = notice.bounded(),
        timeline = timeline.cancelActive(terminalAtEpochMillis),
        pendingApproval = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
    )

    fun hubForgetVerificationFailed(
        defaultEndpoint: String,
        message: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): GoffyUiState = copy(
        macConnection = MacConnectionState.DISCONNECTED,
        hubLinkState = HubLinkState.DEGRADED,
        hubEndpoint = defaultEndpoint,
        hubIdentityFingerprint = null,
        linkError = message.take(MAX_ERROR_LENGTH),
        linkNotice = null,
        timeline = timeline.cancelActive(terminalAtEpochMillis),
        pendingApproval = null,
        hubOperatorAudit = HubOperatorAuditUiState(),
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

    fun hubOperatorAuditLoading(): GoffyUiState = copy(
        hubOperatorAudit = hubOperatorAudit.copy(
            state = HubOperatorAuditState.LOADING,
            message = null,
        ),
    )

    fun hubOperatorAuditLoaded(
        snapshot: HubOperatorAuditSnapshot,
        refreshedAtEpochMillis: Long,
    ): GoffyUiState = copy(
        hubOperatorAudit = HubOperatorAuditUiState(
            state = HubOperatorAuditState.READY,
            storageKind = snapshot.storageKind.take(MAX_HUB_AUDIT_LABEL_LENGTH),
            integrity = snapshot.integrity.take(MAX_HUB_AUDIT_LABEL_LENGTH),
            events = snapshot.events.take(MAX_HUB_OPERATOR_AUDIT_EVENTS),
            message = null,
            refreshedAtEpochMillis = refreshedAtEpochMillis,
        ),
    )

    fun hubOperatorAuditFailed(message: String): GoffyUiState = copy(
        hubOperatorAudit = hubOperatorAudit.copy(
            state = HubOperatorAuditState.DEGRADED,
            message = message.take(MAX_ERROR_LENGTH),
        ),
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
        const val MAX_NOTICE_LENGTH = 256
        const val MAX_FINGERPRINT_LENGTH = 80
        const val MAX_LOCAL_MODEL_NOTICE_LENGTH = 180
        const val MAX_HUB_AUDIT_LABEL_LENGTH = 32
        const val MAX_HUB_OPERATOR_AUDIT_EVENTS = 20
    }

    private fun HubLinkNotice.bounded(): HubLinkNotice = copy(
        message = message.take(MAX_NOTICE_LENGTH),
    )

    private fun LocalModelNotice.bounded(): LocalModelNotice = copy(
        message = message.take(MAX_LOCAL_MODEL_NOTICE_LENGTH),
    )
}

data class HubLinkNotice(
    val message: String,
    val warning: Boolean,
)

data class PendingApproval(
    val taskId: UUID,
    val toolName: String,
    val description: String,
    val expiresAtEpochMillis: Long,
    val durationSeconds: Long,
)
