package dev.goffy.os.ocr

import dev.goffy.os.protocol.MAX_OCR_CHARACTER_COUNT
import dev.goffy.os.protocol.MAX_OCR_PREVIEW_LENGTH
import dev.goffy.os.protocol.matchesToolContract
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OcrTextSummarizerTest {
    @Test
    fun visibleTextProducesBoundedPreview() {
        val result = OcrTextSummarizer.summarize("GOFFY OS\nObserve Plan Act")

        assertTrue(result.matchesToolContract())
        assertEquals("latin", result.script)
        assertEquals(2, result.lineCount)
        assertEquals("GOFFY OS Observe Plan Act", result.preview)
        assertTrue(!result.redacted)
    }

    @Test
    fun sensitiveTextIsRedactedFromPreview() {
        val result = OcrTextSummarizer.summarize("Password: secret launch code")

        assertTrue(result.matchesToolContract())
        assertTrue(result.redacted)
        assertNull(result.preview)
    }

    @Test
    fun paymentCardLikeTextIsRedactedFromPreview() {
        val result = OcrTextSummarizer.summarize("4111 1111 1111 1111")

        assertTrue(result.matchesToolContract())
        assertTrue(result.redacted)
        assertNull(result.preview)
    }

    @Test
    fun oversizedTextKeepsOnlyBoundedCountsAndPreview() {
        val result = OcrTextSummarizer.summarize("a".repeat(MAX_OCR_CHARACTER_COUNT + 5))

        assertTrue(result.matchesToolContract())
        assertEquals(MAX_OCR_CHARACTER_COUNT, result.characterCount)
        assertEquals(MAX_OCR_PREVIEW_LENGTH, result.preview?.length)
        assertTrue(result.characterCountTruncated)
        assertTrue(result.previewTruncated)
    }
}
