package dev.goffy.os.localmodel

import android.content.Context
import android.os.Build
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test

private const val DEFAULT_TFLITE_TIMEOUT_MILLIS = 30_000L
private const val MAX_TFLITE_TIMEOUT_MILLIS = 120_000L
private const val MAX_TFLITE_MODEL_BYTES = 8L * 1024L * 1024L
private const val DEFAULT_TFLITE_COMMAND = "show my battery status"

class TfliteTaskTextClassifierInstrumentedTest {
    @Test
    fun benchmarkClassifierThroughGoffyBoundary() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val args = InstrumentationRegistry.getArguments()
        val modelPath = args.getString("modelPath")
        assumeTrue("Pass -e modelPath to run the real TFLite classifier benchmark.", !modelPath.isNullOrBlank())

        val command = args.getString("command") ?: DEFAULT_TFLITE_COMMAND
        val timeoutMillis = args.getString("timeoutMillis")
            ?.toLongOrNull()
            ?.coerceIn(5_000L, MAX_TFLITE_TIMEOUT_MILLIS)
            ?: DEFAULT_TFLITE_TIMEOUT_MILLIS
        val resultFile = tfliteResultFile(context, args.getString("resultPath"))
        val modelRoot = requireNotNull(context.getExternalFilesDir("models")) {
            "external model directory unavailable"
        }.canonicalFile
        val modelFile = verifiedTfliteModelFile(modelRoot, modelPath)

        val result = try {
            val report = withTimeout(timeoutMillis) {
                withContext(kotlinx.coroutines.Dispatchers.Default) {
                    TfliteTaskTextIntentClassifier(
                        modelRoot = modelRoot,
                        modelFile = modelFile,
                    ).classify(command)
                }
            }
            TfliteTaskTextBenchmarkResult.success(
                modelFile = modelFile,
                command = command,
                report = report,
            )
        } catch (throwable: Throwable) {
            TfliteTaskTextBenchmarkResult.failure(
                modelFile = modelFile,
                command = command,
                error = throwable,
            )
        }

        resultFile.parentFile?.mkdirs()
        resultFile.writeText(result.toJson(), Charsets.UTF_8)
        println("GOFFY_TFLITE_TASK_TEXT_CLASSIFIER_JSON=${resultFile.absolutePath}")

        assertTrue("TFLite Task Text benchmark JSON should be written", resultFile.isFile)
    }
}

private data class TfliteTaskTextBenchmarkResult(
    val status: String,
    val deviceModel: String,
    val androidSdk: Int,
    val modelPath: String,
    val modelBytes: Long,
    val commandChars: Int,
    val initMillis: Long?,
    val inferenceMillis: Long?,
    val categoryCount: Int,
    val topLabel: String?,
    val topScore: Float?,
    val observationType: String?,
    val observationRoute: String?,
    val observationConfidence: Float?,
    val observationReason: String?,
    val nonAuthoritative: Boolean,
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
            appendJson("commandChars", commandChars)
            appendJson("initMillis", initMillis)
            appendJson("inferenceMillis", inferenceMillis)
            appendJson("categoryCount", categoryCount)
            appendJson("topLabel", topLabel)
            appendJson("topScore", topScore)
            appendJson("observationType", observationType)
            appendJson("observationRoute", observationRoute)
            appendJson("observationConfidence", observationConfidence)
            appendJson("observationReason", observationReason)
            appendJson("nonAuthoritative", nonAuthoritative)
            appendJson("errorClass", errorClass)
            appendJson("errorMessage", errorMessage, trailing = false)
            append("\n}\n")
        }

    companion object {
        fun success(
            modelFile: File,
            command: String,
            report: TfliteTaskTextClassificationReport,
        ): TfliteTaskTextBenchmarkResult {
            val observation = report.observation
            val topCategory = report.categories.firstOrNull()
            val terminalObservation = observation is LocalModelIntentObservation.Candidate ||
                observation is LocalModelIntentObservation.Rejected
            return TfliteTaskTextBenchmarkResult(
                status = if (terminalObservation && report.categories.isNotEmpty()) "PASS" else "FAIL",
                deviceModel = Build.MODEL,
                androidSdk = Build.VERSION.SDK_INT,
                modelPath = modelFile.absolutePath,
                modelBytes = report.modelBytes,
                commandChars = report.commandChars,
                initMillis = report.initMillis,
                inferenceMillis = report.inferenceMillis,
                categoryCount = report.categories.size,
                topLabel = topCategory?.label,
                topScore = topCategory?.score,
                observationType = observation::class.java.simpleName,
                observationRoute = (observation as? LocalModelIntentObservation.Candidate)
                    ?.candidate
                    ?.intentLabel,
                observationConfidence = (observation as? LocalModelIntentObservation.Candidate)
                    ?.candidate
                    ?.confidence,
                observationReason = (observation as? LocalModelIntentObservation.Rejected)?.reason,
                nonAuthoritative = report.nonAuthoritative,
                errorClass = null,
                errorMessage = null,
            )
        }

        fun failure(
            modelFile: File,
            command: String,
            error: Throwable,
        ): TfliteTaskTextBenchmarkResult =
            TfliteTaskTextBenchmarkResult(
                status = "FAIL",
                deviceModel = Build.MODEL,
                androidSdk = Build.VERSION.SDK_INT,
                modelPath = modelFile.absolutePath,
                modelBytes = modelFile.length(),
                commandChars = command.length,
                initMillis = null,
                inferenceMillis = null,
                categoryCount = 0,
                topLabel = null,
                topScore = null,
                observationType = null,
                observationRoute = null,
                observationConfidence = null,
                observationReason = null,
                nonAuthoritative = true,
                errorClass = error::class.java.simpleName,
                errorMessage = error.message?.take(240),
            )
    }
}

private fun verifiedTfliteModelFile(modelRoot: File, modelPath: String?): File {
    require(!modelPath.isNullOrBlank()) { "modelPath is required" }
    require(modelPath.endsWith(".tflite")) { "modelPath must point to a .tflite file" }

    val modelFile = File(modelPath).canonicalFile
    require(modelFile.startsWithPath(modelRoot)) {
        "modelPath must be under the app-owned GOFFY model directory"
    }
    require(modelFile.isFile) { "modelPath does not exist" }
    require(modelFile.length() in 1..MAX_TFLITE_MODEL_BYTES) {
        "model file must be 1..$MAX_TFLITE_MODEL_BYTES bytes for tiny-classifier benchmarking"
    }
    return modelFile
}

private fun tfliteResultFile(context: Context, resultPath: String?): File {
    val defaultDir = requireNotNull(context.getExternalFilesDir("benchmarks")) {
        "external benchmark directory unavailable"
    }
    val file = if (resultPath.isNullOrBlank()) {
        File(defaultDir, "tflite-task-text-classifier.json")
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
                else -> if (char.code < 0x20) {
                    append("\\u")
                    append(char.code.toString(16).padStart(4, '0'))
                } else {
                    append(char)
                }
            }
        }
    }
