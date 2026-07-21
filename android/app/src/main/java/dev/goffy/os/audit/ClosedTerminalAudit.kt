package dev.goffy.os.audit

import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GIT_STATUS_TOOL
import dev.goffy.os.protocol.GOFFY_PROTOCOL_VERSION
import dev.goffy.os.protocol.MAC_CLIPBOARD_READ_TOOL
import dev.goffy.os.protocol.MAC_FILES_LIST_TOOL
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PHONE_OCR_READ_TOOL
import dev.goffy.os.protocol.PHONE_QR_READ_TOOL
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PermissionLevel
import java.util.UUID

enum class AuditSourceSurface {
    TERMINAL_TIMELINE,
}

enum class AuditPermission {
    SAFE,
    CONFIRM,
}

enum class TerminalAuditPhase {
    VERIFIED,
    UNVERIFIED,
    FAILED,
    CANCELLED,
}

enum class AuditApprovalOutcome {
    NOT_REQUIRED,
    APPROVED,
    DENIED,
    EXPIRED,
    CANCELLED,
}

data class ClosedTerminalAuditRecord(
    val schemaVersion: Int = SCHEMA_VERSION,
    val taskId: UUID,
    val recordedAtEpochMillis: Long,
    val protocolVersion: String,
    val sourceSurface: AuditSourceSurface,
    val executionTarget: ExecutionTarget,
    val toolName: String?,
    val permission: AuditPermission?,
    val phase: TerminalAuditPhase,
    val approvalOutcome: AuditApprovalOutcome,
    val eventKinds: List<TaskEventKind>,
) {
    init {
        require(schemaVersion == SCHEMA_VERSION) { "unsupported audit schema version: $schemaVersion" }
        require(recordedAtEpochMillis > 0) { "recordedAtEpochMillis must be positive" }
        require(protocolVersion in SUPPORTED_AUDIT_PROTOCOL_VERSIONS) {
            "unsupported audit protocol version: $protocolVersion"
        }
        require(executionTarget in setOf(ExecutionTarget.PHONE, ExecutionTarget.MAC)) {
            "audit execution target must be PHONE or MAC"
        }
        require(
            if (toolName == null) {
                permission == null
            } else {
                AUDIT_CAPABILITY_CONTRACTS[toolName] == (executionTarget to permission)
            },
        ) {
            "audit tool, target, and permission must match a closed capability contract"
        }
        require(permission == AuditPermission.CONFIRM || approvalOutcome == AuditApprovalOutcome.NOT_REQUIRED) {
            "only CONFIRM capabilities may record an approval outcome"
        }
        require(eventKinds.size <= MAX_EVENT_KINDS) {
            "eventKinds exceeds $MAX_EVENT_KINDS items"
        }
    }

    fun toTimelineEntry(): TaskTimelineEntry = TaskTimelineEntry(
        id = taskId,
        command = toolName.displayCommand(),
        executionTarget = executionTarget,
        toolName = toolName,
        phase = phase.toTaskPhase(),
        summary = phase.displaySummary(),
        events = eventKinds.takeLast(MAX_EVENT_KINDS).map { kind ->
            TaskTimelineEvent(kind, kind.displayMessage(approvalOutcome, phase))
        },
        result = null,
        verificationSummary = null,
        verificationChecks = emptyList(),
        lastProgressSequence = null,
        lastStartAttempt = null,
        executionReady = false,
        permission = permission.toPermissionLevel(),
        approvalGranted = false,
        terminalAtEpochMillis = recordedAtEpochMillis,
        auditRecordedAtEpochMillis = recordedAtEpochMillis,
    )
}

data class ClosedTerminalAuditLoadResult(
    val records: List<ClosedTerminalAuditRecord>,
    val discardedCorruptRows: Int,
) {
    init {
        require(discardedCorruptRows >= 0) { "discardedCorruptRows cannot be negative" }
    }
}

interface TerminalAuditStore {
    suspend fun load(): ClosedTerminalAuditLoadResult

    suspend fun upsert(record: ClosedTerminalAuditRecord): ClosedTerminalAuditRecord

    fun close()
}

