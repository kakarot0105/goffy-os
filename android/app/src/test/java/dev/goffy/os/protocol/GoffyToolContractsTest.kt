package dev.goffy.os.protocol

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyToolContractsTest {
    @Test
    fun batteryContractAcceptsOnlyPercentages() {
        assertTrue(PhoneBatteryStatus(0, false).matchesToolContract())
        assertTrue(PhoneBatteryStatus(100, true).matchesToolContract())
        assertFalse(PhoneBatteryStatus(-1, false).matchesToolContract())
        assertFalse(PhoneBatteryStatus(101, false).matchesToolContract())
    }

    @Test
    fun deviceInfoContractRejectsMissingOversizedOrSpoofableFields() {
        assertTrue(validDeviceInfo().matchesToolContract())
        assertTrue(
            validDeviceInfo()
                .copy(goffySystemApp = true, goffyHomeCandidate = true, goffyDefaultHome = true)
                .matchesToolContract(),
        )
        assertFalse(validDeviceInfo().copy(manufacturer = "").matchesToolContract())
        assertFalse(validDeviceInfo().copy(model = "x".repeat(129)).matchesToolContract())
        assertFalse(validDeviceInfo().copy(model = "moto\u202Eg").matchesToolContract())
        assertFalse(validDeviceInfo().copy(androidRelease = "15\n").matchesToolContract())
        assertFalse(validDeviceInfo().copy(sdkInt = 25).matchesToolContract())
        assertFalse(validDeviceInfo().copy(sdkInt = Int.MAX_VALUE).matchesToolContract())
        assertFalse(
            validDeviceInfo()
                .copy(goffyHomeCandidate = false, goffyDefaultHome = true)
                .matchesToolContract(),
        )
    }

    @Test
    fun noteContractRequiresBoundedDisplaySafeTextAndPositiveMetadata() {
        val valid = PhoneNoteCreated(1, "Buy milk", 1_720_000_000_000)

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(noteId = 0).matchesToolContract())
        assertFalse(valid.copy(text = " ").matchesToolContract())
        assertFalse(valid.copy(text = "x".repeat(MAX_NOTE_TEXT_LENGTH + 1)).matchesToolContract())
        assertFalse(valid.copy(text = "safe\u202Eevil").matchesToolContract())
        assertFalse(valid.copy(text = "first\nsecond").matchesToolContract())
        assertFalse(valid.copy(createdAtEpochMillis = 0).matchesToolContract())
    }

    @Test
    fun timerContractRequiresAndroidBoundsActionAndSafeClockPackage() {
        val valid = PhoneTimerDispatched(
            300,
            "com.google.android.deskclock",
            "com.google.android.deskclock.TimerActivity",
            true,
            true,
            ANDROID_SET_TIMER_ACTION,
        )

        assertTrue(PhoneTimerCreateArguments(1, true).matchesToolContract())
        assertTrue(PhoneTimerCreateArguments(MAX_TIMER_SECONDS, true).matchesToolContract())
        assertFalse(PhoneTimerCreateArguments(0, true).matchesToolContract())
        assertFalse(PhoneTimerCreateArguments(MAX_TIMER_SECONDS + 1, true).matchesToolContract())
        assertFalse(PhoneTimerCreateArguments(300, false).matchesToolContract())
        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(durationSeconds = 0).matchesToolContract())
        assertFalse(valid.copy(clockPackage = "android").matchesToolContract())
        assertFalse(valid.copy(clockPackage = "com.clock\nspoof").matchesToolContract())
        assertFalse(valid.copy(clockActivity = "com.example.clock.TimerActivity").matchesToolContract())
        assertFalse(valid.copy(systemApplication = false).matchesToolContract())
        assertFalse(valid.copy(skipClockUiRequested = false).matchesToolContract())
        assertFalse(valid.copy(systemAction = "android.intent.action.SET_ALARM").matchesToolContract())
    }

    @Test
    fun largestMacFilesContractRequiresBoundedRelativeMetadata() {
        assertTrue(MacFilesLargestArguments(rootIndex = 0).matchesToolContract())
        assertFalse(MacFilesLargestArguments(rootIndex = 8).matchesToolContract())
        assertFalse(MacFilesLargestArguments(maxEntries = 0).matchesToolContract())
        assertFalse(MacFilesLargestArguments(maxDepth = MAX_MAC_FILES_LARGEST_DEPTH + 1).matchesToolContract())

        val valid = validLargestFiles()

        assertTrue(valid.matchesToolContract())
        assertFalse(
            valid.copy(
                entries = listOf(
                    valid.entries[1],
                    valid.entries[0],
                ),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(relativePath = "/Users/private.bin")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(relativePath = "../private.bin")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(sizeBytes = -1)),
            ).matchesToolContract(),
        )
        assertFalse(valid.copy(scannedEntries = MAX_MAC_FILES_LARGEST_SCANNED_ENTRIES + 1).matchesToolContract())
    }

    private fun validDeviceInfo(): PhoneDeviceInfo = PhoneDeviceInfo(
        manufacturer = "motorola",
        model = "moto g",
        androidRelease = "15",
        sdkInt = 35,
    )

    private fun validLargestFiles(): MacFilesLargest = MacFilesLargest(
        status = "available",
        rootIndex = 0,
        rootName = "goffy",
        relativePath = "",
        maxDepth = DEFAULT_MAC_FILES_LARGEST_DEPTH,
        scannedEntries = 3,
        skippedEntries = 0,
        truncated = false,
        approvedRoots = listOf(MacFilesApprovedRoot(0, "goffy")),
        entries = listOf(
            MacFilesLargestEntry(
                relativePath = "build/output.apk",
                pathTruncated = false,
                name = "output.apk",
                nameTruncated = false,
                sizeBytes = 12_345L,
                modifiedEpochSeconds = 1L,
            ),
            MacFilesLargestEntry(
                relativePath = "README.md",
                pathTruncated = false,
                name = "README.md",
                nameTruncated = false,
                sizeBytes = 1_024L,
                modifiedEpochSeconds = 2L,
            ),
        ),
    )
}
