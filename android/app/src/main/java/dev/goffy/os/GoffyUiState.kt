package dev.goffy.os

enum class MacConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
}

enum class ExecutionTarget {
    PHONE,
    MAC,
    CLOUD,
}

data class TimelineEntry(
    val command: String,
    val status: String,
)

data class GoffyUiState(
    val macConnection: MacConnectionState = MacConnectionState.DISCONNECTED,
    val executionTarget: ExecutionTarget = ExecutionTarget.MAC,
    val timeline: List<TimelineEntry> = emptyList(),
) {
    fun queueCommand(command: String, waitingStatus: String): GoffyUiState {
        val normalized = command.trim()
        if (normalized.isEmpty()) return this

        return copy(
            timeline = (timeline + TimelineEntry(normalized, waitingStatus)).takeLast(MAX_TIMELINE_ITEMS),
        )
    }

    private companion object {
        const val MAX_TIMELINE_ITEMS = 50
    }
}