fun TaskTimelineEntry.toClosedTerminalAuditRecord(
    recordedAtEpochMillis: Long,
    protocolVersion: String = GOFFY_PROTOCOL_VERSION,
    sourceSurface: AuditSourceSurface = AuditSourceSurface.TERMINAL_TIMELINE,
): ClosedTerminalAuditRecord? {
    val terminalPhase = phase.toTerminalAuditPhase() ?: return null
    return ClosedTerminalAuditRecord(
        taskId = id,
        recordedAtEpochMillis = recordedAtEpochMillis,
        protocolVersion = protocolVersion,
        sourceSurface = sourceSurface,
        executionTarget = executionTarget,
        toolName = toolName?.takeIf { it in ALLOWLISTED_TOOL_NAMES },
        permission = permission.toAuditPermission(),
        phase = terminalPhase,
        approvalOutcome = approvalOutcome(),
        eventKinds = events.map(TaskTimelineEvent::kind).takeLast(MAX_EVENT_KINDS),
    )
}

private fun TaskPhase.toTerminalAuditPhase(): TerminalAuditPhase? = when (this) {
    TaskPhase.VERIFIED -> TerminalAuditPhase.VERIFIED
    TaskPhase.UNVERIFIED -> TerminalAuditPhase.UNVERIFIED
    TaskPhase.FAILED -> TerminalAuditPhase.FAILED
    TaskPhase.CANCELLED -> TerminalAuditPhase.CANCELLED
    TaskPhase.ROUTING,
    TaskPhase.AWAITING_APPROVAL,
    TaskPhase.PREPARING,
    TaskPhase.ACCEPTED,
    TaskPhase.COMPLETED_UNVERIFIED,
    -> null
}

private fun TerminalAuditPhase.toTaskPhase(): TaskPhase = when (this) {
    TerminalAuditPhase.VERIFIED -> TaskPhase.VERIFIED
    TerminalAuditPhase.UNVERIFIED -> TaskPhase.UNVERIFIED
    TerminalAuditPhase.FAILED -> TaskPhase.FAILED
    TerminalAuditPhase.CANCELLED -> TaskPhase.CANCELLED
}

private fun TerminalAuditPhase.displaySummary(): String = when (this) {
    TerminalAuditPhase.VERIFIED -> "Recorded task completed with verification"
    TerminalAuditPhase.UNVERIFIED -> "Recorded task completed without readable verification"
    TerminalAuditPhase.FAILED -> "Recorded task failed"
    TerminalAuditPhase.CANCELLED -> "Recorded task was cancelled"
}

private fun PermissionLevel?.toAuditPermission(): AuditPermission? = when (this) {
    PermissionLevel.SAFE -> AuditPermission.SAFE
    PermissionLevel.CONFIRM -> AuditPermission.CONFIRM
    PermissionLevel.SENSITIVE,
    PermissionLevel.BLOCKED,
    null,
    -> null
}

private fun AuditPermission?.toPermissionLevel(): PermissionLevel? = when (this) {
    AuditPermission.SAFE -> PermissionLevel.SAFE
    AuditPermission.CONFIRM -> PermissionLevel.CONFIRM
    null -> null
}

private fun TaskTimelineEntry.approvalOutcome(): AuditApprovalOutcome = when {
    permission != PermissionLevel.CONFIRM -> AuditApprovalOutcome.NOT_REQUIRED
    approvalGranted -> AuditApprovalOutcome.APPROVED
    phase == TaskPhase.CANCELLED && summary == APPROVAL_DENIED_SUMMARY -> AuditApprovalOutcome.DENIED
    phase == TaskPhase.CANCELLED && summary == APPROVAL_CANCELLED_SUMMARY -> AuditApprovalOutcome.CANCELLED
    phase == TaskPhase.FAILED && summary == APPROVAL_EXPIRED_SUMMARY -> AuditApprovalOutcome.EXPIRED
    phase == TaskPhase.CANCELLED -> AuditApprovalOutcome.CANCELLED
    else -> AuditApprovalOutcome.CANCELLED
}

