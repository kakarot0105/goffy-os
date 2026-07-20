package dev.goffy.os.localmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalModelIntentBoundaryTest {
    @Test
    fun defaultPolicyIsDisabledAndMotoBounded() {
        val policy = LocalModelRuntimePolicy()

        assertEquals(false, policy.enabled)
        assertEquals(512L * 1024L * 1024L, policy.maxModelFileBytes)
        assertEquals(512, policy.maxPromptChars)
        assertEquals(60_000L, policy.idleUnloadMillis)
    }

    @Test
    fun rejectsOversizedModelOrPromptBudgets() {
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(maxModelFileBytes = 513L * 1024L * 1024L)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(maxPromptChars = 513)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(idleUnloadMillis = 301_000L)
        }
    }

    @Test
    fun disabledFallbackReturnsNonAuthoritativeObservation() {
        val observation = DisabledLocalModelIntentFallback.observeUnsupportedCommand("open settings")

        assertTrue(observation is LocalModelIntentObservation.Disabled)
    }

    @Test
    fun promptCandidatesAreBoundedForMotoFallbackUse() {
        assertTrue(isSafeLocalModelPrompt("open settings"))
        assertEquals(false, isSafeLocalModelPrompt(""))
        assertEquals(false, isSafeLocalModelPrompt("x".repeat(513)))
        assertEquals(false, isSafeLocalModelPrompt("open\u202Esettings"))
        assertEquals(false, isSafeLocalModelPrompt("open\u2066settings"))
        assertEquals(false, isSafeLocalModelPrompt("open\u200Bsettings"))
    }

    @Test
    fun intentCandidatesAreBoundedAndNonControlText() {
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelIntentCandidate(
                intentLabel = "open\u200Bsettings",
                confidence = 0.5f,
                normalizedCommand = "open settings",
                rationale = "spoofed",
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelIntentCandidate(
                intentLabel = "open_settings",
                confidence = 1.1f,
                normalizedCommand = "open settings",
                rationale = "out of range",
            )
        }
    }
}
