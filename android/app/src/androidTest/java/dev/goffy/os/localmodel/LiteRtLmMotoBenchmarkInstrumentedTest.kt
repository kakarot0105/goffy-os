package dev.goffy.os.localmodel

import android.app.ActivityManager
import android.content.Context
import android.os.BatteryManager
import android.os.Build
import android.os.Debug
import android.os.PowerManager
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

private const val MAX_MODEL_BYTES = 512L * 1024L * 1024L
private const val MAX_PROMPT_CHARS = 512
private const val MAX_OUTPUT_PREVIEW_CHARS = 320
private const val DEFAULT_TIMEOUT_MILLIS = 120_000L
private const val MIN_TIMEOUT_MILLIS = 5_000L
private const val MAX_TIMEOUT_MILLIS = 300_000L

class LiteRtLmMotoBenchmarkInstrumentedTest {
    @Test
    fun benchmarkOnePromptOnCpu() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val args = InstrumentationRegistry.getArguments()
        val modelPath = args.getString("modelPath")
        assumeTrue("Pass -e modelPath to run the real Moto benchmark.", !modelPath.isNullOrBlank())

        val prompt = args.getString("prompt") ?: "Classify this GOFFY command: show my battery status"
        require(prompt.isNotBlank() && prompt.length <= MAX_PROMPT_CHARS) {
            "benchmark prompt must be 1..$MAX_PROMPT_CHARS characters"
        }
        val timeoutMillis = args.getString("timeoutMillis")
            ?.toLongOrNull()
            ?.coerceIn(MIN_TIMEOUT_MILLIS, MAX_TIMEOUT_MILLIS)
            ?: DEFAULT_TIMEOUT_MILLIS
        val resultFile = benchmarkResultFile(context, args.getString("resultPath"))
        val modelFile = verifiedModelFile(context, modelPath)

        val result = try {
            withTimeout(timeoutMillis) {
                runBenchmark(context, modelFile, prompt)
            }
        } catch (throwable: Throwable) {
            MotoLocalModelBenchmarkResult.failure(
                context = context,
                modelFile = modelFile,
                prompt = prompt,
                error = throwable,
            )
        }

        resultFile.parentFile?.mkdirs()
        resultFile.writeText(result.toJson(), Charsets.UTF_8)
        println("GOFFY_LITERTLM_BENCHMARK_JSON=${resultFile.absolutePath}")

        assertTrue(result.errorClass ?: "benchmark completed", result.errorClass == null)
        assertTrue("model must emit at least one chunk", result.outputChunkCount > 0)
    }

    private suspend fun runBenchmark(
        context: Context,
        modelFile: File,
        prompt: String,
    ): MotoLocalModelBenchmarkResult = withContext(kotlinx.coroutines.Dispatchers.Default) {
        Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
        val memoryBefore = currentMemory()
        val wallStartMillis = System.currentTimeMillis()

        var initMillis = 0L
        var generationMillis = 0L
        var firstChunkMillis: Long? = null
        var outputChunkCount = 0
        var outputCharCount = 0
        val outputPreview = StringBuilder()

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
                    if (outputPreview.length < MAX_OUTPUT_PREVIEW_CHARS) {
                        outputPreview.append(text.take(MAX_OUTPUT_PREVIEW_CHARS - outputPreview.length))
                    }
                }
                generationMillis = SystemClock.elapsedRealtime() - generationStart
            }
        }

        val memoryAfter = currentMemory()
        MotoLocalModelBenchmarkResult.success(
            context = context,
            modelFile = modelFile,
            prompt = prompt,
            wallStartMillis = wallStartMillis,
            initMillis = initMillis,
            firstChunkMillis = firstChunkMillis,
            generationMillis = generationMillis,
            outputChunkCount = outputChunkCount,
            outputCharCount = outputCharCount,
            outputPreview = outputPreview.toString(),
            memoryBefore = memoryBefore,
            memoryAfter = memoryAfter,
        )
    }
}

