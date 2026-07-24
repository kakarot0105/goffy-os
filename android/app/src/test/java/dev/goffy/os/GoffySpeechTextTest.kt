package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GIT_STATUS_TOOL
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.GitStatusApprovedRepo
import dev.goffy.os.protocol.GitStatusChange
import dev.goffy.os.protocol.GOFFY_ROM_CHECKLIST_TOOL
import dev.goffy.os.protocol.GOFFY_ROM_FEATURES_TOOL
import dev.goffy.os.protocol.GoffyRomChecklist
import dev.goffy.os.protocol.GoffyRomChecklistStep
import dev.goffy.os.protocol.GoffyRomFeature
import dev.goffy.os.protocol.GoffyRomFeatures
import dev.goffy.os.protocol.MAC_APPS_LIST_TOOL
import dev.goffy.os.protocol.MAC_CLIPBOARD_READ_TOOL
import dev.goffy.os.protocol.MAC_FILES_LARGEST_TOOL
import dev.goffy.os.protocol.MAC_FILES_LIST_TOOL
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.MacAppCatalogEntry
import dev.goffy.os.protocol.MacAppsList
import dev.goffy.os.protocol.MacClipboardRead
import dev.goffy.os.protocol.MacFilesApprovedRoot
import dev.goffy.os.protocol.MacFilesLargest
import dev.goffy.os.protocol.MacFilesLargestEntry
import dev.goffy.os.protocol.MacFilesList
import dev.goffy.os.protocol.MacFilesListEntry
import dev.goffy.os.protocol.MacProcessEntry
import dev.goffy.os.protocol.MacProcessesList
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_PROVENANCE_USER_APPROVED
import dev.goffy.os.protocol.PHONE_MEMORY_REMEMBER_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneMemoryRemembered
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.ToolResultContent
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffySpeechTextTest {
    private val endpoint = "wss://mac.example/ws/v1"

    @Test
    fun latestSpeakableTextUsesNewestVerifiedResult() {
        val oldBattery = entry(
            toolName = PHONE_BATTERY_STATUS_TOOL,
            target = ExecutionTarget.PHONE,
            result = PhoneBatteryStatus(levelPercent = 20, charging = false),
        )
        val latestMac = entry(
            toolName = MAC_SYSTEM_INFO_TOOL,
            target = ExecutionTarget.MAC,
            result = MacSystemInfo(
                status = "available",
                operatingSystem = "Darwin",
                architecture = "arm64",
            ),
        )
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(entries = listOf(oldBattery, latestMac)),
        )

        assertEquals(
            "Mac status is available. System: Darwin on arm64.",
            state.latestSpeakableText(),
        )
    }

    @Test
    fun privateNoteTextIsNeverSpoken() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = PHONE_NOTE_CREATE_TOOL,
                        target = ExecutionTarget.PHONE,
                        permission = PermissionLevel.CONFIRM,
                        result = PhoneNoteCreated(
                            noteId = 7,
                            text = "secret launch phrase",
                            createdAtEpochMillis = 1_720_000_000_000,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("Private note 7"))
        assertTrue(speechText.contains("will not read the note text aloud"))
        assertFalse(speechText.contains("secret launch phrase"))
    }

    @Test
    fun localMemoryTextIsNeverSpoken() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = PHONE_MEMORY_REMEMBER_TOOL,
                        target = ExecutionTarget.PHONE,
                        permission = PermissionLevel.CONFIRM,
                        result = PhoneMemoryRemembered(
                            memoryId = 9,
                            text = "secret memory phrase",
                            createdAtEpochMillis = 1_720_000_000_000,
                            provenance = PHONE_MEMORY_PROVENANCE_USER_APPROVED,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("Local memory 9"))
        assertTrue(speechText.contains("will not read the memory text aloud"))
        assertFalse(speechText.contains("secret memory phrase"))
    }

    @Test
    fun macFileNamesAreNotReadAloud() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = MAC_FILES_LIST_TOOL,
                        target = ExecutionTarget.MAC,
                        result = MacFilesList(
                            status = "available",
                            rootIndex = 0,
                            rootName = "goffy",
                            relativePath = "",
                            truncated = false,
                            approvedRoots = listOf(MacFilesApprovedRoot(0, "goffy")),
                            entries = listOf(
                                MacFilesListEntry("private-plan.txt", false, "file", 42, 1L),
                            ),
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("1 entries"))
        assertFalse(speechText.contains("private-plan.txt"))
    }

    @Test
    fun largestMacFilePathsAreNotReadAloud() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = MAC_FILES_LARGEST_TOOL,
                        target = ExecutionTarget.MAC,
                        result = MacFilesLargest(
                            status = "available",
                            rootIndex = 0,
                            rootName = "goffy",
                            relativePath = "",
                            maxDepth = 4,
                            scannedEntries = 2,
                            skippedEntries = 0,
                            truncated = false,
                            approvedRoots = listOf(MacFilesApprovedRoot(0, "goffy")),
                            entries = listOf(
                                MacFilesLargestEntry(
                                    relativePath = "private-plan.txt",
                                    pathTruncated = false,
                                    name = "private-plan.txt",
                                    nameTruncated = false,
                                    sizeBytes = 42,
                                    modifiedEpochSeconds = 1L,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("1 entries"))
        assertFalse(speechText.contains("private-plan.txt"))
    }

    @Test
    fun macProcessNamesAreNotReadAloud() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = "mac.processes.list",
                        target = ExecutionTarget.MAC,
                        result = MacProcessesList(
                            status = "available",
                            processCount = 2,
                            skippedCount = 0,
                            truncated = false,
                            entries = listOf(
                                MacProcessEntry(
                                    pid = 88,
                                    name = "private-agent",
                                    status = "running",
                                    rssBytes = 512_000_000L,
                                    createTimeEpochSeconds = null,
                                ),
                                MacProcessEntry(
                                    pid = 99,
                                    name = "helper",
                                    status = "sleeping",
                                    rssBytes = 128_000_000L,
                                    createTimeEpochSeconds = null,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("2 process summaries"))
        assertTrue(speechText.contains("will not read process names aloud"))
        assertFalse(speechText.contains("private-agent"))
    }

    @Test
    fun macAppCatalogDoesNotImplyLaunchAuthority() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = MAC_APPS_LIST_TOOL,
                        target = ExecutionTarget.MAC,
                        result = MacAppsList(
                            status = "available",
                            appCount = 2,
                            truncated = false,
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
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("2 apps"))
        assertTrue(speechText.contains("will not launch apps without confirmation"))
    }

    @Test
    fun gitStatusPathsAreNotReadAloud() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = GIT_STATUS_TOOL,
                        target = ExecutionTarget.MAC,
                        result = GitStatus(
                            status = "available",
                            repoIndex = 0,
                            repoName = "goffy",
                            branch = "main",
                            headOidShort = "0123456789abcdef",
                            upstream = null,
                            ahead = null,
                            behind = null,
                            clean = false,
                            stagedCount = 1,
                            unstagedCount = 0,
                            untrackedCount = 1,
                            conflictCount = 0,
                            truncated = false,
                            approvedRepos = listOf(GitStatusApprovedRepo(0, "goffy")),
                            changes = listOf(
                                GitStatusChange("private-plan.txt", false, "?", "?", "untracked"),
                            ),
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("2 changes"))
        assertFalse(speechText.contains("private-plan.txt"))
    }

    @Test
    fun macClipboardTextIsNotReadAloud() {
        val secret = "secret launch phrase"
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = MAC_CLIPBOARD_READ_TOOL,
                        target = ExecutionTarget.MAC,
                        result = MacClipboardRead(
                            status = "available",
                            contentType = "text",
                            text = secret,
                            textTruncated = false,
                            characterCount = secret.length,
                            characterCountTruncated = false,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("clipboard returned bounded text"))
        assertTrue(speechText.contains("will not read clipboard contents aloud"))
        assertFalse(speechText.contains(secret))
    }

    @Test
    fun goffyRomChecklistSpeechUsesOnlyBoundedNextStepMetadata() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = GOFFY_ROM_CHECKLIST_TOOL,
                        target = ExecutionTarget.MAC,
                        result = GoffyRomChecklist(
                            status = "available",
                            milestone = "ROM-0",
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
                            ),
                            nextStepsTruncated = true,
                            blockerCount = 1,
                            blockers = listOf("exact stock restore evidence is missing"),
                            blockersTruncated = false,
                            nextStepTitle = "Record exact stock restore evidence",
                            nextStepStatus = "READY",
                            nextAction = "Complete Record exact stock restore evidence",
                            checkedOperatorChecklist = true,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("2 steps remaining"))
        assertTrue(speechText.contains("1 blockers"))
        assertTrue(speechText.contains("Record exact stock restore evidence"))
        assertTrue(speechText.contains("Destructive actions remain withheld"))
        assertFalse(speechText.contains(".goffy-validation"))
    }

    @Test
    fun goffyRomChecklistSpeechHidesCommandLikeNextStep() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = GOFFY_ROM_CHECKLIST_TOOL,
                        target = ExecutionTarget.MAC,
                        result = GoffyRomChecklist(
                            status = "available",
                            milestone = "ROM-0",
                            generatedAt = "2026-07-22T15:00:01Z",
                            checklistStatus = "BLOCKED_EVIDENCE",
                            destructiveActions = "withheld",
                            totalStepCount = 2,
                            doneStepCount = 0,
                            remainingStepCount = 2,
                            nextSteps = emptyList(),
                            nextStepsTruncated = true,
                            blockerCount = 1,
                            blockers = listOf("exact stock restore evidence is missing"),
                            blockersTruncated = false,
                            nextStepTitle = "adb reboot bootloader now",
                            nextStepStatus = "READY",
                            nextAction = "Complete next step",
                            checkedOperatorChecklist = true,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("Next step is hidden"))
        assertFalse(speechText.contains("adb reboot bootloader"))
    }

    @Test
    fun goffyRomChecklistSpeechAllowsSafeAcronymSlashNextStep() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = GOFFY_ROM_CHECKLIST_TOOL,
                        target = ExecutionTarget.MAC,
                        result = GoffyRomChecklist(
                            status = "available",
                            milestone = "ROM-0",
                            generatedAt = "2026-07-22T15:00:01Z",
                            checklistStatus = "BLOCKED_EVIDENCE",
                            destructiveActions = "withheld",
                            totalStepCount = 2,
                            doneStepCount = 0,
                            remainingStepCount = 2,
                            nextSteps = emptyList(),
                            nextStepsTruncated = true,
                            blockerCount = 1,
                            blockers = listOf("DSU/GSI evidence is missing"),
                            blockersTruncated = false,
                            nextStepTitle = "Record DSU/GSI readiness evidence",
                            nextStepStatus = "READY",
                            nextAction = "Complete Record DSU/GSI readiness evidence",
                            checkedOperatorChecklist = true,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("Record DSU/GSI readiness evidence"))
        assertFalse(speechText.contains("Next step is hidden"))
    }

    @Test
    fun goffyRomFeaturesSpeechSummarizesPolicyWithoutPaths() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = GOFFY_ROM_FEATURES_TOOL,
                        target = ExecutionTarget.MAC,
                        result = GoffyRomFeatures(
                            status = "available",
                            payloadName = "GOFFY ROM-0 Jarvis Payload",
                            targetStage = "ROM-0",
                            defaultPerformanceMode = "GOFFY LITE",
                            rom0Flashable = false,
                            privileged = false,
                            platformSigned = false,
                            romDestructiveActionsIncluded = false,
                            appPrivateDestructiveToolsIncluded = false,
                            requiresUserSelectedHome = true,
                            localModelPolicy = "disabled_by_default_observe_only",
                            featureCount = 1,
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
                            ),
                            featuresTruncated = false,
                            mcpToolCount = 1,
                            androidPermissionCount = 0,
                            blockedRomActionCount = 2,
                            blockedRomActions = listOf("unlock_bootloader", "flash_image"),
                            blockedRomActionsTruncated = false,
                            notes = listOf("ROM-0 inserts GOFFY as a safe home payload."),
                            notesTruncated = false,
                            destructiveActions = "withheld",
                            checkedFeaturePayload = true,
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertTrue(speechText.contains("1 features"))
        assertTrue(speechText.contains("GOFFY LITE"))
        assertTrue(speechText.contains("GOFFY Home Surface"))
        assertTrue(speechText.contains("destructive actions are withheld"))
        assertFalse(speechText.contains("android/app/src"))
    }

    @Test
    fun missingOrNonTerminalResultIsNotSpeakable() {
        val withoutResult = entry(
            toolName = PHONE_BATTERY_STATUS_TOOL,
            target = ExecutionTarget.PHONE,
            result = null,
        )
        val activeResult = entry(
            toolName = PHONE_BATTERY_STATUS_TOOL,
            target = ExecutionTarget.PHONE,
            phase = TaskPhase.PREPARING,
            result = PhoneBatteryStatus(levelPercent = 88, charging = true),
        )
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(entries = listOf(withoutResult, activeResult)),
        )

        assertNull(state.latestSpeakableText())
    }

    @Test
    fun speakableTextIsWhitespaceNormalizedAndBounded() {
        val state = GoffyUiState(
            hubEndpoint = endpoint,
            timeline = TaskTimelineState(
                entries = listOf(
                    entry(
                        toolName = MAC_SYSTEM_INFO_TOOL,
                        target = ExecutionTarget.MAC,
                        result = MacSystemInfo(
                            status = "available\nnow",
                            operatingSystem = "Darwin\t${"x".repeat(700)}",
                            architecture = "arm64",
                        ),
                    ),
                ),
            ),
        )

        val speechText = requireNotNull(state.latestSpeakableText())

        assertFalse(speechText.contains("\n"))
        assertFalse(speechText.contains("\t"))
        assertTrue(speechText.length <= 480)
    }

    private fun entry(
        toolName: String,
        target: ExecutionTarget,
        result: ToolResultContent?,
        phase: TaskPhase = TaskPhase.VERIFIED,
        permission: PermissionLevel = PermissionLevel.SAFE,
    ): TaskTimelineEntry = TaskTimelineEntry(
        id = UUID.randomUUID(),
        command = "test command",
        executionTarget = target,
        toolName = toolName,
        phase = phase,
        summary = "test summary",
        events = emptyList(),
        result = result,
        permission = permission,
    )
}
