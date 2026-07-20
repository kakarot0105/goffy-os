package dev.goffy.os.localmodel

import android.content.Context
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import dev.goffy.os.BuildConfig
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val LOCAL_MODEL_DIRECTORY = "local-models"

class LiteRtLmLocalModelProviderFactory : LocalModelRuntimeProviderFactory {
    override fun create(
        context: Context,
        settingsSource: LocalModelRuntimeSettingsSource,
    ): LocalModelRuntimeProvider {
        val appContext = context.applicationContext
        val modelRoot = File(appContext.noBackupFilesDir, LOCAL_MODEL_DIRECTORY)
        val modelFile = File(modelRoot, BuildConfig.GOFFY_LOCAL_MODEL_FILE_NAME)
        val policyProvider = {
            LocalModelRuntimePolicy(enabled = settingsSource.snapshot().enabledByUser)
        }
        val gate = LocalModelRuntimeGate(
            configProvider = {
                val settings = settingsSource.snapshot()
                LocalModelRuntimeGateConfig(
                    enabledByUser = settings.enabledByUser,
                    developerRuntimeAllowed = BuildConfig.GOFFY_LOCAL_MODEL_DEVELOPER_RUNTIME_ALLOWED,
                    runtimeAvailable = true,
                    modelRoot = modelRoot,
                    modelFile = modelFile,
                    policy = policyProvider(),
                )
            },
            delegateAvailableProvider = { true },
        )
        val adapter = GatedLocalModelRuntimeAdapter(
            policyProvider = policyProvider,
            modelFile = modelFile,
            modelRoot = modelRoot,
            textGenerator = LiteRtLmTextGenerator(appContext, modelFile),
        )
        return GatedLocalModelRuntimeProvider(gate, adapter)
    }
}

private class LiteRtLmTextGenerator(
    private val context: Context,
    private val modelFile: File,
) : LocalModelTextGenerator {
    override suspend fun generate(
        prompt: String,
        policy: LocalModelRuntimePolicy,
    ): String = withContext(Dispatchers.Default) {
        Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
        val output = StringBuilder()
        val outputBudgetChars = policy.maxModelOutputChars + 1
        val engineConfig = EngineConfig(
            modelPath = modelFile.absolutePath,
            backend = Backend.CPU(),
            cacheDir = context.cacheDir.absolutePath,
        )
        Engine(engineConfig).use { engine ->
            engine.initialize()
            engine.createConversation().use { conversation ->
                conversation.sendMessageAsync(prompt).collect { message ->
                    val text = message.toString()
                    val remainingOutputBudget = outputBudgetChars - output.length
                    if (remainingOutputBudget > 0) {
                        output.append(text.take(remainingOutputBudget))
                    }
                    if (output.length >= outputBudgetChars) {
                        throw LocalModelOutputLimitExceeded()
                    }
                }
            }
        }
        output.toString()
    }
}
