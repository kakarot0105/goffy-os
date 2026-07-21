package dev.goffy.os.qr

import dev.goffy.os.protocol.MAX_QR_PAYLOAD_CHARACTER_COUNT
import dev.goffy.os.protocol.MAX_QR_PREVIEW_LENGTH
import dev.goffy.os.protocol.matchesToolContract
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QrPayloadSummarizerTest {
    @Test
    fun textQrPayloadProducesBoundedPreviewWithoutRawImageState() {
        val result = QrPayloadSummarizer.summarize("  hello from GOFFY  ")

        assertTrue(result.matchesToolContract())
        assertEquals("text", result.contentType)
        assertEquals("hello from GOFFY", result.preview)
        assertFalse(result.redacted)
        assertFalse(result.previewTruncated)
    }

    @Test
    fun urlQrPayloadHidesPathQueryAndFragmentFromPreview() {
        val result = QrPayloadSummarizer.summarize(
            "https://example.com/private/path?token=abc#frag",
        )

        assertTrue(result.matchesToolContract())
        assertEquals("url", result.contentType)
        assertEquals("https://example.com/...", result.preview)
        assertFalse(result.preview?.contains("token") ?: true)
    }

    @Test
    fun sensitiveQrPayloadsAreRedactedFromPreview() {
        val wifi = QrPayloadSummarizer.summarize("WIFI:T:WPA;S:Home;P:secret-password;;")
        val otp = QrPayloadSummarizer.summarize("otpauth://totp/acct?secret=ABC")

        assertTrue(wifi.matchesToolContract())
        assertTrue(otp.matchesToolContract())
        assertEquals("wifi", wifi.contentType)
        assertEquals("sensitive", otp.contentType)
        assertTrue(wifi.redacted)
        assertTrue(otp.redacted)
        assertNull(wifi.preview)
        assertNull(otp.preview)
    }

    @Test
    fun oversizedPayloadKeepsOnlyBoundedCountsAndPreview() {
        val result = QrPayloadSummarizer.summarize("a".repeat(MAX_QR_PAYLOAD_CHARACTER_COUNT + 5))

        assertTrue(result.matchesToolContract())
        assertEquals(MAX_QR_PAYLOAD_CHARACTER_COUNT, result.characterCount)
        assertTrue(result.characterCountTruncated)
        assertEquals(MAX_QR_PREVIEW_LENGTH, result.preview?.length)
        assertTrue(result.previewTruncated)
    }
}
