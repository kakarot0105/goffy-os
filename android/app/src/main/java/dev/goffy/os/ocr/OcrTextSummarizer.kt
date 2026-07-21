package dev.goffy.os.ocr

import dev.goffy.os.protocol.MAX_OCR_CHARACTER_COUNT
import dev.goffy.os.protocol.MAX_OCR_LINE_COUNT
import dev.goffy.os.protocol.MAX_OCR_PREVIEW_LENGTH
import dev.goffy.os.protocol.PHONE_OCR_STATUS_AVAILABLE
import dev.goffy.os.protocol.PhoneOcrRead
import java.util.Locale

internal object OcrTextSummarizer {
    fun summarize(rawText: String): PhoneOcrRead {
        val lines = rawText.lineSequence()
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .toList()
        val collapsed = lines.joinToString(" ").replace(whitespace, " ").trim()
        val characterCount = collapsed.length.coerceIn(1, MAX_OCR_CHARACTER_COUNT)
        val lineCount = lines.size.coerceIn(1, MAX_OCR_LINE_COUNT)
        val characterCountTruncated = collapsed.length > MAX_OCR_CHARACTER_COUNT
        val lineCountTruncated = lines.size > MAX_OCR_LINE_COUNT

        if (collapsed.isEmpty() || containsUnsafeDisplayCharacter(collapsed) || looksSensitive(collapsed)) {
            return redacted(
                characterCount = characterCount,
                characterCountTruncated = characterCountTruncated,
                lineCount = lineCount,
                lineCountTruncated = lineCountTruncated,
            )
        }

        val preview = collapsed.take(MAX_OCR_PREVIEW_LENGTH)
        return PhoneOcrRead(
            status = PHONE_OCR_STATUS_AVAILABLE,
            script = OCR_SCRIPT_LATIN,
            characterCount = characterCount,
            characterCountTruncated = characterCountTruncated,
            lineCount = lineCount,
            lineCountTruncated = lineCountTruncated,
            preview = preview,
            previewTruncated = collapsed.length > MAX_OCR_PREVIEW_LENGTH ||
                characterCountTruncated ||
                lineCountTruncated,
            redacted = false,
        )
    }

    private fun redacted(
        characterCount: Int,
        characterCountTruncated: Boolean,
        lineCount: Int,
        lineCountTruncated: Boolean,
    ): PhoneOcrRead = PhoneOcrRead(
        status = PHONE_OCR_STATUS_AVAILABLE,
        script = OCR_SCRIPT_LATIN,
        characterCount = characterCount,
        characterCountTruncated = characterCountTruncated,
        lineCount = lineCount,
        lineCountTruncated = lineCountTruncated,
        preview = null,
        previewTruncated = false,
        redacted = true,
    )

    private fun containsUnsafeDisplayCharacter(value: String): Boolean =
        value.any { character ->
            character == '\u0000' || Character.getType(character) == Character.FORMAT.toInt()
        }

    private fun looksSensitive(value: String): Boolean {
        val lower = value.lowercase(Locale.US)
        return sensitiveMarkers.any { marker -> lower.contains(marker) } ||
            paymentCardLikeDigits.containsMatchIn(value)
    }

    private val whitespace = Regex("\\s+")
    private const val OCR_SCRIPT_LATIN = "latin"
    private val paymentCardLikeDigits = Regex("(?:\\d[ -]?){13,19}")
    private val sensitiveMarkers = listOf(
        "password",
        "passwd",
        "secret",
        "token",
        "bearer ",
        "api key",
        "api_key",
        "apikey",
        "private key",
        "private_key",
        "client secret",
        "client_secret",
        "otp",
        "recovery code",
    )
}
