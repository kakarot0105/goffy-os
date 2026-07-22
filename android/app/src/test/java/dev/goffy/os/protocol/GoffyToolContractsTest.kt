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
    fun memoryMutationContractsRequireExactIdAndSafeText() {
        assertTrue(PhoneMemoryForgetArguments(1).matchesToolContract())
        assertFalse(PhoneMemoryForgetArguments(0).matchesToolContract())

        assertTrue(PhoneMemoryUpdateArguments(1, "favorite project is GOFFY").matchesToolContract())
        assertFalse(PhoneMemoryUpdateArguments(0, "favorite project is GOFFY").matchesToolContract())
        assertFalse(PhoneMemoryUpdateArguments(1, "safe\u202Eevil").matchesToolContract())

        assertTrue(PhoneMemoryDeleted(memoryId = 1, deletedCount = 1, remainingCount = 0).matchesToolContract())
        assertFalse(PhoneMemoryDeleted(memoryId = 0, deletedCount = 1, remainingCount = 0).matchesToolContract())
        assertFalse(PhoneMemoryDeleted(memoryId = 1, deletedCount = 0, remainingCount = 0).matchesToolContract())

        val updated = PhoneMemoryUpdated(
            memoryId = 1,
            text = "favorite project is GOFFY",
            createdAtEpochMillis = 1_720_000_000_000,
            provenance = PHONE_MEMORY_PROVENANCE_USER_APPROVED,
        )
        assertTrue(updated.matchesToolContract())
        assertFalse(updated.copy(text = "first\nsecond").matchesToolContract())
        assertFalse(updated.copy(provenance = "system_inferred").matchesToolContract())
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

    @Test
    fun macProcessesContractRequiresBoundedSortedDisplaySafeMetadata() {
        assertTrue(MacProcessesListArguments().matchesToolContract())
        assertFalse(MacProcessesListArguments(maxEntries = 0).matchesToolContract())
        assertFalse(MacProcessesListArguments(maxEntries = MAX_MAC_PROCESS_ENTRIES + 1).matchesToolContract())

        val valid = validProcesses()

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(skippedCount = 3).matchesToolContract())
        assertFalse(valid.copy(truncated = false).matchesToolContract())
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
                entries = listOf(valid.entries[0].copy(name = "/Users/example/private")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(name = "safe\u202Eevil")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(rssBytes = -1)),
            ).matchesToolContract(),
        )
    }

    @Test
    fun macAppsContractRequiresBoundedApprovedCatalogMetadata() {
        assertTrue(MacAppsListArguments().matchesToolContract())
        assertFalse(MacAppsListArguments(maxEntries = 0).matchesToolContract())
        assertFalse(MacAppsListArguments(maxEntries = MAX_MAC_APP_ENTRIES + 1).matchesToolContract())

        val valid = validApps()

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(truncated = false).matchesToolContract())
        assertFalse(valid.copy(appCount = 1, truncated = true).matchesToolContract())
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(displayName = "/Applications/Safari")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0].copy(bundleId = "com..apple.Safari")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                entries = listOf(valid.entries[0], valid.entries[1].copy(bundleId = "com.apple.Safari")),
            ).matchesToolContract(),
        )
    }

    @Test
    fun macAppOpenContractRequiresSafeNameAndVerifiedRunningState() {
        assertTrue(MacAppsOpenArguments("Safari").matchesToolContract())
        assertFalse(MacAppsOpenArguments("/Applications/Safari").matchesToolContract())
        assertFalse(MacAppsOpenArguments("Safari\u202E").matchesToolContract())

        val valid = MacAppOpened(
            status = "running",
            displayName = "Safari",
            bundleId = "com.apple.Safari",
            verified = true,
        )

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(status = "dispatched").matchesToolContract())
        assertFalse(valid.copy(verified = false).matchesToolContract())
        assertFalse(valid.copy(bundleId = "com..apple.Safari").matchesToolContract())
        assertFalse(valid.copy(displayName = "Bad/Name").matchesToolContract())
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

    private fun validProcesses(): MacProcessesList = MacProcessesList(
        status = "available",
        processCount = 3,
        skippedCount = 0,
        truncated = true,
        entries = listOf(
            MacProcessEntry(
                pid = 88,
                name = "WindowServer",
                status = "running",
                rssBytes = 512_000_000L,
                createTimeEpochSeconds = 1_784_620_000L,
            ),
            MacProcessEntry(
                pid = 99,
                name = "loginwindow",
                status = "sleeping",
                rssBytes = 128_000_000L,
                createTimeEpochSeconds = null,
            ),
        ),
    )

    private fun validApps(): MacAppsList = MacAppsList(
        status = "available",
        appCount = 3,
        truncated = true,
        entries = listOf(
            MacAppCatalogEntry(
                appIndex = 0,
                displayName = "Safari",
                bundleId = "com.apple.Safari",
            ),
            MacAppCatalogEntry(
                appIndex = 1,
                displayName = "Terminal",
                bundleId = "com.apple.Terminal",
            ),
        ),
    )
}
