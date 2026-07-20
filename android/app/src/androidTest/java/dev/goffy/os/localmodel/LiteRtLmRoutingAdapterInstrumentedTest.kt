package dev.goffy.os.localmodel

import android.content.Context
import android.os.Build
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

private const val ADAPTER_TIMEOUT_MILLIS = 120_000L
private const val MAX_ADAPTER_TIMEOUT_MILLIS = 300_000L
private const val ADAPTER_OUTPUT_PREVIEW_CHARS = 320

class LiteRtLmRoutingAdapterInstrumentedTest {
    @Test
    fun smokeRealLiteRtLmThroughAdapterGate() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val args = InstrumentationRegistry.getArguments()
        val modelPath = args.getString("modelPath")
        assumeTrue("Pass -e modelPath to run the real adapter smoke.", !modelPath.isNullOrBlank())

        val command = args.getString("prompt") ?: "show my battery status"
        val timeoutMillis = args.getString("timeoutMillis")
            ?.toLongOrNull()
            ?.coerceIn(5_000L, MAX_ADAPTER_TIMEOUT_MILLIS)
            ?: ADAPTER_TIMEOUT_MILLIS
        val resultFile = adapterSmokeResultFile(context, args.getString("resultPath"))
        val modelFile = verifiedAdapterModelFile(context, modelPath)
        val modelRoot = requireNotNull(context.getExternalFilesDir("models")) {
            "external model directory unavailable"
        }.canonicalFile
        val generator = RecordingLiteRtLmTextGenerator(context, modelFile)
        val startedAt = System.currentTimeMillis()

        val result = try {
            val observation = withTimeout(timeoutMillis) {
                GatedLocalModelRuntimeAdapter(
                    policy = LocalModelRuntimePolicy(enabled = true),
                    modelFile = modelFile,
                    modelRoot = modelRoot,
                    textGenerator = generator,
                ).observeUnsupportedCommand(command)
            }
            LiteRtLmAdapterSmokeResult.fromObservation(
                modelFile = modelFile,
                command = command,
                startedAt = startedAt,
                generator = generator,
                observation = observation,
            )
        } catch (throwable: Throwable) {
            LiteRtLmAdapterSmokeResult.failure(
                modelFile = modelFile,
                command = command,
                startedAt = startedAt,
                generator = generator,
                error = throwable,
            )
        }

        resultFile.parentFile?.mkdirs()
        resultFile.writeText(result.toJson(), Charsets.UTF_8)
        println("GOFFY_LITERTLM_ADAPTER_SMOKE_JSON=${resultFile.absolutePath}")

        assertTrue("adapter smoke JSON should be written", resultFile.isFile)
    }
}

private class RecordingLiteRtLmTextGenerator(
    private val context: Context,
    private val modelFile: File,
) : LocalModelTextGenerator {
    var initMillis: Long? = null
        private set
    var firstChunkMillis: Long? = null
        private set
    var generationMillis: Long? = null
        private set
    var outputChunkCount = 0
        private set
    var outputCharCount = 0
        private set
    val outputPreview = StringBuilder()

    override suspend fun generate(
        prompt: String,
        policy: LocalModelRuntimePolicy,
    ): String = withContext(kotlinx.coroutines.Dispatchers.Default) {
        Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
        val output = StringBuilder()
        val outputBudgetChars = policy.maxModelOutputChars + 1
        val engineConfig = EngineConfig(
            modelPath = modelFile.absolutePath,
            backend = Backend.CPU(),
            cacheDir = context.cacheDir.absolutePath,
        )
        Engine(engineConfig).use { engine ->
            initMillis = elapsedMillis {
                engine.initialize()
            }
            engine.createConversation().use { conversation ->
                val generationStart = SystemClock.elapsedRealtime()
                conversation.sendMessageAsync(prompt).collect { message ->
                    if (firstChunkMillis == null) {
                        firstChunkMillis = SystemClock.elapsedRealtime() - generationStart
                    }
                    val text = message.toString()
                    outputChunkCount += 1
                    outputCharCount += text.length
                    val remainingOutputBudget = outputBudgetChars - output.length
                    if (remainingOutputBudget > 0) {
                        output.append(text.take(remainingOutputBudget))
                    }
                    if (outputPreview.length < ADAPTER_OUTPUT_PREVIEW_CHARS) {
                        outputPreview.append(
                            text.take(ADAPTER_OUTPUT_PREVIEW_CHARS - outputPreview.length),
                        )
                    }
                    if (output.length >= outputBudgetChars) {
                        generationMillis = SystemClock.elapsedRealtime() - generationStart
                        throw LocalModelOutputLimitExceeded()
                    }
                }
                generationMillis = SystemClock.elapsedRealtime() - generationStart
            }
        }
        output.toString()
    }
}

