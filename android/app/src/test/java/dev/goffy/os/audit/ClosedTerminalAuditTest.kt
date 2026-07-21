package dev.goffy.os.audit

import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GIT_STATUS_TOOL
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.GitStatusApprovedRepo
import dev.goffy.os.protocol.GitStatusChange
import dev.goffy.os.protocol.MAC_CLIPBOARD_READ_TOOL
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PHONE_OCR_READ_TOOL
import dev.goffy.os.protocol.PHONE_QR_READ_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PhoneNoteCreated
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class ClosedTerminalAuditTest {
    @Test
    fun projectionRedactsSecretNoteTextAndRestoresDisplayOnlyTimelineEntry() {
        val secret = "Launch code 12345"
        val entry = terminalEntry(
            phase = TaskPhase.VERIFIED,
            summary = "Stored secret note: $secret",
            approvalGranted = true,
        )

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNotNull(record)
        assertFalse(record.toString().contains(secret))
        assertEquals(PHONE_NOTE_CREATE_TOOL, record?.toolName)
        assertEquals(AuditPermission.CONFIRM, record?.permission)
        assertEquals(TerminalAuditPhase.VERIFIED, record?.phase)
        assertEquals(AuditApprovalOutcome.APPROVED, record?.approvalOutcome)
        assertEquals(
            listOf(TaskEventKind.OBSERVE, TaskEventKind.AUTHORIZE, TaskEventKind.RESULT, TaskEventKind.VERIFY),
            record?.eventKinds,
        )

        val restored = requireNotNull(record).toTimelineEntry()
        assertEquals("Recorded private note task", restored.command)
        assertEquals(TaskPhase.VERIFIED, restored.phase)
        assertEquals(null, restored.result)
        assertEquals(PHONE_NOTE_CREATE_TOOL, restored.toolName)
        assertEquals(PermissionLevel.CONFIRM, restored.permission)
        assertFalse(restored.approvalGranted)
        assertEquals(1_720_000_000_000, restored.terminalAtEpochMillis)
        assertFalse(restored.toString().contains(secret))
        assertTrueNoSecret(restored.events.map { it.message }, secret)
    }

    @Test
    fun qrReadCapabilityIsPersistedAsSafeClosedAuditMetadata() {
        val entry = TaskTimelineEntry(
            id = UUID.fromString("22222222-2222-4222-8222-222222222222"),
            command = "Read foreground QR code",
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_QR_READ_TOOL,
            phase = TaskPhase.VERIFIED,
            summary = "QR code read as url: https://example.com/...",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Received foreground scanner input"),
                TaskTimelineEvent(TaskEventKind.RESULT, "Stored bounded QR summary"),
                TaskTimelineEvent(TaskEventKind.VERIFY, "Verified QR summary contract"),
            ),
            permission = PermissionLevel.SAFE,
            terminalAtEpochMillis = 1_720_000_000_000,
        )

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNotNull(record)
        assertEquals(PHONE_QR_READ_TOOL, record?.toolName)
        assertEquals(AuditPermission.SAFE, record?.permission)
        assertEquals(AuditApprovalOutcome.NOT_REQUIRED, record?.approvalOutcome)
        assertEquals("Recorded QR read task", record?.toTimelineEntry()?.command)
    }

    @Test
    fun ocrReadCapabilityIsPersistedAsSafeClosedAuditMetadata() {
        val entry = TaskTimelineEntry(
            id = UUID.fromString("33333333-3333-4333-8333-333333333333"),
            command = "Read foreground text",
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_OCR_READ_TOOL,
            phase = TaskPhase.VERIFIED,
            summary = "OCR read 2 lines",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Received foreground scanner input"),
                TaskTimelineEvent(TaskEventKind.RESULT, "Stored bounded OCR summary"),
                TaskTimelineEvent(TaskEventKind.VERIFY, "Verified OCR summary contract"),
            ),
            permission = PermissionLevel.SAFE,
            terminalAtEpochMillis = 1_720_000_000_000,
        )

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNotNull(record)
        assertEquals(PHONE_OCR_READ_TOOL, record?.toolName)
        assertEquals(AuditPermission.SAFE, record?.permission)
        assertEquals(AuditApprovalOutcome.NOT_REQUIRED, record?.approvalOutcome)
        assertEquals("Recorded OCR read task", record?.toTimelineEntry()?.command)
    }

    @Test
    fun rejectsUnsupportedVersionsAndImpossibleCapabilityMetadata() {
        val record = requireNotNull(
            terminalEntry(
                phase = TaskPhase.VERIFIED,
                summary = "Completed",
                approvalGranted = true,
            ).toClosedTerminalAuditRecord(1),
        )

        assertThrows(IllegalArgumentException::class.java) {
            record.copy(protocolVersion = "99.0.0")
        }
        assertThrows(IllegalArgumentException::class.java) {
            record.copy(executionTarget = ExecutionTarget.MAC)
        }
        assertThrows(IllegalArgumentException::class.java) {
            record.copy(permission = AuditPermission.SAFE)
        }
    }

    @Test
    fun nonterminalProjectionReturnsNull() {
        val entry = terminalEntry(phase = TaskPhase.PREPARING, summary = "Preparing secret")

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNull(record)
    }

    @Test
    fun noToolObserveOnlyTerminalEntryRoundTripsAsUnsupportedAuditRecord() {
        val entry = TaskTimelineEntry(
            id = UUID.fromString("22222222-2222-4222-8222-222222222222"),
            command = "open settings",
            executionTarget = ExecutionTarget.PHONE,
            toolName = null,
            phase = TaskPhase.FAILED,
            summary = "Local model suggested PHONE, but GOFFY needs a deterministic route before execution",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Received typed command input"),
                TaskTimelineEvent(TaskEventKind.PLAN, "No deterministic route selected"),
                TaskTimelineEvent(TaskEventKind.PREPARE, "Local model ready for observe-only fallback."),
                TaskTimelineEvent(TaskEventKind.ERROR, "Deterministic route still required"),
            ),
            permission = null,
        )

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNotNull(record)
        assertEquals(null, record?.toolName)
        assertEquals(null, record?.permission)
        assertEquals(TerminalAuditPhase.FAILED, record?.phase)
        assertEquals(AuditApprovalOutcome.NOT_REQUIRED, record?.approvalOutcome)
        assertEquals(
            listOf(TaskEventKind.OBSERVE, TaskEventKind.PLAN, TaskEventKind.PREPARE, TaskEventKind.ERROR),
            record?.eventKinds,
        )

        val restored = requireNotNull(record).toTimelineEntry()
        assertEquals("Recorded unsupported task", restored.command)
        assertEquals(TaskPhase.FAILED, restored.phase)
        assertEquals(null, restored.toolName)
        assertEquals(null, restored.permission)
        assertEquals(null, restored.result)
        assertFalse(restored.approvalGranted)
    }

    @Test
    fun gitStatusAuditRoundTripsAsDisplayOnlySafeMacTask() {
        val secretPath = "private-plan.txt"
        val entry = TaskTimelineEntry(
            id = UUID.fromString("33333333-3333-4333-8333-333333333333"),
            command = "Show my git status",
            executionTarget = ExecutionTarget.MAC,
            toolName = GIT_STATUS_TOOL,
            phase = TaskPhase.VERIFIED,
            summary = "Git repo goffy has private path $secretPath",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Observed $secretPath"),
                TaskTimelineEvent(TaskEventKind.RESULT, "Returned $secretPath"),
                TaskTimelineEvent(TaskEventKind.VERIFY, "Verified $secretPath"),
            ),
            result = GitStatus(
                status = "available",
                repoIndex = 0,
                repoName = "goffy",
                branch = "main",
                headOidShort = "0123456789abcdef",
                upstream = null,
                ahead = null,
                behind = null,
                clean = false,
                stagedCount = 0,
                unstagedCount = 0,
                untrackedCount = 1,
                conflictCount = 0,
                truncated = false,
                approvedRepos = listOf(GitStatusApprovedRepo(0, "goffy")),
                changes = listOf(GitStatusChange(secretPath, false, "?", "?", "untracked")),
            ),
            permission = PermissionLevel.SAFE,
            approvalGranted = false,
        )

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNotNull(record)
        assertEquals(GIT_STATUS_TOOL, record?.toolName)
        assertEquals(AuditPermission.SAFE, record?.permission)
        assertEquals(AuditApprovalOutcome.NOT_REQUIRED, record?.approvalOutcome)
        assertFalse(record.toString().contains(secretPath))

        val restored = requireNotNull(record).toTimelineEntry()
        assertEquals("Recorded Git status task", restored.command)
        assertEquals(TaskPhase.VERIFIED, restored.phase)
        assertEquals(GIT_STATUS_TOOL, restored.toolName)
        assertEquals(PermissionLevel.SAFE, restored.permission)
        assertEquals(null, restored.result)
        assertFalse(restored.approvalGranted)
        assertFalse(restored.toString().contains(secretPath))
    }

    @Test
    fun macClipboardAuditRoundTripsWithoutClipboardText() {
        val secretText = "secret launch phrase"
        val entry = TaskTimelineEntry(
            id = UUID.fromString("44444444-4444-4444-8444-444444444444"),
            command = "Read my Mac clipboard",
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_CLIPBOARD_READ_TOOL,
            phase = TaskPhase.VERIFIED,
            summary = "Mac clipboard contains ${secretText.length} text characters",
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Observed command"),
                TaskTimelineEvent(TaskEventKind.RESULT, "Returned clipboard text"),
                TaskTimelineEvent(TaskEventKind.VERIFY, "Verified clipboard text"),
            ),
            result = null,
            permission = PermissionLevel.SAFE,
            approvalGranted = false,
        )

        val record = entry.toClosedTerminalAuditRecord(recordedAtEpochMillis = 1_720_000_000_000)

        assertNotNull(record)
        assertEquals(MAC_CLIPBOARD_READ_TOOL, record?.toolName)
        assertEquals(AuditPermission.SAFE, record?.permission)
        assertFalse(record.toString().contains(secretText))

        val restored = requireNotNull(record).toTimelineEntry()
        assertEquals("Recorded Mac clipboard task", restored.command)
        assertEquals(MAC_CLIPBOARD_READ_TOOL, restored.toolName)
        assertEquals(null, restored.result)
    }

    @Test
    fun mapsApprovalOutcomesFromTerminalTimelineEntries() {
        val approved = terminalEntry(
            phase = TaskPhase.VERIFIED,
            summary = "Completed",
            approvalGranted = true,
        )
        val safe = terminalEntry(
            phase = TaskPhase.VERIFIED,
            permission = PermissionLevel.SAFE,
            approvalGranted = false,
            summary = "Completed",
        ).copy(toolName = PHONE_BATTERY_STATUS_TOOL)
        val denied = terminalEntry(
            phase = TaskPhase.CANCELLED,
            approvalGranted = false,
            summary = "Approval denied; no phone tool was invoked",
        )
        val expired = terminalEntry(
            phase = TaskPhase.FAILED,
            approvalGranted = false,
            summary = "Approval expired; no phone tool was invoked",
        )
        val cancelled = terminalEntry(
            phase = TaskPhase.CANCELLED,
            approvalGranted = false,
            summary = "Approval cancelled; no phone tool was invoked",
        )

        assertEquals(
            AuditApprovalOutcome.APPROVED,
            approved.toClosedTerminalAuditRecord(10)?.approvalOutcome,
        )
        assertEquals(
            AuditApprovalOutcome.NOT_REQUIRED,
            safe.toClosedTerminalAuditRecord(11)?.approvalOutcome,
        )
        assertEquals(
            AuditApprovalOutcome.DENIED,
            denied.toClosedTerminalAuditRecord(12)?.approvalOutcome,
        )
        assertEquals(
            AuditApprovalOutcome.EXPIRED,
            expired.toClosedTerminalAuditRecord(13)?.approvalOutcome,
        )
        assertEquals(
            AuditApprovalOutcome.CANCELLED,
            cancelled.toClosedTerminalAuditRecord(14)?.approvalOutcome,
        )
    }

    private fun terminalEntry(
        phase: TaskPhase,
        summary: String,
        permission: PermissionLevel = PermissionLevel.CONFIRM,
        approvalGranted: Boolean = false,
    ): TaskTimelineEntry {
        val secret = "Launch code 12345"
        return TaskTimelineEntry(
            id = UUID.fromString("11111111-1111-4111-8111-111111111111"),
            command = "Create a note saying $secret",
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_NOTE_CREATE_TOOL,
            phase = phase,
            summary = summary,
            events = listOf(
                TaskTimelineEvent(TaskEventKind.OBSERVE, "Observed $secret"),
                TaskTimelineEvent(TaskEventKind.AUTHORIZE, "Approve note for $secret"),
                TaskTimelineEvent(TaskEventKind.RESULT, "Stored $secret"),
                TaskTimelineEvent(TaskEventKind.VERIFY, "Verified $secret"),
            ),
            result = PhoneNoteCreated(
                noteId = 99,
                text = secret,
                createdAtEpochMillis = 1_720_000_000_000,
            ),
            verificationSummary = "Verified $secret",
            verificationChecks = listOf(secret),
            permission = permission,
            approvalGranted = approvalGranted,
        )
    }

    private fun assertTrueNoSecret(values: List<String>, secret: String) {
        values.forEach { value -> assertFalse(value.contains(secret)) }
    }
}
