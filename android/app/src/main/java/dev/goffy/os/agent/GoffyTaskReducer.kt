package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.ToolResultContent
import java.util.UUID

enum class TaskPhase {
    ROUTING,
    PREPARING,
    ACCEPTED,
    COMPLETED_UNVERIFIED,
    VERIFIED,
    FAILED,
    CANCELLED,
}

enum class TaskEventKind {
    OBSERVE,
    PLAN,
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
)

data class TaskTimelineState(
    val activeTaskId: UUID? = null,
    val entries: List<TaskTimelineEntry> = emptyList(),
) {
    fun start(taskId: UUID, plan: GoffyExecutionPlan): TaskTimelineState {
        require(activeTaskId == null) { "only one task may run at a time" }
        val entry = TaskTimelineEntry(
            id = taskId,
            command = plan.command,
            executionTarget = plan.executionTarget,
            toolName = plan.toolName,
            phase = TaskPhase.ROUTING,
            summary = "Safe deterministic route selected",
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

    fun reject(command: String, summary: String): TaskTimelineState {
        val normalized = command.trim().take(MAX_COMMAND_LENGTH)
        if (normalized.isEmpty()) return this
        val entry = TaskTimelineEntry(
            id = UUID.randomUUID(),
            command = normalized,
            executionTarget = ExecutionTarget.PHONE,
            toolName = null,
            phase = TaskPhase.FAILED,
            summary = summary.safeText(),
            events = listOf(TaskTimelineEvent(TaskEventKind.ERROR, summary.safeText())),
        )
        return copy(entries = (entries + entry).takeLast(MAX_TIMELINE_ITEMS))
    }

    fun apply(taskId: UUID, event: ExecutionEvent): TaskTimelineState {
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
            is ExecutionEvent.Error -> current.copy(
                phase = TaskPhase.FAILED,
                summary = event.message.safeText(),
            ).withEvent(TaskEventKind.ERROR, "${event.code}: ${event.message}")
        }

        val terminal = updated.phase in TERMINAL_PHASES
        return copy(
            activeTaskId = if (terminal) null else activeTaskId,
            entries = entries.toMutableList().also { it[index] = updated },
        )
    }

    fun cancelActive(): TaskTimelineState {
        val taskId = activeTaskId ?: return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)
        val updated = entries[index].copy(
            phase = TaskPhase.CANCELLED,
            summary = entries[index].cancellationSummary(),
        ).withEvent(TaskEventKind.ERROR, entries[index].cancellationEventMessage())
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
            summary = event.content.summaryText(),
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

    private fun TaskTimelineEntry.failSequence(message: String): TaskTimelineEntry = copy(
        phase = TaskPhase.FAILED,
        summary = message,
    ).withEvent(TaskEventKind.ERROR, message)

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
            current.lastProgressSequence != null
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
        MAC_SYSTEM_INFO_TOOL -> executionTarget == ExecutionTarget.MAC && content is MacSystemInfo
        PHONE_BATTERY_STATUS_TOOL -> executionTarget == ExecutionTarget.PHONE &&
            content is PhoneBatteryStatus &&
            content.levelPercent in 0..100
        else -> false
    }

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
        ExecutionTarget.MAC -> "MAC Hub ready; invocation sent"
        ExecutionTarget.PHONE -> "PHONE local execution ready"
        ExecutionTarget.CLOUD -> "CLOUD execution ready"
    }

    private fun TaskTimelineEntry.readyEventMessage(): String = when (executionTarget) {
        ExecutionTarget.MAC -> "Authenticated MAC Hub connection ready"
        ExecutionTarget.PHONE -> "PHONE local execution ready"
        ExecutionTarget.CLOUD -> "CLOUD execution ready"
    }

    private fun TaskTimelineEntry.cancellationSummary(): String = when (executionTarget) {
        ExecutionTarget.MAC -> "Cancelled locally; Hub completion is not guaranteed"
        ExecutionTarget.PHONE -> "Local PHONE execution cancelled"
        ExecutionTarget.CLOUD -> "Cancelled locally; remote completion is not guaranteed"
    }

    private fun TaskTimelineEntry.cancellationEventMessage(): String = when (executionTarget) {
        ExecutionTarget.MAC -> "User cancelled the local Hub connection"
        ExecutionTarget.PHONE -> "User cancelled local PHONE execution"
        ExecutionTarget.CLOUD -> "User cancelled the local request"
    }

    private companion object {
        const val MAX_TIMELINE_ITEMS = 50
        const val MAX_TASK_EVENTS = 16
        const val MAX_VERIFICATION_CHECKS = 16
        const val MAX_COMMAND_LENGTH = 2_000
        val TERMINAL_PHASES = setOf(TaskPhase.VERIFIED, TaskPhase.FAILED, TaskPhase.CANCELLED)
    }
}

private fun String.safeText(): String = trim().take(256).ifEmpty { "No details available" }

private fun ToolResultContent.summaryText(): String = when (this) {
    is MacSystemInfo -> "$operatingSystem $architecture: $status"
    is PhoneBatteryStatus -> "Battery $levelPercent%: ${if (charging) "charging" else "not charging"}"
}
