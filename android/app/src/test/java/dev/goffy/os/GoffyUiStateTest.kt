package dev.goffy.os

import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
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
    }

    @Test
    fun configurationStateNeverContainsBearerToken() {
        val state = GoffyUiState(hubEndpoint = endpoint).hubConfigured(endpoint)

        assertTrue(state.hubConfigured)
        assertEquals(endpoint, state.hubEndpoint)
        assertFalse(state.toString().contains("secret-token"))
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