private data class MotoLocalModelBenchmarkResult(
    val status: String,
    val deviceModel: String,
    val androidSdk: Int,
    val modelPath: String,
    val modelBytes: Long,
    val promptChars: Int,
    val backend: String,
    val wallStartMillis: Long,
    val initMillis: Long?,
    val firstChunkMillis: Long?,
    val generationMillis: Long?,
    val outputChunkCount: Int,
    val outputCharCount: Int,
    val outputCharsPerSecond: Double?,
    val outputPreview: String,
    val batteryPercent: Int?,
    val batteryStatus: Int?,
    val thermalStatus: Int?,
    val availableMemoryBytes: Long?,
    val totalMemoryBytes: Long?,
    val runtimeUsedMemoryBeforeBytes: Long,
    val runtimeUsedMemoryAfterBytes: Long,
    val nativeHeapBeforeBytes: Long,
    val nativeHeapAfterBytes: Long,
    val errorClass: String?,
    val errorMessage: String?,
) {
    fun toJson(): String =
        buildString {
            append("{\n")
            appendJson("status", status)
            appendJson("deviceModel", deviceModel)
            appendJson("androidSdk", androidSdk)
            appendJson("modelPath", modelPath)
            appendJson("modelBytes", modelBytes)
            appendJson("promptChars", promptChars)
            appendJson("backend", backend)
            appendJson("wallStartMillis", wallStartMillis)
            appendJson("initMillis", initMillis)
            appendJson("firstChunkMillis", firstChunkMillis)
            appendJson("generationMillis", generationMillis)
            appendJson("outputChunkCount", outputChunkCount)
            appendJson("outputCharCount", outputCharCount)
            appendJson("outputCharsPerSecond", outputCharsPerSecond)
            appendJson("outputPreview", outputPreview)
            appendJson("batteryPercent", batteryPercent)
            appendJson("batteryStatus", batteryStatus)
            appendJson("thermalStatus", thermalStatus)
            appendJson("availableMemoryBytes", availableMemoryBytes)
            appendJson("totalMemoryBytes", totalMemoryBytes)
            appendJson("runtimeUsedMemoryBeforeBytes", runtimeUsedMemoryBeforeBytes)
            appendJson("runtimeUsedMemoryAfterBytes", runtimeUsedMemoryAfterBytes)
            appendJson("nativeHeapBeforeBytes", nativeHeapBeforeBytes)
            appendJson("nativeHeapAfterBytes", nativeHeapAfterBytes)
            appendJson("errorClass", errorClass)
            appendJson("errorMessage", errorMessage, trailing = false)
            append("\n}\n")
        }

    companion object {
        fun success(
            context: Context,
            modelFile: File,
            prompt: String,
            wallStartMillis: Long,
            initMillis: Long,
            firstChunkMillis: Long?,
            generationMillis: Long,
            outputChunkCount: Int,
            outputCharCount: Int,
            outputPreview: String,
            memoryBefore: RuntimeMemory,
            memoryAfter: RuntimeMemory,
        ): MotoLocalModelBenchmarkResult {
            val deviceState = currentDeviceState(context)
            return MotoLocalModelBenchmarkResult(
                status = "PASS",
                deviceModel = Build.MODEL,
                androidSdk = Build.VERSION.SDK_INT,
                modelPath = modelFile.absolutePath,
                modelBytes = modelFile.length(),
                promptChars = prompt.length,
                backend = "CPU",
                wallStartMillis = wallStartMillis,
                initMillis = initMillis,
                firstChunkMillis = firstChunkMillis,
                generationMillis = generationMillis,
                outputChunkCount = outputChunkCount,
                outputCharCount = outputCharCount,
                outputCharsPerSecond = charsPerSecond(outputCharCount, generationMillis),
                outputPreview = outputPreview,
                batteryPercent = deviceState.batteryPercent,
                batteryStatus = deviceState.batteryStatus,
                thermalStatus = deviceState.thermalStatus,
                availableMemoryBytes = deviceState.availableMemoryBytes,
                totalMemoryBytes = deviceState.totalMemoryBytes,
                runtimeUsedMemoryBeforeBytes = memoryBefore.runtimeUsedBytes,
                runtimeUsedMemoryAfterBytes = memoryAfter.runtimeUsedBytes,
                nativeHeapBeforeBytes = memoryBefore.nativeHeapBytes,
                nativeHeapAfterBytes = memoryAfter.nativeHeapBytes,
                errorClass = null,
                errorMessage = null,
            )
        }

        fun failure(
            context: Context,
            modelFile: File,
            prompt: String,
            error: Throwable,
        ): MotoLocalModelBenchmarkResult {
            val deviceState = currentDeviceState(context)
            val memory = currentMemory()
            return MotoLocalModelBenchmarkResult(
                status = "FAIL",
                deviceModel = Build.MODEL,
                androidSdk = Build.VERSION.SDK_INT,
                modelPath = modelFile.absolutePath,
                modelBytes = modelFile.length(),
                promptChars = prompt.length,
                backend = "CPU",
                wallStartMillis = System.currentTimeMillis(),
                initMillis = null,
                firstChunkMillis = null,
                generationMillis = null,
                outputChunkCount = 0,
                outputCharCount = 0,
                outputCharsPerSecond = null,
                outputPreview = "",
                batteryPercent = deviceState.batteryPercent,
                batteryStatus = deviceState.batteryStatus,
                thermalStatus = deviceState.thermalStatus,
                availableMemoryBytes = deviceState.availableMemoryBytes,
                totalMemoryBytes = deviceState.totalMemoryBytes,
                runtimeUsedMemoryBeforeBytes = memory.runtimeUsedBytes,
                runtimeUsedMemoryAfterBytes = memory.runtimeUsedBytes,
                nativeHeapBeforeBytes = memory.nativeHeapBytes,
                nativeHeapAfterBytes = memory.nativeHeapBytes,
                errorClass = error::class.java.simpleName,
                errorMessage = error.message?.take(240),
            )
        }
    }
}

