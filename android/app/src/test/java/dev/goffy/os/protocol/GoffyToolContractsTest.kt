package dev.goffy.os.protocol

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyToolContractsTest {
    @Test
    fun goffyRomStatusContractRequiresBoundedNonAuthorizingMetadata() {
        val valid = validRomStatus()

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(status = "ready").matchesToolContract())
        assertFalse(valid.copy(milestone = "ROM-1").matchesToolContract())
        assertFalse(valid.copy(destructiveActions = "allowed").matchesToolContract())
        assertFalse(valid.copy(destructiveApprovalStatus = "APPROVED").matchesToolContract())
        assertFalse(valid.copy(installDecision = "INSTALL_NOW").matchesToolContract())
        assertFalse(valid.copy(dsuPreflightGateStatus = "/private/dsu").matchesToolContract())
        assertTrue(
            valid.copy(
                blockers = listOf("DSU/GSI readiness evidence is missing"),
                nextAction = "DSU/GSI readiness evidence is missing",
            ).matchesToolContract(),
        )
        assertFalse(valid.copy(romReady = true, blockerCount = 1).matchesToolContract())
        assertFalse(valid.copy(blockerCount = 0, blockers = emptyList()).matchesToolContract())
        assertFalse(
            valid.copy(
                blockers = listOf("/Users/example/private/rom-stock-restore-evidence.json"),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(nextAction = "file:///Users/example/private/rom-stock-restore-evidence.json")
                .matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                summary = "ROM-0 is ready for a manual readiness review",
                refreshStatus = "BLOCKED",
                packetStatus = GOFFY_ROM_READY_STATUS,
                operatorChecklistStatus = GOFFY_ROM_READY_STATUS,
                installDecision = "BLOCKED",
                romReady = true,
                blockerCount = 0,
                blockers = emptyList(),
                nextAction = "Review ROM-0 readiness manually",
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                summary = "ROM-0 is ready for a manual readiness review",
                refreshStatus = GOFFY_ROM_READY_STATUS,
                packetStatus = "BLOCKED_MANUAL_EVIDENCE",
                operatorChecklistStatus = GOFFY_ROM_READY_STATUS,
                romReady = true,
                blockerCount = 0,
                blockers = emptyList(),
                nextAction = "Review ROM-0 readiness manually",
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                summary = "ROM-0 is ready for a manual readiness review",
                refreshStatus = GOFFY_ROM_READY_STATUS,
                packetStatus = GOFFY_ROM_READY_STATUS,
                operatorChecklistStatus = "BLOCKED_EVIDENCE",
                romReady = true,
                blockerCount = 0,
                blockers = emptyList(),
                nextAction = "Review ROM-0 readiness manually",
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                summary = "ROM-0 is ready for a manual readiness review",
                refreshStatus = GOFFY_ROM_READY_STATUS,
                packetStatus = GOFFY_ROM_READY_STATUS,
                operatorChecklistStatus = GOFFY_ROM_READY_STATUS,
                romReady = true,
                blockerCount = 0,
                blockers = emptyList(),
                staleReport = true,
                nextAction = "Review ROM-0 readiness manually",
            ).matchesToolContract(),
        )
        assertFalse(valid.copy(blockerCount = 3, blockersTruncated = false).matchesToolContract())
        assertFalse(valid.copy(blockers = listOf("safe", "bad\u202Eblocker")).matchesToolContract())
        assertFalse(
            valid
                .copy(
                    summary = "ROM-0 is ready for a manual readiness review",
                    refreshStatus = GOFFY_ROM_READY_STATUS,
                    packetStatus = GOFFY_ROM_READY_STATUS,
                    operatorChecklistStatus = GOFFY_ROM_READY_STATUS,
                    installDecision = "READY_FOR_MANUAL_REVIEW",
                    unlockGateStatus = "READY",
                    stockRestoreGateStatus = "READY",
                    gsiCandidateGateStatus = "READY",
                    dsuPreflightGateStatus = "MISSING",
                    fastbootGateStatus = "READY",
                    romReady = true,
                    blockerCount = 0,
                    blockers = emptyList(),
                    nextAction = "Review ROM-0 readiness manually",
                ).matchesToolContract(),
        )
        assertTrue(
            valid
                .copy(
                    summary = "ROM-0 is ready for a manual readiness review",
                    refreshStatus = GOFFY_ROM_READY_STATUS,
                    packetStatus = GOFFY_ROM_READY_STATUS,
                    operatorChecklistStatus = GOFFY_ROM_READY_STATUS,
                    installDecision = "READY_FOR_MANUAL_REVIEW",
                    unlockGateStatus = "READY",
                    stockRestoreGateStatus = "READY",
                    gsiCandidateGateStatus = "READY",
                    dsuPreflightGateStatus = "READY",
                    fastbootGateStatus = "READY",
                    romReady = true,
                    blockerCount = 0,
                    blockers = emptyList(),
                    nextAction = "Review ROM-0 readiness manually",
                ).matchesToolContract(),
        )
    }

    @Test
    fun goffyRomChecklistContractRequiresBoundedNonAuthorizingMetadata() {
        val valid = validRomChecklist()

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(status = "ready").matchesToolContract())
        assertFalse(valid.copy(milestone = "ROM-1").matchesToolContract())
        assertFalse(valid.copy(destructiveActions = "allowed").matchesToolContract())
        assertFalse(valid.copy(totalStepCount = 101).matchesToolContract())
        assertFalse(valid.copy(doneStepCount = 3).matchesToolContract())
        assertFalse(valid.copy(remainingStepCount = 1).matchesToolContract())
        assertFalse(valid.copy(nextStepsTruncated = false, remainingStepCount = 3).matchesToolContract())
        assertFalse(valid.copy(blockerCount = 3, blockersTruncated = false).matchesToolContract())
        assertFalse(valid.copy(nextStepTitle = "/Users/example/stock.zip").matchesToolContract())
        assertFalse(valid.copy(nextStepTitle = "adb reboot bootloader now").matchesToolContract())
        assertFalse(valid.copy(nextAction = "file:///Users/example/stock.zip").matchesToolContract())
        assertFalse(valid.copy(nextAction = "Run fastboot flash boot boot.img next").matchesToolContract())
        assertTrue(
            valid.copy(
                blockers = listOf("stock restore evidence must be recorded before DSU/GSI decisions advance"),
            ).matchesToolContract(),
        )
        assertFalse(valid.copy(checklistStatus = "REBOOT_REQUIRED").matchesToolContract())
        assertFalse(valid.copy(nextStepStatus = "REBOOT_REQUIRED").matchesToolContract())
        assertFalse(valid.copy(status = "missing", checkedOperatorChecklist = true).matchesToolContract())
        assertFalse(valid.copy(status = "available", checkedOperatorChecklist = false).matchesToolContract())
        assertFalse(
            valid.copy(totalStepCount = 0, doneStepCount = 0, remainingStepCount = 0, nextSteps = emptyList())
                .matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                nextSteps = listOf(valid.nextSteps[0].copy(summary = "/private/stock.zip")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                nextSteps = listOf(valid.nextSteps[0].copy(summary = "Use shell to continue")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                nextSteps = listOf(valid.nextSteps[0].copy(kind = "ROOT_SHELL")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                nextSteps = listOf(valid.nextSteps[0].copy(status = "REBOOT_REQUIRED")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                nextSteps = listOf(valid.nextSteps[0].copy(status = "READY", blocked = true, blockerCount = 0)),
            ).matchesToolContract(),
        )
    }

    @Test
    fun goffyRomFeaturesContractRequiresNonPrivilegedNonFlashableMetadata() {
        val valid = validRomFeatures()

        assertTrue(valid.matchesToolContract())
        assertFalse(valid.copy(status = "ready").matchesToolContract())
        assertFalse(valid.copy(targetStage = "ROM-1").matchesToolContract())
        assertFalse(valid.copy(defaultPerformanceMode = "GOFFY ULTRA").matchesToolContract())
        assertFalse(valid.copy(rom0Flashable = true).matchesToolContract())
        assertFalse(valid.copy(privileged = true).matchesToolContract())
        assertFalse(valid.copy(platformSigned = true).matchesToolContract())
        assertFalse(valid.copy(romDestructiveActionsIncluded = true).matchesToolContract())
        assertFalse(valid.copy(appPrivateDestructiveToolsIncluded = true).matchesToolContract())
        assertFalse(valid.copy(requiresUserSelectedHome = false).matchesToolContract())
        assertFalse(valid.copy(localModelPolicy = "always_on").matchesToolContract())
        assertFalse(valid.copy(destructiveActions = "allowed").matchesToolContract())
        assertFalse(valid.copy(featureCount = 0, features = emptyList()).matchesToolContract())
        assertFalse(valid.copy(featuresTruncated = false, featureCount = 3).matchesToolContract())
        assertFalse(
            valid.copy(
                blockedRomActions = listOf("unlock-bootloader"),
            ).matchesToolContract(),
        )
        assertFalse(valid.copy(notes = listOf("/Users/example/private")).matchesToolContract())
        assertFalse(
            valid.copy(
                features = listOf(valid.features[0].copy(title = "Run fastboot flash boot boot.img")),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                features = listOf(valid.features[0].copy(backgroundAccess = true)),
            ).matchesToolContract(),
        )
        assertFalse(
            valid.copy(
                features = listOf(valid.features[0].copy(mcpTools = listOf("phone/battery"))),
            ).matchesToolContract(),
        )
    }

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

    private fun validRomStatus(): GoffyRomStatus = GoffyRomStatus(
        status = "available",
        milestone = GOFFY_ROM_MILESTONE,
        summary = "ROM-0 is BLOCKED; 1 blocker remains",
        generatedAt = "2026-07-22T15:00:00Z",
        refreshSchemaVersion = "goffy.rom0-refresh-report.v4",
        refreshStatus = "BLOCKED",
        packetStatus = "BLOCKED_MANUAL_EVIDENCE",
        bootloaderVisibilityStatus = "READY_FOR_MANUAL_BOOTLOADER_CHECK",
        operatorChecklistStatus = "BLOCKED_EVIDENCE",
        installDecision = "BLOCKED",
        unlockGateStatus = "MISSING",
        stockRestoreGateStatus = "MISSING",
        gsiCandidateGateStatus = "MISSING",
        dsuPreflightGateStatus = "MISSING",
        fastbootGateStatus = "MISSING",
        destructiveApprovalStatus = "WITHHELD",
        romReady = false,
        destructiveActions = "withheld",
        blockerCount = 1,
        blockers = listOf("exact stock restore evidence is missing"),
        blockersTruncated = false,
        nextAction = "exact stock restore evidence is missing",
        staleReport = false,
        checkedRefreshReport = true,
        checkedOperatorChecklist = true,
    )

    private fun validRomChecklist(): GoffyRomChecklist = GoffyRomChecklist(
        status = "available",
        milestone = GOFFY_ROM_MILESTONE,
        generatedAt = "2026-07-22T15:00:01Z",
        checklistStatus = "BLOCKED_EVIDENCE",
        destructiveActions = "withheld",
        totalStepCount = 3,
        doneStepCount = 1,
        remainingStepCount = 2,
        nextSteps = listOf(
            GoffyRomChecklistStep(
                stepIndex = 2,
                title = "Record exact stock restore evidence",
                kind = "HUMAN_ONLY",
                status = "READY",
                summary = "Record the official Motorola restore archive name and checksum.",
                blocked = false,
                blockerCount = 0,
            ),
            GoffyRomChecklistStep(
                stepIndex = 3,
                title = "Record read-only DSU preflight",
                kind = "LOCAL_READ_ONLY",
                status = "BLOCKED",
                summary = "Check DSU prerequisites from local evidence only.",
                blocked = true,
                blockerCount = 1,
            ),
        ),
        nextStepsTruncated = false,
        blockerCount = 1,
        blockers = listOf("exact stock restore evidence is missing"),
        blockersTruncated = false,
        nextStepTitle = "Record exact stock restore evidence",
        nextStepStatus = "READY",
        nextAction = "Complete Record exact stock restore evidence",
        checkedOperatorChecklist = true,
    )

    private fun validRomFeatures(): GoffyRomFeatures = GoffyRomFeatures(
        status = "available",
        payloadName = "GOFFY ROM-0 Jarvis Payload",
        targetStage = GOFFY_ROM_MILESTONE,
        defaultPerformanceMode = "GOFFY LITE",
        rom0Flashable = false,
        privileged = false,
        platformSigned = false,
        romDestructiveActionsIncluded = false,
        appPrivateDestructiveToolsIncluded = false,
        requiresUserSelectedHome = true,
        localModelPolicy = GOFFY_ROM_LOCAL_MODEL_POLICY,
        featureCount = 2,
        features = listOf(
            GoffyRomFeature(
                featureIndex = 1,
                title = "GOFFY Home Surface",
                executionTargets = listOf("PHONE"),
                mcpTools = listOf("phone.device.info"),
                mcpToolCount = 1,
                androidPermissionCount = 0,
                runtimePolicy = "user selected home with no privileged authority",
                foregroundOnly = true,
                backgroundAccess = false,
                privilegedRequired = false,
                romDestructiveAction = false,
                appPrivateDestructiveToolCount = 0,
            ),
            GoffyRomFeature(
                featureIndex = 2,
                title = "GOFFY ROM Status",
                executionTargets = listOf("MAC"),
                mcpTools = listOf("goffy.rom.status", "goffy.rom.features"),
                mcpToolCount = 2,
                androidPermissionCount = 0,
                runtimePolicy = "read only fixed validation artifacts",
                foregroundOnly = true,
                backgroundAccess = false,
                privilegedRequired = false,
                romDestructiveAction = false,
                appPrivateDestructiveToolCount = 0,
            ),
        ),
        featuresTruncated = false,
        mcpToolCount = 3,
        androidPermissionCount = 0,
        blockedRomActionCount = 2,
        blockedRomActions = listOf("unlock_bootloader", "flash_image"),
        blockedRomActionsTruncated = false,
        notes = listOf("ROM-0 inserts GOFFY as a safe home payload."),
        notesTruncated = false,
        destructiveActions = "withheld",
        checkedFeaturePayload = true,
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
