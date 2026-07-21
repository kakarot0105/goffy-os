package dev.goffy.os.qr

import dev.goffy.os.protocol.MAX_QR_PAYLOAD_CHARACTER_COUNT
import dev.goffy.os.protocol.MAX_QR_PREVIEW_LENGTH
import dev.goffy.os.protocol.PHONE_QR_STATUS_AVAILABLE
import dev.goffy.os.protocol.PhoneQrRead
import java.net.URI
import java.util.Locale

internal object QrPayloadSummarizer {
    fun summarize(rawPayload: String): PhoneQrRead {
        val normalized = rawPayload.trim()
        val characterCount = normalized.length.coerceIn(1, MAX_QR_PAYLOAD_CHARACTER_COUNT)
        val characterCountTruncated = normalized.length > MAX_QR_PAYLOAD_CHARACTER_COUNT
        val displayPayload = normalized.replace(whitespace, " ")
        if (normalized.isEmpty() || containsUnsafeDisplayCharacter(normalized)) {
            return redacted("unknown", characterCount, characterCountTruncated)
        }

        val contentType = classify(displayPayload)
        if (contentType in redactedContentTypes ||
            (contentType != "url" && containsSensitiveMarker(displayPayload))
        ) {
            return redacted(contentType, characterCount, characterCountTruncated)
        }

        val previewSource = if (contentType == "url") {
            safeUrlPreview(displayPayload) ?: return redacted("url", characterCount, characterCountTruncated)
        } else {
            displayPayload
        }
        val preview = previewSource.take(MAX_QR_PREVIEW_LENGTH)
        return PhoneQrRead(
            status = PHONE_QR_STATUS_AVAILABLE,
            contentType = contentType,
            characterCount = characterCount,
            characterCountTruncated = characterCountTruncated,
            preview = preview,
            previewTruncated = previewSource.length > MAX_QR_PREVIEW_LENGTH || characterCountTruncated,
            redacted = false,
        )
    }

    private fun redacted(
        contentType: String,
        characterCount: Int,
        characterCountTruncated: Boolean,
    ): PhoneQrRead = PhoneQrRead(
        status = PHONE_QR_STATUS_AVAILABLE,
        contentType = contentType,
        characterCount = characterCount,
        characterCountTruncated = characterCountTruncated,
        preview = null,
        previewTruncated = false,
        redacted = true,
    )

    private fun classify(payload: String): String {
        val lower = payload.lowercase(Locale.US)
        return when {
            lower.startsWith("wifi:") -> "wifi"
            lower.startsWith("otpauth://") -> "sensitive"
            lower.startsWith("http://") || lower.startsWith("https://") -> "url"
            lower.isBlank() -> "unknown"
            else -> "text"
        }
    }

    private fun safeUrlPreview(payload: String): String? {
        val uri = runCatching { URI(payload) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase(Locale.US)
        if (scheme !in setOf("http", "https")) return null
        if (uri.rawUserInfo != null) return null
        val host = uri.host?.takeIf { it.isNotBlank() } ?: return null
        val hasHiddenTail = !uri.rawPath.isNullOrBlank() || uri.rawQuery != null || uri.rawFragment != null
        return "$scheme://$host${if (hasHiddenTail) "/..." else ""}"
    }

    private fun containsUnsafeDisplayCharacter(value: String): Boolean =
        value.any { character ->
            character == '\u0000' || Character.getType(character) == Character.FORMAT.toInt()
        }

    private fun containsSensitiveMarker(value: String): Boolean {
        val lower = value.lowercase(Locale.US)
        return sensitiveMarkers.any { marker -> lower.contains(marker) }
    }

    private val whitespace = Regex("\\s+")
    private val redactedContentTypes = setOf("wifi", "sensitive")
    private val sensitiveMarkers = listOf(
        "password",
        "passwd",
        "secret",
        "token",
        "bearer ",
        "api_key",
        "apikey",
        "private_key",
        "client_secret",
    )
}
