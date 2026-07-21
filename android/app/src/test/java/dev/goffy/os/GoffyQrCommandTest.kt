package dev.goffy.os

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyQrCommandTest {
    @Test
    fun foregroundQrReadCommandsAreRecognized() {
        assertTrue(isForegroundQrReadCommand("read this QR code"))
        assertTrue(isForegroundQrReadCommand("Scan the qr"))
        assertTrue(isForegroundQrReadCommand("scan a QR code!"))
    }

    @Test
    fun unrelatedCommandsAreNotQrReadCommands() {
        assertFalse(isForegroundQrReadCommand("show my Mac status"))
        assertFalse(isForegroundQrReadCommand("read my Mac clipboard"))
        assertFalse(isForegroundQrReadCommand("scan files on my Mac"))
    }
}