private data class LiteRtLmAdapterSmokeResult(
    val status: String,
    val deviceModel: String,
    val androidSdk: Int,
    val modelPath: String,
    val modelBytes: Long,
    val commandChars: Int,
    val promptChars: Int,
    val wallStartMillis: Long,
    val initMillis: Long?,
    val firstChunkMillis: Long?,
    val generationMillis: Long?,
    val outputChunkCount: Int,
    val outputCharCount: Int,
    val outputPreview: String,
    val observationType: String?,
    val observationRoute: String?,
    val observationConfidence: Float?,
    val observationReason: String?,
    val nonAuthoritative: Boolean,
    val errorClass: String?,
    val errorMessage: String?,
    val errorCauseClass: String?,
    val errorCauseMessage: String?,
) {
    fun toJson(): String =
        buildString {
            append("{\n")
            appendJson("status", status)
            appendJson("deviceModel", deviceModel)
            appendJson("androidSdk", androidSdk)
            appendJson("modelPath", modelPath)
            appendJson("modelBytes", modelBytes)
            appendJson("commandChars", commandChars)
            appendJson("promptChars", promptChars)
            appendJson("wallStartMillis", wallStartMillis)
            appendJson("initMillis", initMillis)
            appendJson("firstChunkMillis", firstChunkMillis)
            appendJson("generationMillis", generationMillis)
            appendJson("outputChunkCount", outputChunkCount)
            appendJson("outputCharCount", outputCharCount)
            appendJson("outputPreview", outputPreview)
            appendJson("observationType", observationType)
            appendJson("observationRoute", observationRoute)
            appendJson("observationConfidence", observationConfidence)
            appendJson("observationReason", observationReason)
            appendJson("nonAuthoritative", nonAuthoritative)
            appendJson("errorClass", errorClass)
            appendJson("errorMessage", errorMessage)
            appendJson("errorCauseClass", errorCauseClass)
            appendJson("errorCauseMessage", errorCauseMessage, trailing = false)
            append("\n}\n")
        }

    companion object {
        fun fromObservation(
            modelFile: File,
            command: String,
            startedAt: Long,
            generator: RecordingLiteRtLmTextGenerator,
            observation: LocalModelIntentObservation,
        ): LiteRtLmAdapterSmokeResult {
            val prompt = localModelRoutingPrompt(command.trim())
            val safeTerminalObservation = observation is LocalModelIntentObservation.Candidate ||
                observation is LocalModelIntentObservation.Rejected
            return LiteRtLmAdapterSmokeResult(
                status = if (safeTerminalObservation && generator.outputChunkCount > 0) {
                    "PASS"
                } else {
                    "FAIL"
                },
                deviceModel = Build.MODEL,
                androidSdk = Build.VERSION.SDK_INT,
                modelPath = modelFile.absolutePath,
                modelBytes = modelFile.length(),
                commandChars = command.length,
                promptChars = prompt.length,
                wallStartMillis = startedAt,
                initMillis = generator.initMillis,
                firstChunkMillis = generator.firstChunkMillis,
                generationMillis = generator.generationMillis,
                outputChunkCount = generator.outputChunkCount,
                outputCharCount = generator.outputCharCount,
                outputPreview = generator.outputPreview.toString(),
                observationType = observation::class.java.simpleName,
                observationRoute = (observation as? LocalModelIntentObservation.Candidate)
                    ?.candidate
                    ?.intentLabel,
                observationConfidence = (observation as? LocalModelIntentObservation.Candidate)
                    ?.candidate
                    ?.confidence,
                observationReason = (observation as? LocalModelIntentObservation.Rejected)?.reason,
                nonAuthoritative = true,
                errorClass = null,
                errorMessage = null,
                errorCauseClass = null,
                errorCauseMessage = null,
            )
        }

        fun failure(
            modelFile: File,
            command: String,
            startedAt: Long,
            generator: RecordingLiteRtLmTextGenerator,
            error: Throwable,
        ): LiteRtLmAdapterSmokeResult {
            val rootCause = error.rootCause()
            return LiteRtLmAdapterSmokeResult(
                status = "FAIL",
                deviceModel = Build.MODEL,
                androidSdk = Build.VERSION.SDK_INT,
                modelPath = modelFile.absolutePath,
                modelBytes = modelFile.length(),
                commandChars = command.length,
                promptChars = localModelRoutingPrompt(command.trim()).length,
                wallStartMillis = startedAt,
                initMillis = generator.initMillis,
                firstChunkMillis = generator.firstChunkMillis,
                generationMillis = generator.generationMillis,
                outputChunkCount = generator.outputChunkCount,
                outputCharCount = generator.outputCharCount,
                outputPreview = generator.outputPreview.toString(),
                observationType = null,
                observationRoute = null,
                observationConfidence = null,
                observationReason = null,
                nonAuthoritative = true,
                errorClass = error::class.java.simpleName,
                errorMessage = error.message?.take(240),
                errorCauseClass = rootCause::class.java.simpleName,
                errorCauseMessage = rootCause.message?.take(240),
            )
        }
    }
}

