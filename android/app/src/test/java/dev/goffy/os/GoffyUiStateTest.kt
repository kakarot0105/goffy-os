package dev.goffy.os

import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineEvent
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.PermissionLevel
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyUiStateTest {
    private val endpoint = "wss://mac.example/ws/v1"
    private val taskId = UUID.fromString("11111111-1111-4111-8111-111111111111")
    private val plan = (GoffyIntentRouter.route("Show my Mac status") as RoutingDecision.Routed).plan
    private val phonePlan =
        (GoffyIntentRouter.route("Show my battery status") as RoutingDecision.Routed).plan

    @Test
    fun initialStateIsLiteFriendlyAndHasEmptyTimeline() {
        val state = GoffyUiState(hubEndpoint = endpoint)

        assertEquals(MacConnectionState.DISCONNECTED, state.macConnection)
        assertEquals(ExecutionTarget.PHONE, state.executionTarget)
        assertTrue(state.timeline.entries.isEmpty())
        assertFalse(state.hubConfigured)
        assertEquals(AuditPersistenceState.LOADING, state.auditPersistence)
        assertEquals(DockAwakeStatus.WAITING_FOR_POWER, state.dockAwakeStatus)
        assertFalse(state.keepScreenAwake)
    }

    @Test
    fun chargingStateEnablesForegroundDockAwakeMode() {
        val unplugged = GoffyUiState(hubEndpoint = endpoint, charging = false)
        val charging = unplugged.copy(charging = true)
        val disabled = charging.copy(keepAwakeWhenCharging = false)

        assertEquals(DockAwakeStatus.WAITING_FOR_POWER, unplugged.dockAwakeStatus)
        assertFalse(unplugged.keepScreenAwake)
        assertEquals(DockAwakeStatus.AWAKE, charging.dockAwakeStatus)
        assertTrue(charging.keepScreenAwake)
        assertEquals(DockAwakeStatus.DISABLED, disabled.dockAwakeStatus)
        assertFalse(disabled.keepScreenAwake)
    }

    @Test
    fun restoredAuditIsDisplayOnlyAndNeverResumesAuthority() {
        val restored = TaskTimelineEntry(
            id = taskId,
            command = "Show Mac status",
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_SYSTEM_INFO_TOOL,
            phase = TaskPhase.VERIFIED,
            summary = "Verified Mac status",
            events = listOf(TaskTimelineEvent(TaskEventKind.VERIFY, "Verification completed")),
            permission = PermissionLevel.SAFE,
            terminalAtEpochMillis = 1_720_000_000_000,
            auditRecordedAtEpochMillis = 1_720_000_000_000,
        )

        val state = GoffyUiState(hubEndpoint = endpoint).auditLoaded(listOf(restored), 0)

        assertEquals(AuditPersistenceState.READY, state.auditPersistence)
        assertEquals(listOf(restored), state.timeline.entries)
        assertNull(state.timeline.activeTaskId)
        assertNull(state.pendingApproval)
        assertNull(state.timeline.entries.single().result)

        assertThrows(IllegalArgumentException::class.java) {
            GoffyUiState(hubEndpoint = endpoint).auditLoaded(
                listOf(restored.copy(approvalGranted = true)),
                0,
            )
        }
    }

    @Test
    fun discardedAuditRowsDegradeHistoryWithoutChangingEntries() {
        val state = GoffyUiState(hubEndpoint = endpoint).auditLoaded(emptyList(), 2)

        assertEquals(AuditPersistenceState.DEGRADED, state.auditPersistence)
        assertEquals(2, state.discardedAuditRecords)
        assertTrue(state.timeline.entries.isEmpty())
    }

    @Test
    fun configurationStateNeverContainsBearerToken() {
        val state = GoffyUiState(hubEndpoint = endpoint).hubConfigured(endpoint)

        assertTrue(state.hubConfigured)
        assertEquals(endpoint, state.hubEndpoint)
        assertFalse(state.toString().contains("secret-token"))
    }

    @Test
    fun hubIdentityFingerprintIsShownOnlyForPersistentPairing() {
        val fingerprint = "sha256:" + "a".repeat(90)

        val paired = GoffyUiState(hubEndpoint = endpoint).hubConfigured(
            endpoint,
            persistent = true,
            hubIdentityFingerprint = fingerprint,
        )
        val development = GoffyUiState(hubEndpoint = endpoint).hubConfigured(
            endpoint,
            persistent = false,
            hubIdentityFingerprint = fingerprint,
        )

        assertEquals(fingerprint.take(80), paired.hubIdentityFingerprint)
        assertNull(development.hubIdentityFingerprint)
    }

    @Test
    fun tokenRotationReminderIsShownOnlyForPersistentPairing() {
        val reminder = HubTokenRotationReminder(
            tokenAgeDays = 31,
            message = "x".repeat(220),
        )

        val paired = GoffyUiState(hubEndpoint = endpoint).hubConfigured(
            endpoint,
            persistent = true,
            hubTokenRotationReminder = reminder,
        )
        val development = GoffyUiState(hubEndpoint = endpoint).hubConfigured(
            endpoint,
            persistent = false,
            hubTokenRotationReminder = reminder,
        )

        assertEquals(31L, paired.hubTokenRotationReminder?.tokenAgeDays)
        assertEquals(180, paired.hubTokenRotationReminder?.message?.length)
        assertNull(development.hubTokenRotationReminder)
    }

    @Test
    fun rotationStateIsAnExclusiveLinkOperation() {
        val state = GoffyUiState(hubEndpoint = endpoint).hubRotationStarted()

        assertEquals(HubLinkState.ROTATING, state.hubLinkState)
        assertTrue(state.linkOperationInProgress)
        assertFalse(state.hubConfigured)
    }

    @Test
    fun connectionAndFailureEventsRemainObservable() {
        var state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, plan)
        state = state.applyTaskEvent(taskId, ExecutionEvent.Starting(1))
        assertEquals(MacConnectionState.CONNECTING, state.macConnection)

        state = state.applyTaskEvent(taskId, ExecutionEvent.Ready)
        assertEquals(MacConnectionState.CONNECTED, state.macConnection)

        state = state.applyTaskEvent(
            taskId,
            ExecutionEvent.Error("network_failure", "Unable to reach Hub", true),
        )
        assertEquals(MacConnectionState.DISCONNECTED, state.macConnection)
        assertEquals(TaskPhase.FAILED, state.timeline.entries.single().phase)
        assertNull(state.timeline.activeTaskId)
    }

    @Test
    fun staleEventsAfterCancellationCannotChangeConnectionState() {
        var state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, plan)
        state = state.applyTaskEvent(taskId, ExecutionEvent.Starting(1))
        state = state.cancelActiveTask()

        val afterLateEvent = state.applyTaskEvent(taskId, ExecutionEvent.Ready)

        assertEquals(state, afterLateEvent)
        assertEquals(MacConnectionState.DISCONNECTED, afterLateEvent.macConnection)
        assertEquals(TaskPhase.CANCELLED, afterLateEvent.timeline.entries.single().phase)
    }

    @Test
    fun phoneExecutionDoesNotPretendToOpenTheMacLink() {
        var state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, phonePlan)

        state = state.applyTaskEvent(taskId, ExecutionEvent.Starting(1))
        state = state.applyTaskEvent(taskId, ExecutionEvent.Ready)

        assertEquals(ExecutionTarget.PHONE, state.executionTarget)
        assertEquals(MacConnectionState.DISCONNECTED, state.macConnection)
    }

    @Test
    fun malformedMacEventFailsClosedAndDisconnectsTheBadge() {
        var state = GoffyUiState(hubEndpoint = endpoint).startTask(taskId, plan)
        state = state.applyTaskEvent(taskId, ExecutionEvent.Starting(1))
        state = state.applyTaskEvent(taskId, ExecutionEvent.Ready)

        state = state.applyTaskEvent(taskId, ExecutionEvent.Ready)

        assertEquals(TaskPhase.FAILED, state.timeline.entries.single().phase)
        assertEquals(MacConnectionState.DISCONNECTED, state.macConnection)
        assertNull(state.timeline.activeTaskId)
    }
}
