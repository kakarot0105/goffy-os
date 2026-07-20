package dev.goffy.os.localmodel

import java.io.File
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class GatedLocalModelRuntimeProviderTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun providerDoesNotGenerateWhenGateIsDisabled() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val provider = provider(
            gate = LocalModelRuntimeGate(),
            modelRoot = modelRoot,
            modelFile = modelFile,
            generator = generator,
        )

        val observation = provider.observeUnsupportedCommand("open settings")

        assertEquals(LocalModelRuntimeState.DISABLED, provider.status.state)
        assertTrue(observation is LocalModelIntentObservation.Disabled)
        assertEquals(0, generator.calls)
    }

    @Test
    fun providerDelegatesOnlyAfterGateIsReady() = runTest {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot)
        val generator = RecordingGenerator("""{"route":"PHONE","confidence":0.91}""")
        val policyProvider = { LocalModelRuntimePolicy(enabled = true) }
        val gate = LocalModelRuntimeGate(
            configProvider = {
                LocalModelRuntimeGateConfig(
                    enabledByUser = true,
                    developerRuntimeAllowed = true,
                    runtimeAvailable = true,
                    modelRoot = modelRoot,
                    modelFile = modelFile,
                    policy = policyProvider(),
                )
            },
            delegateAvailableProvider = { true },
        )
        val provider = provider(
            gate = gate,
            modelRoot = modelRoot,
            modelFile = modelFile,
            generator = generator,
            policyProvider = policyProvider,
        )

        val observation = provider.observeUnsupportedCommand("show my battery status")

        assertEquals(LocalModelRuntimeState.READY, provider.status.state)
        assertTrue(observation is LocalModelIntentObservation.Candidate)
        assertEquals(1, generator.calls)
    }

    private fun provider(
        gate: LocalModelRuntimeGate,
        modelRoot: File,
        modelFile: File,
        generator: LocalModelTextGenerator,
        policyProvider: () -> LocalModelRuntimePolicy = { LocalModelRuntimePolicy() },
    ): GatedLocalModelRuntimeProvider =
        GatedLocalModelRuntimeProvider(
            gate = gate,
            adapter = GatedLocalModelRuntimeAdapter(
                policyProvider = policyProvider,
                modelFile = modelFile,
                modelRoot = modelRoot,
                textGenerator = generator,
            ),
        )

    private fun writeModel(modelRoot: File): File =
        File(modelRoot, "tiny.litertlm").also {
            it.writeText("model", charset = Charsets.UTF_8)
        }

    private class RecordingGenerator(
        private val output: String,
    ) : LocalModelTextGenerator {
        var calls = 0
            private set

        override suspend fun generate(prompt: String, policy: LocalModelRuntimePolicy): String {
            calls += 1
            return output
        }
    }
}
