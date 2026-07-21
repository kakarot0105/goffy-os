package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.ToolResultContent
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffySpeechTextTest {
    private val endpoint = "wss://mac.example/ws/v1"

    @Test
    fun latestSpeakableTextUsesNewestVerifiedResult() {
        val oldBattery = entry(
            toolName = PHONE_BATTERY_STATUS_TOOL,
            target = ExecutionTarget.PHONE,
            result = PhoneBatteryStatus(levelPercent = 20, charging = false),
        )
        val latestMac = entry(
            toolName = MAC_SYSTEM_INFO_TOOL,
            target = ExecutionTarget.MAC,
            result = MacSystemInfo(
                status = "available",
                operatingSystem = "Darwin",
                architecture = "arm64",
            ),
        )
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(entries = listOf(oldBattery, latestMac)),
        )

        assertEquals(
            "Mac status is available. System: Darwin on arm64.",
            state.latestSpeakableText(),
        )
    }

    @Test
    fun privateNoteTextIsNeverSpoken() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = PHONE_NOTE_CREATE_TOOL,
                        target = ExecutionTarget.PHONE,
                        permission = PermissionLevel.CONFIRM,
                        result = PhoneNoteCreated(
                            noteId = 7,
                            text = "secret launch phrase",
                            createdAtEpochMillis = 1_720_000_000_000,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("Private note 7"))
        assertTrue(speechText.contains("will not read the note text aloud"))
        assertFalse(speechText.contains("secret launch phrase"))
    }

    @Test
    fun missingOrNonTerminalResultIsNotSpeakable() {
        val withoutResult = entry(
            toolName = PHONE_BATTERY_STATUS_TOOL,
            target = ExecutionTarget.PHONE,
            result = null,
        )
        val activeResult = entry(
            toolName = PHONE_BATTERY_STATUS_TOOL,
            target = ExecutionTarget.PHONE,
            phase = TaskPhase.PREPARING,
            result = PhoneBatteryStatus(levelPercent = 88, charging = true),
        )
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(entries = listOf(withoutResult, activeResult)),
        )

        assertNull(state.latestSpeakableText())
    }

    @Test
    fun speakableTextIsWhitespaceNormalizedAndBounded() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = MAC_SYSTEM_INFO_TOOL,
                        target = ExecutionTarget.MAC,
                        result = MacSystemInfo(
                            status = "available\nnow",
                            operatingSystem = "Darwin\t${"x".repeat(700)}",
                            architecture = "arm64",
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertFalse(speechText.contains("\n"))
        assertFalse(speechText.contains("\t"))
        assertTrue(speechText.length <= 480)
    }

    private fun entry(
        toolName: String,
        target: ExecutionTarget,
        result: ToolResultContent?,
        phase: TaskPhase = TaskPhase.VERIFIED,
        permission: PermissionLevel = PermissionLevel.SAFE,
    ): TaskTimelineEntry = TaskTimelineEntry(
        id = UUID.randomUUID(),
        command = "test command",
        executionTarget = target,
        toolName = toolName,
        phase = phase,
        summary = "test summary",
        events = emptyList(),
        result = result,
        permission = permission,
    )
}