private fun TaskEventKind.displayMessage(
    approvalOutcome: AuditApprovalOutcome,
    phase: TerminalAuditPhase,
): String = when (this) {
    TaskEventKind.OBSERVE -> "Recorded observation step"
    TaskEventKind.PLAN -> "Recorded planning step"
    TaskEventKind.AUTHORIZE -> when (approvalOutcome) {
        AuditApprovalOutcome.APPROVED -> "Recorded approval grant"
        AuditApprovalOutcome.DENIED -> "Recorded approval denial"
        AuditApprovalOutcome.EXPIRED -> "Recorded approval expiry"
        AuditApprovalOutcome.CANCELLED -> "Recorded approval cancellation"
        AuditApprovalOutcome.NOT_REQUIRED -> "Recorded approval step"
    }
    TaskEventKind.PREPARE -> "Recorded preparation step"
    TaskEventKind.TOOL -> "Recorded execution step"
    TaskEventKind.RESULT -> "Recorded result step"
    TaskEventKind.VERIFY -> if (phase == TerminalAuditPhase.UNVERIFIED) {
        "Recorded unverified completion"
    } else {
        "Recorded verification step"
    }
    TaskEventKind.ERROR -> "Recorded failure step"
}

private fun String?.displayCommand(): String = when (this) {
    GIT_STATUS_TOOL -> "Recorded Git status task"
    MAC_CLIPBOARD_READ_TOOL -> "Recorded Mac clipboard task"
    MAC_FILES_LIST_TOOL -> "Recorded Mac file listing task"
    MAC_SYSTEM_INFO_TOOL -> "Recorded Mac status task"
    PHONE_BATTERY_STATUS_TOOL -> "Recorded battery status task"
    PHONE_DEVICE_INFO_TOOL -> "Recorded device info task"
    PHONE_FLASHLIGHT_SET_TOOL -> "Recorded flashlight action task"
    PHONE_NOTE_CREATE_TOOL -> "Recorded private note task"
    PHONE_OCR_READ_TOOL -> "Recorded OCR read task"
    PHONE_QR_READ_TOOL -> "Recorded QR read task"
    PHONE_TIMER_CREATE_TOOL -> "Recorded timer task"
    null -> "Recorded unsupported task"
    else -> "Recorded task"
}

private const val APPROVAL_DENIED_SUMMARY = "Approval denied; no phone tool was invoked"
private const val APPROVAL_CANCELLED_SUMMARY = "Approval cancelled; no phone tool was invoked"
private const val APPROVAL_EXPIRED_SUMMARY = "Approval expired; no phone tool was invoked"
internal const val SCHEMA_VERSION = 1
internal const val MAX_EVENT_KINDS = 16
internal val SUPPORTED_AUDIT_PROTOCOL_VERSIONS = setOf("0.2.0", GOFFY_PROTOCOL_VERSION)
private val AUDIT_CAPABILITY_CONTRACTS = mapOf(
    GIT_STATUS_TOOL to (ExecutionTarget.MAC to AuditPermission.SAFE),
    MAC_CLIPBOARD_READ_TOOL to (ExecutionTarget.MAC to AuditPermission.SAFE),
    MAC_FILES_LIST_TOOL to (ExecutionTarget.MAC to AuditPermission.SAFE),
    MAC_SYSTEM_INFO_TOOL to (ExecutionTarget.MAC to AuditPermission.SAFE),
    PHONE_BATTERY_STATUS_TOOL to (ExecutionTarget.PHONE to AuditPermission.SAFE),
    PHONE_DEVICE_INFO_TOOL to (ExecutionTarget.PHONE to AuditPermission.SAFE),
    PHONE_FLASHLIGHT_SET_TOOL to (ExecutionTarget.PHONE to AuditPermission.CONFIRM),
    PHONE_NOTE_CREATE_TOOL to (ExecutionTarget.PHONE to AuditPermission.CONFIRM),
    PHONE_OCR_READ_TOOL to (ExecutionTarget.PHONE to AuditPermission.SAFE),
    PHONE_QR_READ_TOOL to (ExecutionTarget.PHONE to AuditPermission.SAFE),
    PHONE_TIMER_CREATE_TOOL to (ExecutionTarget.PHONE to AuditPermission.CONFIRM),
)
internal val ALLOWLISTED_TOOL_NAMES = AUDIT_CAPABILITY_CONTRACTS.keys