private data class RuntimeMemory(
    val runtimeUsedBytes: Long,
    val nativeHeapBytes: Long,
)

private data class DeviceState(
    val batteryPercent: Int?,
    val batteryStatus: Int?,
    val thermalStatus: Int?,
    val availableMemoryBytes: Long?,
    val totalMemoryBytes: Long?,
)

private fun verifiedModelFile(context: Context, modelPath: String?): File {
    require(!modelPath.isNullOrBlank()) { "modelPath is required" }
    require(modelPath.endsWith(".litertlm")) { "modelPath must point to a .litertlm file" }

    val modelFile = File(modelPath).canonicalFile
    val allowedRoots = allowedModelRoots(context).map(File::getCanonicalFile)
    require(allowedRoots.any { modelFile.startsWithPath(it) }) {
        "modelPath must be under an app-owned GOFFY model directory"
    }
    require(modelFile.isFile) { "modelPath does not exist" }
    require(modelFile.length() in 1..MAX_MODEL_BYTES) {
        "model file must be 1..$MAX_MODEL_BYTES bytes for GOFFY LITE benchmarking"
    }
    return modelFile
}

private fun benchmarkResultFile(context: Context, resultPath: String?): File {
    val defaultDir = requireNotNull(context.getExternalFilesDir("benchmarks")) {
        "external benchmark directory unavailable"
    }
    val file = if (resultPath.isNullOrBlank()) {
        File(defaultDir, "litertlm-benchmark.json")
    } else {
        File(resultPath)
    }.canonicalFile
    val allowedRoot = defaultDir.canonicalFile
    require(file.startsWithPath(allowedRoot)) {
        "resultPath must stay under the app-owned benchmark directory"
    }
    return file
}

private fun allowedModelRoots(context: Context): List<File> =
    listOfNotNull(
        context.getExternalFilesDir("models"),
        File(context.filesDir, "models"),
    )

private fun File.startsWithPath(root: File): Boolean =
    path == root.path || path.startsWith(root.path + File.separator)

private fun elapsedMillis(block: () -> Unit): Long {
    val start = SystemClock.elapsedRealtime()
    block()
    return SystemClock.elapsedRealtime() - start
}

private fun currentMemory(): RuntimeMemory {
    val runtime = Runtime.getRuntime()
    return RuntimeMemory(
        runtimeUsedBytes = runtime.totalMemory() - runtime.freeMemory(),
        nativeHeapBytes = Debug.getNativeHeapAllocatedSize(),
    )
}

private fun currentDeviceState(context: Context): DeviceState {
    val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
    val activityManager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
    val powerManager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
    val memoryInfo = ActivityManager.MemoryInfo()
    activityManager?.getMemoryInfo(memoryInfo)

    return DeviceState(
        batteryPercent = batteryManager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY),
        batteryStatus = batteryManager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_STATUS),
        thermalStatus = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            powerManager?.currentThermalStatus
        } else {
            null
        },
        availableMemoryBytes = if (activityManager == null) null else memoryInfo.availMem,
        totalMemoryBytes = if (activityManager == null) null else memoryInfo.totalMem,
    )
}

private fun charsPerSecond(chars: Int, millis: Long): Double? =
    if (millis <= 0L) null else chars.toDouble() / (millis.toDouble() / 1000.0)

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
    if (trailing) {
        append(",")
    }
    append("\n")
}

private fun StringBuilder.appendJson(key: String, value: Number?, trailing: Boolean = true) {
    append("  \"")
    append(key.escapeJson())
    append("\": ")
    append(value?.toString() ?: "null")
    if (trailing) {
        append(",")
    }
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
                else -> if (char.code < 0x20) {
                    append("\\u")
                    append(char.code.toString(16).padStart(4, '0'))
                } else {
                    append(char)
                }
            }
        }
    }
