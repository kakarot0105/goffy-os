package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GIT_STATUS_TOOL
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.MAC_FILES_LIST_TOOL
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.MacFilesList
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.ToolResultContent
import dev.goffy.os.protocol.matchesToolContract
import dev.goffy.os.localmodel.LocalModelIntentObservation
import java.util.Locale
import java.util.UUID

enum class TaskPhase {
    ROUTING,
    AWAITING_APPROVAL,
    PREPARING,
    ACCEPTED,
    COMPLETED_UNVERIFIED,
    UNVERIFIED,
    VERIFIED,
    FAILED,
    CANCELLED,
}

enum class TaskEventKind {
    OBSERVE,
    PLAN,
    AUTHORIZE,
    PREPARE,
    TOOL,
    RESULT,
    VERIFY,
    ERROR,
}

data class TaskTimelineEvent(
    val kind: TaskEventKind,
    val message: String,
)

data class TaskTimelineEntry(
    val id: UUID,
    val command: String,
    val executionTarget: ExecutionTarget,
    val toolName: String?,
    val phase: TaskPhase,
    val summary: String,
    val events: List<TaskTimelineEvent>,
    val result: ToolResultContent? = null,
    val verificationSummary: String? = null,
    val verificationChecks: List<String> = emptyList(),
    val lastProgressSequence: Int? = null,
    val lastStartAttempt: Int? = null,
    val executionReady: Boolean = false,
    val permission: PermissionLevel? = null,
    val approvalGranted: Boolean = false,
    val terminalAtEpochMillis: Long? = null,
    val auditRecordedAtEpochMillis: Long? = null,
)

