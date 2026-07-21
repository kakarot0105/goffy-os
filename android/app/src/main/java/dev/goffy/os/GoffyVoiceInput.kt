package dev.goffy.os

data class GoffyVoiceInputState(
    val listening: Boolean = false,
    val notice: String? = null,
    val warning: Boolean = false,
)

internal fun String.toSafeRecognizedCommand(): String? =
    replace(Regex("\\p{Cntrl}+"), " ")
        .replace(Regex("\\s+"), " ")
        .trim()
        .take(MAX_RECOGNIZED_COMMAND_LENGTH)
        .ifEmpty { null }

private const val MAX_RECOGNIZED_COMMAND_LENGTH = 2_000
