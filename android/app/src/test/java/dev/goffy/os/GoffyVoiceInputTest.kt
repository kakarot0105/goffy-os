package dev.goffy.os

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyVoiceInputTest {
    @Test
    fun recognizedCommandIsWhitespaceNormalizedAndBounded() {
        val command = "  Show\n\tmy\r Mac   status  ${"x".repeat(2_500)}"
            .toSafeRecognizedCommand()

        assertTrue(requireNotNull(command).startsWith("Show my Mac status"))
        assertEquals(2_000, command.length)
        assertTrue(command.none { it.code < 0x20 || it.code == 0x7F })
    }

    @Test
    fun blankRecognizedCommandIsRejected() {
        assertNull(" \n\t ".toSafeRecognizedCommand())
    }
}