data class TaskTimelineState(
    val activeTaskId: UUID? = null,
    val entries: List<TaskTimelineEntry> = emptyList(),
) {
    fun mergeRestoredAudit(restoredEntries: List<TaskTimelineEntry>): TaskTimelineState {
        require(
            restoredEntries.all {
                it.phase in TERMINAL_PHASES &&
                    it.result == null &&
                    !it.approvalGranted &&
                    it.lastProgressSequence == null &&
                    it.lastStartAttempt == null &&
                    !it.executionReady &&
                    it.terminalAtEpochMillis != null
            },
        ) {
            "restored audit entries must be terminal, display-only, and authority-free"
        }
        val merged = LinkedHashMap<UUID, TaskTimelineEntry>()
        restoredEntries.forEach { merged[it.id] = it }
        entries.forEach { merged[it.id] = it }
        return copy(entries = merged.values.toList().takeLast(MAX_TIMELINE_ITEMS))
    }

    fun markAuditRecorded(taskId: UUID, recordedAtEpochMillis: Long): TaskTimelineState {
        require(recordedAtEpochMillis > 0) { "audit timestamp must be positive" }
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0 || entries[index].phase !in TERMINAL_PHASES) return this
        return copy(
            entries = entries.toMutableList().also {
                it[index] = it[index].copy(auditRecordedAtEpochMillis = recordedAtEpochMillis)
            },
        )
    }

    fun start(taskId: UUID, plan: GoffyExecutionPlan): TaskTimelineState {
        require(activeTaskId == null) { "only one task may run at a time" }
        val entry = TaskTimelineEntry(
            id = taskId,
            command = plan.command,
            executionTarget = plan.executionTarget,
            toolName = plan.toolName,
            phase = TaskPhase.ROUTING,
            summary = "Deterministic route selected",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Received typed command input"),
                TaskTimelineEvent(
                    TaskEventKind.PLAN,
                    "Route ${plan.executionTarget.name} to ${plan.toolName} (${plan.permission.name})",
                ),
            ),
            permission = plan.permission,
        )
        return copy(
            activeTaskId = taskId,
            entries = (entries + entry).takeLast(MAX_TIMELINE_ITEMS),
        )
    }

    fun reject(
        command: String,
        summary: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
        executionTarget: ExecutionTarget = ExecutionTarget.PHONE,
        toolName: String? = null,
        permission: PermissionLevel? = null,
    ): TaskTimelineState {
        val normalized = command.trim().take(MAX_COMMAND_LENGTH)
        if (normalized.isEmpty()) return this
        val entry = TaskTimelineEntry(
            id = UUID.randomUUID(),
            command = normalized,
            executionTarget = executionTarget,
            toolName = toolName,
            phase = TaskPhase.FAILED,
            summary = summary.safeText(),
            events = listOf(TaskTimelineEvent(TaskEventKind.ERROR, summary.safeText())),
            permission = permission,
            terminalAtEpochMillis = terminalAtEpochMillis,
        )
        return copy(entries = (entries + entry).takeLast(MAX_TIMELINE_ITEMS))
    }

    fun startLocalModelObservation(
        taskId: UUID,
        command: String,
        statusSummary: String,
    ): TaskTimelineState {
        require(activeTaskId == null) { "only one task may run at a time" }
        val normalized = command.trim().take(MAX_COMMAND_LENGTH)
        if (normalized.isEmpty()) return this
        val entry = TaskTimelineEntry(
            id = taskId,
            command = normalized,
            executionTarget = ExecutionTarget.PHONE,
            toolName = null,
            phase = TaskPhase.ROUTING,
            summary = "Checking local model observe-only fallback",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Received typed command input"),
                TaskTimelineEvent(TaskEventKind.PLAN, "No deterministic route selected"),
                TaskTimelineEvent(TaskEventKind.PREPARE, statusSummary.safeText()),
            ),
            permission = null,
        )
        return copy(
            activeTaskId = taskId,
            entries = (entries + entry).takeLast(MAX_TIMELINE_ITEMS),
        )
    }

    fun completeLocalModelObservation(
        taskId: UUID,
        observation: LocalModelIntentObservation,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val current = entries[index]
        val summary = observation.nonExecutableSummary()
        val events = when (observation) {
            is LocalModelIntentObservation.Candidate -> listOf(
                TaskTimelineEvent(
                    TaskEventKind.PLAN,
                    "Local model suggested ${observation.candidate.intentLabel} " +
                        "at ${observation.candidate.confidence.displayConfidence()} confidence",
                ),
                TaskTimelineEvent(TaskEventKind.ERROR, "Deterministic route still required"),
            )
            is LocalModelIntentObservation.Disabled -> listOf(
                TaskTimelineEvent(TaskEventKind.ERROR, observation.reason),
            )
            is LocalModelIntentObservation.Rejected -> listOf(
                TaskTimelineEvent(TaskEventKind.ERROR, observation.reason),
            )
        }
        val updated = current.copy(
            phase = TaskPhase.FAILED,
            summary = summary.safeText(),
            terminalAtEpochMillis = terminalAtEpochMillis,
        ).copy(events = (current.events + events).takeLast(MAX_TASK_EVENTS))
        return copy(
            activeTaskId = null,
            entries = entries.toMutableList().also { it[index] = updated },
        )
    }

    fun apply(
        taskId: UUID,
        event: ExecutionEvent,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)

        val current = entries[index]
        val updated = when (event) {
            is ExecutionEvent.Starting -> applyStarting(current, event)
            ExecutionEvent.Ready -> applyReady(current)

            is ExecutionEvent.Progress -> applyProgress(current, event)
            is ExecutionEvent.Result -> applyResult(current, event)
            is ExecutionEvent.Verification -> applyVerification(current, event)
            is ExecutionEvent.Unverified -> applyUnverified(current, event)
            is ExecutionEvent.Error -> current.copy(
                phase = TaskPhase.FAILED,
                summary = event.message.safeText(),
            ).withEvent(TaskEventKind.ERROR, "${event.code}: ${event.message}")
        }

        val terminalEntry = updated.withTerminalTimestamp(terminalAtEpochMillis)
        val terminal = terminalEntry.phase in TERMINAL_PHASES
        return copy(
            activeTaskId = if (terminal) null else activeTaskId,
            entries = entries.toMutableList().also { it[index] = terminalEntry },
        )
    }

    fun awaitApproval(
        taskId: UUID,
        summary: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val current = entries[index]
        val updated = if (
            current.phase == TaskPhase.ROUTING &&
            current.permission == PermissionLevel.CONFIRM &&
            !current.approvalGranted
        ) {
            current.copy(
                phase = TaskPhase.AWAITING_APPROVAL,
                summary = summary.safeText(),
            ).withEvent(TaskEventKind.AUTHORIZE, "Waiting for explicit one-time approval")
        } else {
            current.failSequence("Approval request failed task ordering checks")
        }
        return replaceEntry(index, updated.withTerminalTimestamp(terminalAtEpochMillis))
    }

    fun grantApproval(
        taskId: UUID,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val current = entries[index]
        val updated = if (
            current.phase == TaskPhase.AWAITING_APPROVAL &&
            current.permission == PermissionLevel.CONFIRM &&
            !current.approvalGranted
        ) {
            current.copy(
                phase = TaskPhase.ROUTING,
                summary = "Approved once; preparing local execution",
                approvalGranted = true,
            ).withEvent(TaskEventKind.AUTHORIZE, "User approved one execution")
        } else {
            current.failSequence("Approval grant failed task ordering checks")
        }
        return replaceEntry(index, updated.withTerminalTimestamp(terminalAtEpochMillis))
    }

    fun denyApproval(
        taskId: UUID,
        summary: String,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val current = entries[index]
        if (current.phase != TaskPhase.AWAITING_APPROVAL) return this
        val updated = current.copy(
            phase = TaskPhase.CANCELLED,
            summary = summary.safeText(),
        ).withEvent(TaskEventKind.AUTHORIZE, summary)
        return replaceEntry(index, updated.withTerminalTimestamp(terminalAtEpochMillis))
    }

    fun expireApproval(
        taskId: UUID,
        terminalAtEpochMillis: Long = System.currentTimeMillis(),
    ): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val current = entries[index]
        if (current.phase != TaskPhase.AWAITING_APPROVAL) return this
        val summary = "Approval expired; no phone tool was invoked"
        val updated = current.copy(
            phase = TaskPhase.FAILED,
            summary = summary,
        ).withEvent(TaskEventKind.ERROR, summary)
        return replaceEntry(index, updated.withTerminalTimestamp(terminalAtEpochMillis))
    }

    fun cancelActive(terminalAtEpochMillis: Long = System.currentTimeMillis()): TaskTimelineState {
        val taskId = activeTaskId ?: return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val updated = entries[index].copy(
            phase = TaskPhase.CANCELLED,
            summary = entries[index].cancellationSummary(),
        ).withEvent(
            TaskEventKind.ERROR,
            entries[index].cancellationEventMessage(),
        ).withTerminalTimestamp(terminalAtEpochMillis)
        return copy(
            activeTaskId = null,
            entries = entries.toMutableList().also { it[index] = updated },
        )
    }

    private fun applyProgress(
        current: TaskTimelineEntry,
        event: ExecutionEvent.Progress,
    ): TaskTimelineEntry {
        val progress = event.payload
        val expectedSequence = (current.lastProgressSequence ?: -1) + 1
        if (progress.toolName != current.toolName ||
            progress.executionTarget != current.executionTarget ||
            progress.sequence != expectedSequence
        ) {
            return current.failSequence("Progress event failed task ordering checks")
        }
        val phase = when {
            progress.stage == "accepted" &&
                current.phase == TaskPhase.PREPARING &&
                current.executionReady &&
                progress.sequence == 0 -> {
                TaskPhase.ACCEPTED
            }
            progress.stage == "completed" && current.phase == TaskPhase.ACCEPTED -> {
                TaskPhase.COMPLETED_UNVERIFIED
            }
            else -> return current.failSequence("Progress event arrived outside the expected sequence")
        }
        return current.copy(
            phase = phase,
            summary = progress.message.safeText(),
            lastProgressSequence = progress.sequence,
        ).withEvent(TaskEventKind.TOOL, "${progress.stage}: ${progress.message}")
    }

    private fun applyResult(
        current: TaskTimelineEntry,
        event: ExecutionEvent.Result,
    ): TaskTimelineEntry {
        if (current.phase != TaskPhase.COMPLETED_UNVERIFIED ||
            event.toolName != current.toolName ||
            event.executionTarget != current.executionTarget ||
            !current.acceptsContent(event.content) ||
            current.result != null
        ) {
            return current.failSequence("Tool result arrived outside the expected sequence")
        }
        return current.copy(
            phase = TaskPhase.COMPLETED_UNVERIFIED,
            summary = event.content.summaryText().safeText(),
            result = event.content,
        ).withEvent(
            TaskEventKind.RESULT,
            event.content.summaryText(),
        )
    }

    private fun applyVerification(
        current: TaskTimelineEntry,
        event: ExecutionEvent.Verification,
    ): TaskTimelineEntry {
        if (current.phase != TaskPhase.COMPLETED_UNVERIFIED || current.result == null) {
            return current.failSequence("Verification arrived before a structured result")
        }
        return current.copy(
            phase = if (event.succeeded) TaskPhase.VERIFIED else TaskPhase.FAILED,
            summary = event.summary.safeText(),
            verificationSummary = event.summary.safeText(),
            verificationChecks = event.checks.take(MAX_VERIFICATION_CHECKS),
        ).withEvent(
            if (event.succeeded) TaskEventKind.VERIFY else TaskEventKind.ERROR,
            event.summary,
        )
    }

    private fun applyUnverified(
        current: TaskTimelineEntry,
        event: ExecutionEvent.Unverified,
    ): TaskTimelineEntry {
        if (current.phase != TaskPhase.COMPLETED_UNVERIFIED || current.result == null) {
            return current.failSequence("Unverified completion arrived before a structured result")
        }
        return current.copy(
            phase = TaskPhase.UNVERIFIED,
            summary = event.summary.safeText(),
            verificationSummary = event.summary.safeText(),
            verificationChecks = event.checks.take(MAX_VERIFICATION_CHECKS),
        ).withEvent(TaskEventKind.VERIFY, event.summary)
    }

    private fun TaskTimelineEntry.failSequence(message: String): TaskTimelineEntry = copy(
        phase = TaskPhase.FAILED,
        summary = message,
    ).withEvent(TaskEventKind.ERROR, message)

    private fun TaskTimelineEntry.withTerminalTimestamp(timestamp: Long): TaskTimelineEntry =
        if (phase in TERMINAL_PHASES && terminalAtEpochMillis == null) {
            copy(terminalAtEpochMillis = timestamp)
        } else {
            this
        }

    private fun TaskTimelineEntry.withEvent(
        kind: TaskEventKind,
        message: String,
    ): TaskTimelineEntry = copy(
        events = (events + TaskTimelineEvent(kind, message.safeText())).takeLast(MAX_TASK_EVENTS),
    )

    private fun applyStarting(
        current: TaskTimelineEntry,
        event: ExecutionEvent.Starting,
    ): TaskTimelineEntry {
        val expectedAttempt = (current.lastStartAttempt ?: 0) + 1
        if (event.attempt != expectedAttempt ||
            current.phase !in setOf(TaskPhase.ROUTING, TaskPhase.PREPARING) ||
            current.lastProgressSequence != null ||
            (current.permission == PermissionLevel.CONFIRM && !current.approvalGranted)
        ) {
            return current.failSequence("Execution start event failed ordering checks")
        }
        return current.copy(
            phase = TaskPhase.PREPARING,
            summary = current.startingSummary(event.attempt),
            lastStartAttempt = event.attempt,
            executionReady = false,
        ).withEvent(TaskEventKind.PREPARE, current.startingEventMessage(event.attempt))
    }

    private fun applyReady(current: TaskTimelineEntry): TaskTimelineEntry {
        if (current.phase != TaskPhase.PREPARING ||
            current.lastStartAttempt == null ||
            current.executionReady
        ) {
            return current.failSequence("Execution ready event failed ordering checks")
        }
        return current.copy(
            summary = current.readySummary(),
            executionReady = true,
        ).withEvent(TaskEventKind.PREPARE, current.readyEventMessage())
    }

    private fun TaskTimelineEntry.acceptsContent(content: ToolResultContent): Boolean = when (toolName) {
        GIT_STATUS_TOOL -> executionTarget == ExecutionTarget.MAC &&
            content is GitStatus &&
            content.matchesToolContract()
        MAC_FILES_LIST_TOOL -> executionTarget == ExecutionTarget.MAC &&
            content is MacFilesList &&
            content.matchesToolContract()
        MAC_SYSTEM_INFO_TOOL -> executionTarget == ExecutionTarget.MAC && content is MacSystemInfo
        PHONE_BATTERY_STATUS_TOOL -> executionTarget == ExecutionTarget.PHONE &&
            content is PhoneBatteryStatus &&
            content.matchesToolContract()
        PHONE_DEVICE_INFO_TOOL -> executionTarget == ExecutionTarget.PHONE &&
            content is PhoneDeviceInfo &&
            content.matchesToolContract()
        PHONE_FLASHLIGHT_SET_TOOL -> executionTarget == ExecutionTarget.PHONE &&
            permission == PermissionLevel.CONFIRM &&
            approvalGranted &&
            content is PhoneFlashlightState
        PHONE_NOTE_CREATE_TOOL -> executionTarget == ExecutionTarget.PHONE &&
            permission == PermissionLevel.CONFIRM &&
            approvalGranted &&
            content is PhoneNoteCreated &&
            content.matchesToolContract()
        PHONE_TIMER_CREATE_TOOL -> executionTarget == ExecutionTarget.PHONE &&
            permission == PermissionLevel.CONFIRM &&
            approvalGranted &&
            content is PhoneTimerDispatched &&
            content.matchesToolContract()
        else -> false
    }

    private fun replaceEntry(index: Int, updated: TaskTimelineEntry): TaskTimelineState = copy(
        activeTaskId = if (updated.phase in TERMINAL_PHASES) null else activeTaskId,
        entries = entries.toMutableList().also { it[index] = updated },
    )

    private fun TaskTimelineEntry.startingSummary(attempt: Int): String = when (executionTarget) {
        ExecutionTarget.MAC ->
            if (attempt == 1) "Starting MAC Hub connection" else "Retrying MAC Hub connection safely"
        ExecutionTarget.PHONE ->
            if (attempt == 1) "Starting local PHONE execution" else "Retrying local PHONE execution safely"
        ExecutionTarget.CLOUD ->
            if (attempt == 1) "Starting CLOUD execution" else "Retrying CLOUD execution safely"
    }

    private fun TaskTimelineEntry.startingEventMessage(attempt: Int): String = when (executionTarget) {
        ExecutionTarget.MAC -> "MAC Hub start attempt $attempt"
        ExecutionTarget.PHONE -> "PHONE local start attempt $attempt"
        ExecutionTarget.CLOUD -> "CLOUD start attempt $attempt"
    }

    private fun TaskTimelineEntry.readySummary(): String = when (executionTarget) {
        ExecutionTarget.MAC -> "MAC capability compatible; invocation sent"
        ExecutionTarget.PHONE -> "PHONE local execution ready"
        ExecutionTarget.CLOUD -> "CLOUD execution ready"
    }

    private fun TaskTimelineEntry.readyEventMessage(): String = when (executionTarget) {
        ExecutionTarget.MAC -> "Authenticated MAC Hub capability discovered and compatible"
        ExecutionTarget.PHONE -> "PHONE local execution ready"
        ExecutionTarget.CLOUD -> "CLOUD execution ready"
    }

    private fun TaskTimelineEntry.cancellationSummary(): String =
        if (phase == TaskPhase.AWAITING_APPROVAL) {
            "Approval cancelled; no phone tool was invoked"
        } else if (permission == PermissionLevel.CONFIRM && lastStartAttempt != null) {
            "Cancellation requested; confirmed action completion is not guaranteed"
        } else when (executionTarget) {
            ExecutionTarget.MAC -> "Cancelled locally; Hub completion is not guaranteed"
            ExecutionTarget.PHONE -> "Local PHONE execution cancelled"
            ExecutionTarget.CLOUD -> "Cancelled locally; remote completion is not guaranteed"
        }

    private fun TaskTimelineEntry.cancellationEventMessage(): String =
        if (phase == TaskPhase.AWAITING_APPROVAL) {
            "User cancelled before approval; no phone tool was invoked"
        } else if (permission == PermissionLevel.CONFIRM && lastStartAttempt != null) {
            "User requested cancellation after confirmed execution started"
        } else when (executionTarget) {
            ExecutionTarget.MAC -> "User cancelled the local Hub connection"
            ExecutionTarget.PHONE -> "User cancelled local PHONE execution"
            ExecutionTarget.CLOUD -> "User cancelled the local request"
        }

    private companion object {
        const val MAX_TIMELINE_ITEMS = 50
        const val MAX_TASK_EVENTS = 16
        const val MAX_VERIFICATION_CHECKS = 16
        const val MAX_COMMAND_LENGTH = 2_000
        val TERMINAL_PHASES = setOf(
            TaskPhase.UNVERIFIED,
            TaskPhase.VERIFIED,
            TaskPhase.FAILED,
            TaskPhase.CANCELLED,
        )
    }
}