private fun Throwable.rootCause(): Throwable {
    var current = this
    var next = current.cause
    while (next != null && next !== current) {
        current = next
        next = current.cause
    }
    return current
}

private fun verifiedAdapterModelFile(context: Context, modelPath: String?): File {
    require(!modelPath.isNullOrBlank()) { "modelPath is required" }
    require(modelPath.endsWith(".litertlm")) { "modelPath must point to a .litertlm file" }

    val modelFile = File(modelPath).canonicalFile
    val allowedRoot = requireNotNull(context.getExternalFilesDir("models")) {
        "external model directory unavailable"
    }.canonicalFile
    require(modelFile.startsWithPath(allowedRoot)) {
        "modelPath must be under the app-owned GOFFY model directory"
    }
    require(modelFile.isFile) { "modelPath does not exist" }
    require(modelFile.length() in 1..(512L * 1024L * 1024L)) {
        "model file must be 1..512 MB for GOFFY LITE adapter smoke"
    }
    return modelFile
}

private fun adapterSmokeResultFile(context: Context, resultPath: String?): File {
    val defaultDir = requireNotNull(context.getExternalFilesDir("benchmarks")) {
        "external benchmark directory unavailable"
    }
    val file = if (resultPath.isNullOrBlank()) {
        File(defaultDir, "litertlm-adapter-smoke.json")
    } else {
        File(resultPath)
    }.canonicalFile
    val allowedRoot = defaultDir.canonicalFile
    require(file.startsWithPath(allowedRoot)) {
        "resultPath must stay under the app-owned benchmark directory"
    }
    return file
}

private fun File.startsWithPath(root: File): Boolean =
    path == root.path || path.startsWith(root.path + File.separator)

private fun elapsedMillis(block: () -> Unit): Long {
    val start = SystemClock.elapsedRealtime()
    block()
    return SystemClock.elapsedRealtime() - start
}

private fun StringBuilder.appendJson(key: String, value: String?, trailing: Boolean = true) {
    append("  \"")
    append(key.escapeJson())
    append("\": ")
    if (value == null) {
        append("null")
    } else {
        append("\"")
        append(value.escapeJson())
        append("\"")
    }
    if (trailing) append(",")
    append("\n")
}

private fun StringBuilder.appendJson(key: String, value: Number?, trailing: Boolean = true) {
    append("  \"")
    append(key.escapeJson())
    append("\": ")
    append(value?.toString() ?: "null")
    if (trailing) append(",")
    append("\n")
}

private fun StringBuilder.appendJson(key: String, value: Boolean, trailing: Boolean = true) {
    append("  \"")
    append(key.escapeJson())
    append("\": ")
    append(value)
    if (trailing) append(",")
    append("\n")
}

private fun String.escapeJson(): String =
    buildString {
        for (char in this@escapeJson) {
            when (char) {
                '\\' -> append("\\\\")
                '"' -> append("\\\"")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> append(char)
            }
        }
    }
