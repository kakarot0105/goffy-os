package dev.goffy.os.localmodel

import java.util.Locale

private const val MIN_MICRO_INTENT_SCORE = 2

object MicroIntentLocalModelFallback : LocalModelIntentFallback {
    private val whitespace = Regex("\\s+")
    private val classes = listOf(
        MicroIntentClass(
            intentLabel = "PHONE",
            phrases = listOf(
                "battery status",
                "battery level",
                "turn on flashlight",
                "turn off flashlight",
                "set a timer",
                "create a note",
                "read qr",
                "scan qr",
                "read text",
            ),
            keywords = setOf(
                "phone",
                "device",
                "battery",
                "timer",
                "reminder",
                "note",
                "flashlight",
                "torch",
                "camera",
                "photo",
                "qr",
                "barcode",
                "ocr",
                "notification",
                "microphone",
                "voice",
                "speak",
                "alarm",
            ),
            rationale = "Matched phone-local capability language.",
        ),
        MicroIntentClass(
            intentLabel = "MAC",
            phrases = listOf(
                "my mac",
                "mac status",
                "mac files",
                "run tests",
                "open my project",
                "git status",
                "largest files",
                "mac clipboard",
                "apple shortcut",
            ),
            keywords = setOf(
                "mac",
                "project",
                "repo",
                "repository",
                "files",
                "file",
                "git",
                "tests",
                "test",
                "docker",
                "clipboard",
                "browser",
                "shortcut",
                "shortcuts",
                "code",
                "build",
            ),
            rationale = "Matched Mac Hub capability language.",
        ),
        MicroIntentClass(
            intentLabel = "CLOUD",
            phrases = listOf(
                "search the web",
                "current news",
                "latest news",
                "pull request",
                "external api",
            ),
            keywords = setOf(
                "cloud",
                "web",
                "internet",
                "online",
                "latest",
                "current",
                "news",
                "research",
                "github",
                "api",
                "external",
            ),
            rationale = "Matched external or current-information language.",
        ),
    )
    private val riskyUnsupportedTerms = setOf(
        "delete",
        "erase",
        "wipe",
        "format",
        "factory",
        "reset",
        "disable",
        "exfiltrate",
        "password",
        "secret",
        "credential",
        "keychain",
        "install",
    )

    override fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
        val normalized = command.trim().replace(whitespace, " ")
        if (!isSafeLocalModelPrompt(normalized) || !isSafeLocalModelCandidateText(normalized)) {
            return LocalModelIntentObservation.Rejected(
                "Command is outside micro intent fallback safety bounds.",
            )
        }

        val lower = normalized.lowercase(Locale.US)
        val tokens = lower.tokenSet()
        if (riskyUnsupportedTerms.any { term -> term in tokens }) {
            return LocalModelIntentObservation.Rejected(
                "Micro intent fallback refused a risky unsupported command.",
            )
        }

        val scored = classes
            .map { candidateClass -> candidateClass to candidateClass.score(lower, tokens) }
            .filter { (_, score) -> score >= MIN_MICRO_INTENT_SCORE }
            .sortedByDescending { (_, score) -> score }

        val winner = scored.firstOrNull()
            ?: return LocalModelIntentObservation.Rejected(
                "Micro intent fallback found no confident PHONE, MAC, or CLOUD target.",
            )
        val runnerUp = scored.drop(1).firstOrNull()
        if (runnerUp != null && runnerUp.second == winner.second) {
            return LocalModelIntentObservation.Rejected(
                "Micro intent fallback found ambiguous target language.",
            )
        }

        val (candidateClass, score) = winner
        return LocalModelIntentObservation.Candidate(
            LocalModelIntentCandidate(
                intentLabel = candidateClass.intentLabel,
                confidence = score.toConfidence(),
                normalizedCommand = normalized,
                rationale = candidateClass.rationale,
            ),
        )
    }
}

private data class MicroIntentClass(
    val intentLabel: String,
    val phrases: List<String>,
    val keywords: Set<String>,
    val rationale: String,
) {
    fun score(lowerCommand: String, tokens: Set<String>): Int =
        phrases.count { phrase -> lowerCommand.contains(phrase) } * 3 +
            keywords.count { keyword -> keyword in tokens }
}

private fun String.tokenSet(): Set<String> =
    split(Regex("[^a-z0-9]+"))
        .filter(String::isNotBlank)
        .toSet()

private fun Int.toConfidence(): Float = when {
    this >= 6 -> 0.88f
    this >= 4 -> 0.82f
    else -> 0.74f
}