private fun String.safeText(): String = trim().take(256).ifEmpty { "No details available" }

private fun LocalModelIntentObservation.nonExecutableSummary(): String = when (this) {
    is LocalModelIntentObservation.Candidate ->
        "Local model suggested ${candidate.intentLabel}, but GOFFY needs a deterministic route before execution"
    is LocalModelIntentObservation.Disabled ->
        "No safe deterministic route is available for this command yet. $reason"
    is LocalModelIntentObservation.Rejected ->
        "No safe deterministic route is available for this command yet. $reason"
}

private fun Float.displayConfidence(): String = String.format(Locale.US, "%.2f", this)

private fun ToolResultContent.summaryText(): String = when (this) {
    is GitStatus -> gitStatusSummary()
    is MacFilesList -> macFilesSummary()
    is MacSystemInfo -> "$operatingSystem $architecture: $status"
    is PhoneBatteryStatus -> "Battery $levelPercent%: ${if (charging) "charging" else "not charging"}"
    is PhoneDeviceInfo -> deviceInfoSummary()
    is PhoneFlashlightState ->
        "Flashlight ${if (enabled) "on" else "off"}; state observed" +
            if (stateChanged) " after state change" else " (already requested state)"
    is PhoneNoteCreated -> "Note #$noteId stored: $text"
    is PhoneTimerDispatched -> "Timer intent for $durationSeconds seconds dispatched to $clockPackage"
}

private fun GitStatus.gitStatusSummary(): String {
    val changeCount = stagedCount + unstagedCount + untrackedCount + conflictCount
    val branchLabel = branch?.let { " on $it" } ?: ""
    val truncatedLabel = if (truncated) " (truncated)" else ""
    return if (clean) {
        "Git repo $repoName$branchLabel is clean"
    } else {
        "Git repo $repoName$branchLabel has $changeCount status changes$truncatedLabel"
    }
}

private fun MacFilesList.macFilesSummary(): String {
    val pathLabel = relativePath.ifBlank { rootName }
    val truncatedLabel = if (truncated) " (truncated)" else ""
    return "${entries.size} Mac file entries in $pathLabel$truncatedLabel"
}

private fun PhoneDeviceInfo.deviceInfoSummary(): String {
    val homeStatus = when {
        goffyDefaultHome -> "default"
        goffyHomeCandidate -> "available"
        else -> "not available"
    }
    val systemStatus = if (goffySystemApp) "yes" else "no"
    return "$manufacturer $model / Android $androidRelease (API $sdkInt); " +
        "GOFFY home=$homeStatus, system=$systemStatus"
}
