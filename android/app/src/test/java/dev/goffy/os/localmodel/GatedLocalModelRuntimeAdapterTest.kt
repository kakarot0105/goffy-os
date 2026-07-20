package dev.goffy.os.localmodel

import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class GatedLocalModelRuntimeAdapterTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun disabledPolicyDoesNotTouchModelOrGenerator() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val missingModel = File(modelRoot, "missing.litertlm")
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = GatedLocalModelRuntimeAdapter(
            policy = LocalModelRuntimePolicy(),
            modelFile = missingModel,
            modelRoot = modelRoot,
            textGenerator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Disabled)
        assertEquals(0, generator.calls)
    }

    @Test
    fun rejectsModelOutsideApprovedRootBeforeGenerating() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val outsideModel = temporaryFolder.newFile("outside.litertlm")
        outsideModel.writeText("model", charset = Charsets.UTF_8)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = outsideModel,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Local model file must stay under the approved app-owned model directory.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(0, generator.calls)
    }

    @Test
    fun rejectsUnavailableApprovedRootBeforeGenerating() = runTest {
        val missingRoot = File(temporaryFolder.root, "missing-models")
        val modelFile = File(missingRoot, "tiny.litertlm")
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = missingRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Approved local model directory is unavailable.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(0, generator.calls)
    }

    @Test
    fun rejectsApprovedRootItselfAsModelFile() = runTest {
        val modelRoot = temporaryFolder.newFolder("root.litertlm")
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = modelRoot,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Local model file must stay under the approved app-owned model directory.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(0, generator.calls)
    }

    @Test
    fun rejectsInvalidModelFileBeforeGenerating() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val wrongExtension = File(modelRoot, "tiny.bin")
        wrongExtension.writeText("model", charset = Charsets.UTF_8)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = wrongExtension,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Local model file must be a .litertlm file.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(0, generator.calls)
    }

    @Test
    fun rejectsOversizedModelFileBeforeGenerating() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = File(modelRoot, "tiny.litertlm")
        modelFile.writeText("12345", charset = Charsets.UTF_8)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = generator,
            policy = LocalModelRuntimePolicy(enabled = true, maxModelFileBytes = 4),
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Local model file exceeds the GOFFY LITE size budget.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(0, generator.calls)
    }

    @Test
    fun passesGeneratorOutputThroughQualityGate() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Candidate)
        assertEquals(1, generator.calls)
        assertTrue(generator.lastPrompt?.contains("show my battery status") == true)
        assertEquals(
            "PHONE",
            (observation as LocalModelIntentObservation.Candidate).candidate.intentLabel,
        )
    }

    @Test
    fun rejectsVerboseGeneratorOutput() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val generator = RecordingGenerator("<think>reasoning</think> PHONE")
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output included hidden reasoning text.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun rejectsOversizedRawGeneratorOutput() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val generator = RecordingGenerator("x".repeat(257))
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output is outside local routing quality bounds.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun rejectsLongCommandBeforeGenerating() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = generator,
        )

        val observation = adapter.observeUnsupportedCommand("x".repeat(161))

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Normalized command is outside local candidate quality bounds.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
        assertEquals(0, generator.calls)
    }

    @Test
    fun convertsRuntimeFailuresToRejectedObservation() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = LocalModelTextGenerator {
                _, _ -> error("native failure")
            },
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Local model runtime failed without producing a safe routing observation.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun convertsOutputLimitFailuresToRejectedObservation() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = LocalModelTextGenerator {
                _, _ -> throw LocalModelOutputLimitExceeded()
            },
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Model output exceeded the local routing output budget.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun rejectsWhenGenerationTimesOut() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = LocalModelTextGenerator {
                _, _ -> awaitCancellation()
            },
            policy = LocalModelRuntimePolicy(
                enabled = true,
                generationTimeoutMillis = 1_000L,
            ),
        )

        val observation = adapter.observeUnsupportedCommand("show my battery status")

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "Local model generation timed out before producing a safe routing observation.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun doesNotSwallowCallerCancellation() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val adapter = enabledAdapter(
            modelFile = modelFile,
            modelRoot = modelRoot,
            generator = LocalModelTextGenerator {
                _, _ -> throw CancellationException("caller cancelled")
            },
        )

        try {
            adapter.observeUnsupportedCommand("show my battery status")
            fail("expected cancellation to propagate")
        } catch (cancellation: CancellationException) {
            assertEquals("caller cancelled", cancellation.message)
        }
    }

    @Test
    fun promptTemplateStaysWithinDefaultPromptBudgetForCandidateSizedCommands() {
        val prompt = localModelRoutingPrompt("x".repeat(160))

        assertTrue(isSafeLocalModelPrompt(prompt))
    }

    private fun enabledAdapter(
        modelFile: File,
        modelRoot: File,
        generator: LocalModelTextGenerator,
        policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(enabled = true),
    ): GatedLocalModelRuntimeAdapter =
        GatedLocalModelRuntimeAdapter(
            policy = policy,
            modelFile = modelFile,
            modelRoot = modelRoot,
            textGenerator = generator,
        )

    private fun writeModel(modelRoot: File): File =
        File(modelRoot, "tiny.litertlm").also {
            it.writeText("model", charset = Charsets.UTF_8)
        }

    private class RecordingGenerator(private val output: String) : LocalModelTextGenerator {
        var calls = 0
            private set
        var lastPrompt: String? = null
            private set

        override suspend fun generate(
            prompt: String,
            policy: LocalModelRuntimePolicy,
        ): String {
            calls += 1
            lastPrompt = prompt
            return output
        }
    }
}
