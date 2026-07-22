package dev.goffy.os.localmodel

import android.os.SystemClock
import java.io.File
import java.io.IOException
import java.util.Locale
import org.tensorflow.lite.support.label.Category
import org.tensorflow.lite.task.text.nlclassifier.NLClassifier

private const val MAX_TFLITE_CLASSIFIER_MODEL_BYTES = 8L * 1024L * 1024L
private const val MAX_TFLITE_CATEGORY_COUNT = 8
private const val TFLITE_CLASSIFIER_MIN_CONFIDENCE = 0.70f
private val allowedTfliteClassifierLabels = setOf("PHONE", "MAC", "CLOUD")

data class TfliteTaskTextCategory(
    val label: String,
    val score: Float,
) {
    init {
        require(label.isSafeTfliteClassifierText()) { "category label is not safe bounded text" }
        require(score in 0.0f..1.0f) { "category score must be between 0 and 1" }
    }
}

data class TfliteTaskTextClassificationReport(
    val commandChars: Int,
    val modelBytes: Long,
    val initMillis: Long,
    val inferenceMillis: Long,
    val categories: List<TfliteTaskTextCategory>,
    val observation: LocalModelIntentObservation,
    val nonAuthoritative: Boolean = true,
)

class TfliteTaskTextIntentClassifier(
    private val modelRoot: File,
    private val modelFile: File,
    private val policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(
        enabled = true,
        maxModelFileBytes = MAX_TFLITE_CLASSIFIER_MODEL_BYTES,
        minRoutingConfidence = TFLITE_CLASSIFIER_MIN_CONFIDENCE,
        generationTimeoutMillis = 5_000L,
    ),
) {
    fun classify(command: String): TfliteTaskTextClassificationReport {
        val normalizedCommand = validateTfliteTaskTextClassifierInput(
            command = command,
            modelRoot = modelRoot,
            modelFile = modelFile,
            policy = policy,
        )

        val initStarted = SystemClock.elapsedRealtime()
        NLClassifier.createFromFile(modelFile).use { classifier ->
            val initMillis = SystemClock.elapsedRealtime() - initStarted
            val inferenceStarted = SystemClock.elapsedRealtime()
            val categories = classifier.classify(normalizedCommand)
                .asSequence()
                .mapNotNull(::toSafeCategory)
                .sortedByDescending(TfliteTaskTextCategory::score)
                .take(MAX_TFLITE_CATEGORY_COUNT)
                .toList()
            val inferenceMillis = SystemClock.elapsedRealtime() - inferenceStarted
            return TfliteTaskTextClassificationReport(
                commandChars = normalizedCommand.length,
                modelBytes = modelFile.length(),
                initMillis = initMillis,
                inferenceMillis = inferenceMillis,
                categories = categories,
                observation = tfliteTaskTextCategoriesToObservation(
                    normalizedCommand = normalizedCommand,
                    categories = categories,
                ),
            )
        }
    }
}

private fun toSafeCategory(category: Category): TfliteTaskTextCategory? {
    val label = category.label.trim()
    val score = category.score
    if (!label.isSafeTfliteClassifierText() || score !in 0.0f..1.0f) {
        return null
    }
    return TfliteTaskTextCategory(label, score)
}

internal fun validateTfliteTaskTextClassifierInput(
    command: String,
    modelRoot: File,
    modelFile: File,
    policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(
        enabled = true,
        maxModelFileBytes = MAX_TFLITE_CLASSIFIER_MODEL_BYTES,
    ),
): String {
    val normalizedCommand = command.trim()
    if (!isSafeLocalModelPrompt(normalizedCommand, policy)) {
        throw IllegalArgumentException("Command is outside TFLite classifier prompt bounds.")
    }
    if (!isSafeLocalModelCandidateText(normalizedCommand)) {
        throw IllegalArgumentException("Command is outside TFLite classifier candidate bounds.")
    }
    val root = modelRoot.canonicalFile
    val file = modelFile.canonicalFile
    if (!root.isDirectory) {
        throw IOException("Approved TFLite classifier model directory is unavailable.")
    }
    if (!file.isUnder(root)) {
        throw SecurityException("TFLite classifier model file must stay under app-owned storage.")
    }
    if (!file.name.endsWith(".tflite")) {
        throw IllegalArgumentException("TFLite classifier model file must be a .tflite file.")
    }
    if (!file.isFile) {
        throw IOException("TFLite classifier model file is unavailable.")
    }
    if (file.length() !in 1L..MAX_TFLITE_CLASSIFIER_MODEL_BYTES) {
        throw IllegalArgumentException("TFLite classifier model exceeds the GOFFY tiny-model budget.")
    }
    return normalizedCommand
}

internal fun tfliteTaskTextCategoriesToObservation(
    normalizedCommand: String,
    categories: List<TfliteTaskTextCategory>,
): LocalModelIntentObservation {
    val top = categories.firstOrNull()
        ?: return LocalModelIntentObservation.Rejected(
            "TFLite Task Text classifier returned no safe categories.",
        )
    val runnerUp = categories.drop(1).firstOrNull()
    if (runnerUp != null && runnerUp.score == top.score) {
        return LocalModelIntentObservation.Rejected(
            "TFLite Task Text classifier returned an ambiguous top score.",
        )
    }
    val route = top.label.uppercase(Locale.US)
    if (route !in allowedTfliteClassifierLabels) {
        return LocalModelIntentObservation.Rejected(
            "TFLite Task Text classifier top label is not a GOFFY route.",
        )
    }
    if (top.score < TFLITE_CLASSIFIER_MIN_CONFIDENCE) {
        return LocalModelIntentObservation.Rejected(
            "TFLite Task Text classifier confidence is below the routing threshold.",
        )
    }
    return LocalModelIntentObservation.Candidate(
        LocalModelIntentCandidate(
            intentLabel = route,
            confidence = top.score,
            normalizedCommand = normalizedCommand,
            rationale = "TFLite Task Text classifier top category matched a GOFFY route.",
        ),
    )
}

private fun File.isUnder(root: File): Boolean {
    val canonicalRoot = root.canonicalFile.path.trimEnd(File.separatorChar)
    val canonicalPath = canonicalFile.path
    return canonicalPath.startsWith("$canonicalRoot${File.separator}")
}

private fun String.isSafeTfliteClassifierText(): Boolean =
    isNotBlank() &&
        length <= 80 &&
        none { it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt() }
