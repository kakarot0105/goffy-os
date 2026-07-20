package dev.goffy.os.localmodel

private const val MAX_MODEL_FILE_BYTES = 512L * 1024L * 1024L
private const val MAX_PROMPT_CHARS = 512
private const val MAX_CANDIDATE_TEXT_CHARS = 160
private const val DEFAULT_IDLE_UNLOAD_MILLIS = 60_000L

data class LocalModelRuntimePolicy(
    val enabled: Boolean = false,
    val maxModelFileBytes: Long = MAX_MODEL_FILE_BYTES,
    val maxPromptChars: Int = MAX_PROMPT_CHARS,
    val idleUnloadMillis: Long = DEFAULT_IDLE_UNLOAD_MILLIS,
) {
    init {
        require(maxModelFileBytes in 1L..MAX_MODEL_FILE_BYTES) {
            "local model file budget must fit GOFFY LITE"
        }
        require(maxPromptChars in 1..MAX_PROMPT_CHARS) {
            "local model prompt budget must fit GOFFY LITE"
        }
        require(idleUnloadMillis in 1_000L..300_000L) {
            "local model idle unload must stay bounded"
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

private fun String.isSafeBoundedText(): Boolean =
    isNotBlank() &&
        length <= MAX_CANDIDATE_TEXT_CHARS &&
        none(Char::isUnsafeModelTextCharacter)

private fun Char.isUnsafeModelTextCharacter(): Boolean =
    isISOControl() || Character.getType(this) == Character.FORMAT.toInt()
