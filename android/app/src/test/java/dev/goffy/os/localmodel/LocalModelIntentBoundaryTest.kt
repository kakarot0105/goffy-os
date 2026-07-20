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
        assertEquals(256, policy.maxModelOutputChars)
        assertEquals(0.70f, policy.minRoutingConfidence)
        assertEquals(60_000L, policy.idleUnloadMillis)
        assertEquals(15_000L, policy.generationTimeoutMillis)
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
            LocalModelRuntimePolicy(maxModelOutputChars = 257)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(minRoutingConfidence = 1.1f)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(idleUnloadMillis = 301_000L)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(generationTimeoutMillis = 999L)
        }
        assertThrows(IllegalArgumentException::class.java) {
            LocalModelRuntimePolicy(generationTimeoutMillis = 60_001L)
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
    fun modelOutputsAreBoundedForRoutingQualityGate() {
        assertTrue(isSafeLocalModelOutput("""{"route":"PHONE","confidence":0.91}"""))
        assertEquals(false, isSafeLocalModelOutput(""))
        assertEquals(false, isSafeLocalModelOutput("x".repeat(257)))
        assertEquals(false, isSafeLocalModelOutput("PHONE\nMAC"))
        assertEquals(false, isSafeLocalModelOutput("PHONE\u202EMAC"))
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

    @Test
    fun qualityGateAcceptsOnlyStrictRoutingJson() {
        val observation = evaluateLocalModelRoutingOutput(
            command = "please show battery",
            output = """{"route":"PHONE","confidence":0.91}""",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(observation is LocalModelIntentObservation.Candidate)
        val candidate = (observation as LocalModelIntentObservation.Candidate).candidate
        assertEquals("PHONE", candidate.intentLabel)
        assertEquals(0.91f, candidate.confidence)
        assertEquals("please show battery", candidate.normalizedCommand)
    }

    @Test
    fun qualityGateRejectsVerboseQwenStyleReasoning() {
        val observation = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = "<think>\nThe user wants battery status.\n</think>\nPHONE",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output is outside local routing quality bounds.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun qualityGateRejectsHiddenReasoningMarkers() {
        val observation = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = "<think>hidden reasoning</think> PHONE",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output included hidden reasoning text.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun qualityGateRejectsNonJsonOrLowConfidenceOutputs() {
        val plainLabel = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = "PHONE",
            policy = LocalModelRuntimePolicy(enabled = true),
        )
        val lowConfidence = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = """{"route":"PHONE","confidence":0.69}""",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(plainLabel is LocalModelIntentObservation.Rejected)
        assertTrue(lowConfidence is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output did not match the strict routing JSON schema.",
            (plainLabel as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(
            "Model confidence is below the local routing threshold.",
            (lowConfidence as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun qualityGateRejectsLongCandidateCommandsWithoutThrowing() {
        val accepted = evaluateLocalModelRoutingOutput(
            command = "x".repeat(160),
            output = """{"route":"PHONE","confidence":0.91}""",
            policy = LocalModelRuntimePolicy(enabled = true),
        )
        val rejected = evaluateLocalModelRoutingOutput(
            command = "x".repeat(161),
            output = """{"route":"PHONE","confidence":0.91}""",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(accepted is LocalModelIntentObservation.Candidate)
        assertTrue(rejected is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Normalized command is outside local candidate quality bounds.",
            (rejected as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun qualityGateFailsClosedWhenPolicyIsDisabled() {
        val observation = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = """{"route":"PHONE","confidence":0.91}""",
        )

        assertTrue(observation is LocalModelIntentObservation.Disabled)
    }
}
