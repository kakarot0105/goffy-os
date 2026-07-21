package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.protocol.ExecutionTarget

internal enum class GoffyOrbMode {
    IDLE,
    LISTENING,
    PHONE_ROUTE,
    MAC_ROUTE,
    CLOUD_ROUTE,
    APPROVAL,
    VERIFIED,
    ATTENTION,
}

internal data class GoffyOrbUiModel(
    val mode: GoffyOrbMode,
    val target: ExecutionTarget,
    val phase: TaskPhase?,
    val hasActiveTask: Boolean,
)

internal fun GoffyUiState.toGoffyOrbUiModel(
    voiceInputState: GoffyVoiceInputState,
): GoffyOrbUiModel {
    val activeEntry = timeline.activeTaskId?.let { activeTaskId ->
        timeline.entries.lastOrNull { it.id == activeTaskId }
    }
    val latestEntry = timeline.entries.lastOrNull()
    val visibleEntry = activeEntry ?: latestEntry
    val target = visibleEntry?.executionTarget ?: executionTarget
    val mode = when {
        voiceInputState.listening -> GoffyOrbMode.LISTENING
        pendingApproval != null || activeEntry?.phase == TaskPhase.AWAITING_APPROVAL ->
            GoffyOrbMode.APPROVAL
        activeEntry != null -> target.toActiveRouteMode()
        latestEntry?.phase == TaskPhase.VERIFIED -> GoffyOrbMode.VERIFIED
        latestEntry?.phase in attentionPhases -> GoffyOrbMode.ATTENTION
        else -> GoffyOrbMode.IDLE
    }
    return GoffyOrbUiModel(
        mode = mode,
        target = target,
        phase = visibleEntry?.phase,
        hasActiveTask = activeEntry != null,
    )
}

private fun ExecutionTarget.toActiveRouteMode(): GoffyOrbMode = when (this) {
    ExecutionTarget.PHONE -> GoffyOrbMode.PHONE_ROUTE
    ExecutionTarget.MAC -> GoffyOrbMode.MAC_ROUTE
    ExecutionTarget.CLOUD -> GoffyOrbMode.CLOUD_ROUTE
}

private val attentionPhases = setOf(
    TaskPhase.UNVERIFIED,
    TaskPhase.FAILED,
    TaskPhase.CANCELLED,
)
