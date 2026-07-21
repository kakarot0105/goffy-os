package dev.goffy.os.localmodel

import android.content.Context
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import dev.goffy.os.BuildConfig
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val LOCAL_MODEL_DIRECTORY = "local-models"
private const val LOCAL_MODEL_LOG_TAG = "GoffyLocalModel"
private const val OBSERVATION_ENGINE_SCOPE_CLOSED_MARKER =
    "observation_engine_scope_closed"

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
        var observationScopeEntered = false
        try {
            Engine(engineConfig).use { engine ->
                engine.initialize()
                engine.createConversation().use { conversation ->
                    observationScopeEntered = true
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
        } finally {
            if (observationScopeEntered) {
                Log.i(LOCAL_MODEL_LOG_TAG, OBSERVATION_ENGINE_SCOPE_CLOSED_MARKER)
            }
        }
        output.toString()
    }
}
