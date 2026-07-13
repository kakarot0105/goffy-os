package dev.goffy.os

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyUiStateTest {
    @Test
    fun initialStateIsLiteFriendlyAndHasEmptyTimeline() {
        val state = GoffyUiState()

        assertEquals(MacConnectionState.DISCONNECTED, state.macConnection)
        assertEquals(ExecutionTarget.MAC, state.executionTarget)
        assertTrue(state.timeline.isEmpty())
    }

    @Test
    fun blankCommandIsIgnored() {
        val state = GoffyUiState()

        assertEquals(state, state.queueCommand("   ", "waiting"))
    }

    @Test
    fun queuedCommandIsTrimmedAndBounded() {
        var state = GoffyUiState()

        repeat(55) { index ->
            state = state.queueCommand("  command $index  ", "waiting")
        }

        assertEquals(50, state.timeline.size)
        assertEquals("command 5", state.timeline.first().command)
        assertEquals("command 54", state.timeline.last().command)
    }
}
