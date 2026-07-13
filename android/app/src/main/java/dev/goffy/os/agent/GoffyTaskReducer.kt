package dev.goffy.os.agent

import dev.goffy.os.protocol.HubStreamEvent
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.ExecutionTarget
import java.util.UUID

enum class TaskPhase {
    ROUTING,
    CONNECTING,
    ACCEPTED,
    COMPLETED_UNVERIFIED,
    VERIFIED,
    FAILED,
    CANCELLED,
}

enum class TaskEventKind {
    OBSERVE,
    PLAN,
    CONNECT,
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
    val result: MacSystemInfo? = null,
    val verificationSummary: String? = null,
    val verificationChecks: List<String> = emptyList(),
    val lastProgressSequence: Int? = null,
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

    fun apply(taskId: UUID, event: HubStreamEvent): TaskTimelineState {
        if (taskId != activeTaskId) return this
        val index = entries.indexOfLast { it.id == taskId }
        if (index < 0) return copy(activeTaskId = null)

        val current = entries[index]
        val updated = when (event) {
            is HubStreamEvent.Connecting -> current.copy(
                phase = TaskPhase.CONNECTING,
                summary = if (event.attempt == 1) "Connecting to GOFFY Hub" else "Reconnecting safely",
            ).withEvent(
                TaskEventKind.CONNECT,
                "Connection attempt ${event.attempt}",
            )

            HubStreamEvent.Connected -> current.copy(
                phase = TaskPhase.CONNECTING,
                summary = "Connected; invocation sent",
            ).withEvent(TaskEventKind.CONNECT, "Authenticated WebSocket connected")

            is HubStreamEvent.Progress -> applyProgress(current, event)
            is HubStreamEvent.Result -> applyResult(current, event)
            is HubStreamEvent.Verification -> applyVerification(current, event)
            is HubStreamEvent.Error -> current.copy(
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
            summary = "Cancelled locally; Hub completion is not guaranteed",
        ).withEvent(TaskEventKind.ERROR, "User cancelled the local connection")
        return copy(
            activeTaskId = null,
            entries = entries.toMutableList().also { it[index] = updated },
        )
    }

    private fun applyProgress(
        current: TaskTimelineEntry,
        event: HubStreamEvent.Progress,
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
            progress.stage == "accepted" && current.phase == TaskPhase.CONNECTING && progress.sequence == 0 -> {
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
        event: HubStreamEvent.Result,
    ): TaskTimelineEntry {
        if (current.phase != TaskPhase.COMPLETED_UNVERIFIED ||
            event.toolName != current.toolName ||
            event.executionTarget != current.executionTarget ||
            current.result != null
        ) {
            return current.failSequence("Tool result arrived outside the expected sequence")
        }
        return current.copy(
            phase = TaskPhase.COMPLETED_UNVERIFIED,
            summary = "Result received; waiting for verification",
            result = event.content,
        ).withEvent(
            TaskEventKind.RESULT,
            "${event.content.operatingSystem} ${event.content.architecture}: ${event.content.status}",
        )
    }

    private fun applyVerification(
        current: TaskTimelineEntry,
        event: HubStreamEvent.Verification,
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

    private companion object {
        const val MAX_TIMELINE_ITEMS = 50
        const val MAX_TASK_EVENTS = 16
        const val MAX_VERIFICATION_CHECKS = 16
        const val MAX_COMMAND_LENGTH = 2_000
        val TERMINAL_PHASES = setOf(TaskPhase.VERIFIED, TaskPhase.FAILED, TaskPhase.CANCELLED)
    }
}

private fun String.safeText(): String = trim().take(256).ifEmpty { "No details available" }
