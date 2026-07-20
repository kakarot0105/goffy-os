package dev.goffy.os.localmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalModelIntentBoundaryInstrumentedTest {
    @Test
    fun acceptsStrictRoutingJsonOnAndroidRuntime() {
        val observation = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = """{"route":"PHONE","confidence":0.91}""",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(observation is LocalModelIntentObservation.Candidate)
        val candidate = (observation as LocalModelIntentObservation.Candidate).candidate
        assertEquals("PHONE", candidate.intentLabel)
        assertEquals(0.91f, candidate.confidence, 0.0f)
    }

    @Test
    fun rejectsMalformedRoutingJsonOnAndroidRuntime() {
        val observation = evaluateLocalModelRoutingOutput(
            command = "show my battery status",
            output = """{"route":"PHONE","confidence":0.91,"extra":true}""",
            policy = LocalModelRuntimePolicy(enabled = true),
        )

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output did not match the strict routing JSON schema.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }
}
