package dev.goffy.os.localmodel

private const val MAX_MODEL_FILE_BYTES = 512L * 1024L * 1024L
private const val MAX_PROMPT_CHARS = 512
private const val MAX_MODEL_OUTPUT_CHARS = 256
private const val MAX_CANDIDATE_TEXT_CHARS = 160
private const val DEFAULT_IDLE_UNLOAD_MILLIS = 60_000L
private const val DEFAULT_GENERATION_TIMEOUT_MILLIS = 15_000L
private const val MIN_ROUTING_CONFIDENCE = 0.70f
private val allowedRoutingLabels = setOf("PHONE", "MAC", "CLOUD")
private val strictRoutingJson = Regex(
    pattern = """\{\s*"route"\s*:\s*"(PHONE|MAC|CLOUD)"\s*,\s*"confidence"\s*:\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*\}""",
)

data class LocalModelRuntimePolicy(
    val enabled: Boolean = false,
    val maxModelFileBytes: Long = MAX_MODEL_FILE_BYTES,
    val maxPromptChars: Int = MAX_PROMPT_CHARS,
    val maxModelOutputChars: Int = MAX_MODEL_OUTPUT_CHARS,
    val minRoutingConfidence: Float = MIN_ROUTING_CONFIDENCE,
    val idleUnloadMillis: Long = DEFAULT_IDLE_UNLOAD_MILLIS,
    val generationTimeoutMillis: Long = DEFAULT_GENERATION_TIMEOUT_MILLIS,
) {
    init {
        require(maxModelFileBytes in 1L..MAX_MODEL_FILE_BYTES) {
            "local model file budget must fit GOFFY LITE"
        }
        require(maxPromptChars in 1..MAX_PROMPT_CHARS) {
            "local model prompt budget must fit GOFFY LITE"
        }
        require(maxModelOutputChars in 1..MAX_MODEL_OUTPUT_CHARS) {
            "local model output budget must fit GOFFY LITE"
        }
        require(minRoutingConfidence in 0.0f..1.0f) {
            "local model routing confidence must stay bounded"
        }
        require(idleUnloadMillis in 1_000L..300_000L) {
            "local model idle unload must stay bounded"
        }
        require(generationTimeoutMillis in 1_000L..60_000L) {
            "local model generation timeout must stay bounded"
        }
    }
}

data class LocalModelIntentCandidate(
    val intentLabel: String,
    val confidence: Float,
    val normalizedCommand: String,
    val rationale: String,
) {
    init {
        require(intentLabel.isSafeBoundedText()) { "intent label is not safe bounded text" }
        require(normalizedCommand.isSafeBoundedText()) { "normalized command is not safe bounded text" }
        require(rationale.isSafeBoundedText()) { "rationale is not safe bounded text" }
        require(confidence in 0.0f..1.0f) { "confidence must be between 0 and 1" }
    }
}

sealed interface LocalModelIntentObservation {
    data class Disabled(val reason: String) : LocalModelIntentObservation

    data class Candidate(val candidate: LocalModelIntentCandidate) : LocalModelIntentObservation

    data class Rejected(val reason: String) : LocalModelIntentObservation
}

fun interface LocalModelIntentFallback {
    fun observeUnsupportedCommand(command: String): LocalModelIntentObservation
}

object DisabledLocalModelIntentFallback : LocalModelIntentFallback {
    override fun observeUnsupportedCommand(command: String): LocalModelIntentObservation =
        LocalModelIntentObservation.Disabled(
            "Local model fallback is disabled; deterministic routing remains authoritative.",
        )
}

fun isSafeLocalModelPrompt(command: String, policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy()): Boolean =
    command.isNotBlank() &&
        command.length <= policy.maxPromptChars &&
        command.none(Char::isUnsafeModelTextCharacter)

fun evaluateLocalModelRoutingOutput(
    command: String,
    output: String,
    policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(),
): LocalModelIntentObservation {
    if (!policy.enabled) {
        return LocalModelIntentObservation.Disabled(
            "Local model fallback is disabled; deterministic routing remains authoritative.",
        )
    }
    if (!isSafeLocalModelPrompt(command, policy)) {
        return LocalModelIntentObservation.Rejected(
            "Command is outside local model prompt safety bounds.",
        )
    }
    val trimmedOutput = output.trim()
    if (!isSafeLocalModelOutput(trimmedOutput, policy)) {
        return LocalModelIntentObservation.Rejected(
            "Model output is outside local routing quality bounds.",
        )
    }
    if (trimmedOutput.contains("<think", ignoreCase = true) ||
        trimmedOutput.contains("</think", ignoreCase = true)
    ) {
        return LocalModelIntentObservation.Rejected(
            "Model output included hidden reasoning text.",
        )
    }
    val match = strictRoutingJson.matchEntire(trimmedOutput)
        ?: return LocalModelIntentObservation.Rejected(
            "Model output did not match the strict routing JSON schema.",
        )
    val route = match.groupValues[1]
    val confidence = match.groupValues[2].toFloatOrNull()
        ?: return LocalModelIntentObservation.Rejected(
            "Model confidence was not a valid number.",
        )
    if (route !in allowedRoutingLabels) {
        return LocalModelIntentObservation.Rejected("Model returned an unsupported route label.")
    }
    if (confidence < policy.minRoutingConfidence) {
        return LocalModelIntentObservation.Rejected(
            "Model confidence is below the local routing threshold.",
        )
    }
    val normalizedCommand = command.trim()
    if (!isSafeLocalModelCandidateText(normalizedCommand)) {
        return LocalModelIntentObservation.Rejected(
            "Normalized command is outside local candidate quality bounds.",
        )
    }
    return LocalModelIntentObservation.Candidate(
        LocalModelIntentCandidate(
            intentLabel = route,
            confidence = confidence,
            normalizedCommand = normalizedCommand,
            rationale = "Strict local model routing JSON passed.",
        ),
    )
}

fun isSafeLocalModelOutput(
    output: String,
    policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(),
): Boolean =
    output.isNotBlank() &&
        output.length <= policy.maxModelOutputChars &&
        output.none(Char::isUnsafeModelTextCharacter)

fun isSafeLocalModelCandidateText(text: String): Boolean = text.isSafeBoundedText()

private fun String.isSafeBoundedText(): Boolean =
    isNotBlank() &&
        length <= MAX_CANDIDATE_TEXT_CHARS &&
        none(Char::isUnsafeModelTextCharacter)

private fun Char.isUnsafeModelTextCharacter(): Boolean =
    isISOControl() || Character.getType(this) == Character.FORMAT.toInt()
