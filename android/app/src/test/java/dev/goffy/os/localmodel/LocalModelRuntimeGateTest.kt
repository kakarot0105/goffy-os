package dev.goffy.os.localmodel

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class LocalModelRuntimeGateTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun defaultGateIsDisabledAndDoesNotDelegate() {
        val delegate = RecordingFallback()
        val gate = LocalModelRuntimeGate(delegate = delegate)

        val observation = gate.observeUnsupportedCommand("open settings")

        assertEquals(LocalModelRuntimeState.DISABLED, gate.status.state)
        assertTrue(observation is LocalModelIntentObservation.Disabled)
        assertEquals(0, delegate.calls)
    }

    @Test
    fun userEnabledGateRequiresRuntimeProviderBeforeDelegating() {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val delegate = RecordingFallback()
        val gate = LocalModelRuntimeGate(
            config = LocalModelRuntimeGateConfig(
                enabledByUser = true,
                developerRuntimeAllowed = true,
                runtimeAvailable = false,
                modelRoot = modelRoot,
                modelFile = modelFile,
                policy = LocalModelRuntimePolicy(enabled = true),
            ),
            delegate = delegate,
        )

        val observation = gate.observeUnsupportedCommand("open settings")

        assertEquals(LocalModelRuntimeState.UNAVAILABLE, gate.status.state)
        assertTrue(observation is LocalModelIntentObservation.Disabled)
        assertEquals(0, delegate.calls)
    }

    @Test
    fun gateBlocksModelOutsideApprovedRoot() {
        val modelRoot = temporaryFolder.newFolder("models")
        val outsideModel = temporaryFolder.newFile("outside.litertlm")
        outsideModel.writeText("model", charset = Charsets.UTF_8)
        val delegate = RecordingFallback()
        val gate = LocalModelRuntimeGate(
            config = LocalModelRuntimeGateConfig(
                enabledByUser = true,
                developerRuntimeAllowed = true,
                runtimeAvailable = true,
                modelRoot = modelRoot,
                modelFile = outsideModel,
                policy = LocalModelRuntimePolicy(enabled = true),
            ),
            delegate = delegate,
        )

        val observation = gate.observeUnsupportedCommand("open settings")

        assertEquals(LocalModelRuntimeState.BLOCKED, gate.status.state)
        assertTrue(observation is LocalModelIntentObservation.Disabled)
        assertEquals(0, delegate.calls)
    }

    @Test
    fun readyGateDelegatesButRemainsObserveOnly() {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val delegate = RecordingFallback(
            LocalModelIntentObservation.Candidate(
                LocalModelIntentCandidate(
                    intentLabel = "PHONE",
                    confidence = 0.91f,
                    normalizedCommand = "open settings",
                    rationale = "test observation",
                ),
            ),
        )
        val gate = LocalModelRuntimeGate(
            config = LocalModelRuntimeGateConfig(
                enabledByUser = true,
                developerRuntimeAllowed = true,
                runtimeAvailable = true,
                modelRoot = modelRoot,
                modelFile = modelFile,
                policy = LocalModelRuntimePolicy(enabled = true),
            ),
            delegate = delegate,
        )

        val observation = gate.observeUnsupportedCommand("open settings")

        assertEquals(LocalModelRuntimeState.READY, gate.status.state)
        assertTrue(gate.status.observeOnly)
        assertTrue(observation is LocalModelIntentObservation.Candidate)
        assertEquals(1, delegate.calls)
    }

    @Test
    fun readyGateRechecksModelFileBeforeDelegating() {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val delegate = RecordingFallback()
        val gate = LocalModelRuntimeGate(
            config = LocalModelRuntimeGateConfig(
                enabledByUser = true,
                developerRuntimeAllowed = true,
                runtimeAvailable = true,
                modelRoot = modelRoot,
                modelFile = modelFile,
                policy = LocalModelRuntimePolicy(enabled = true),
            ),
            delegate = delegate,
        )

        assertEquals(LocalModelRuntimeState.READY, gate.status.state)
        assertTrue(modelFile.delete())
        val observation = gate.observeUnsupportedCommand("open settings")

        assertEquals(LocalModelRuntimeState.UNAVAILABLE, gate.status.state)
        assertTrue(observation is LocalModelIntentObservation.Disabled)
        assertEquals(0, delegate.calls)
    }

    private fun writeModel(modelRoot: File): File =
        File(modelRoot, "tiny.litertlm").also {
            it.writeText("model", charset = Charsets.UTF_8)
        }

    private class RecordingFallback(
        private val observation: LocalModelIntentObservation = LocalModelIntentObservation.Rejected(
            "test rejection",
        ),
    ) : LocalModelIntentFallback {
        var calls = 0
            private set

        override fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
            calls += 1
            return observation
        }
    }
}
