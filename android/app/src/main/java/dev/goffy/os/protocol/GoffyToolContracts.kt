package dev.goffy.os.protocol

import java.util.Locale

fun GoffyRomStatus.matchesToolContract(): Boolean =
    status in GOFFY_ROM_STATUS_VALUES &&
        milestone == GOFFY_ROM_MILESTONE &&
        summary.isSafeRomStatusField(MAX_GOFFY_ROM_SUMMARY_LENGTH) &&
        generatedAt.isSafeRomStatusField(MAX_GOFFY_ROM_TIMESTAMP_LENGTH) &&
        refreshSchemaVersion.isSafeRomStatusField(MAX_GOFFY_ROM_SCHEMA_LENGTH) &&
        refreshStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        packetStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        bootloaderVisibilityStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        operatorChecklistStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        installDecision in GOFFY_ROM_INSTALL_DECISION_VALUES &&
        unlockGateStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        stockRestoreGateStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        gsiCandidateGateStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        dsuPreflightGateStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        fastbootGateStatus.isSafeRomStatusField(MAX_GOFFY_ROM_STATUS_LENGTH) &&
        destructiveApprovalStatus == "WITHHELD" &&
        destructiveActions == "withheld" &&
        blockerCount in 0..MAX_GOFFY_ROM_BLOCKER_COUNT &&
        blockers.size <= MAX_GOFFY_ROM_BLOCKERS &&
        blockers.size <= blockerCount &&
        (if (blockersTruncated) blockers.size < blockerCount else blockers.size == blockerCount) &&
        blockers.all { it.isSafeRomStatusField(MAX_GOFFY_ROM_BLOCKER_LENGTH) } &&
        nextAction.isSafeRomStatusField(MAX_GOFFY_ROM_NEXT_ACTION_LENGTH) &&
        (!romReady || status == "available") &&
        (!romReady || blockerCount == 0) &&
        (!romReady || !staleReport) &&
        (!romReady || checkedRefreshReport) &&
        (!romReady || checkedOperatorChecklist) &&
        (!romReady || refreshStatus == GOFFY_ROM_READY_STATUS) &&
        (!romReady || packetStatus == GOFFY_ROM_READY_STATUS) &&
        (!romReady || operatorChecklistStatus == GOFFY_ROM_READY_STATUS) &&
        (!romReady || installDecision == "READY_FOR_MANUAL_REVIEW") &&
        (!romReady || unlockGateStatus == "READY") &&
        (!romReady || stockRestoreGateStatus == "READY") &&
        (!romReady || gsiCandidateGateStatus == "READY") &&
        (!romReady || dsuPreflightGateStatus == "READY") &&
        (!romReady || fastbootGateStatus == "READY") &&
        (romReady || installDecision == "BLOCKED") &&
        (romReady || blockerCount > 0)

fun GoffyRomChecklist.matchesToolContract(): Boolean =
        status in GOFFY_ROM_STATUS_VALUES &&
        milestone == GOFFY_ROM_MILESTONE &&
        generatedAt.isSafeRomStatusField(MAX_GOFFY_ROM_TIMESTAMP_LENGTH) &&
        checklistStatus in GOFFY_ROM_CHECKLIST_STATUS_VALUES &&
        destructiveActions == "withheld" &&
        totalStepCount in 0..MAX_GOFFY_ROM_CHECKLIST_STEP_COUNT &&
        doneStepCount in 0..totalStepCount &&
        remainingStepCount == totalStepCount - doneStepCount &&
        nextSteps.size <= MAX_GOFFY_ROM_CHECKLIST_STEPS &&
        nextSteps.size <= remainingStepCount &&
        (if (nextStepsTruncated) nextSteps.size < remainingStepCount else nextSteps.size == remainingStepCount) &&
        nextSteps.all(GoffyRomChecklistStep::matchesToolContract) &&
        nextSteps.map { it.stepIndex }.toSet().size == nextSteps.size &&
        blockerCount in 0..MAX_GOFFY_ROM_BLOCKER_COUNT &&
        blockers.size <= MAX_GOFFY_ROM_BLOCKERS &&
        blockers.size <= blockerCount &&
        (if (blockersTruncated) blockers.size < blockerCount else blockers.size == blockerCount) &&
        blockers.all { it.isSafeRomStatusField(MAX_GOFFY_ROM_BLOCKER_LENGTH) } &&
        nextStepTitle.isSafeRomStatusField(MAX_GOFFY_ROM_CHECKLIST_TITLE_LENGTH) &&
        nextStepStatus in GOFFY_ROM_CHECKLIST_NEXT_STEP_STATUS_VALUES &&
        nextAction.isSafeRomStatusField(MAX_GOFFY_ROM_NEXT_ACTION_LENGTH) &&
        (status != "available" || checkedOperatorChecklist) &&
        (status == "available" || !checkedOperatorChecklist) &&
        (status != "available" || totalStepCount > 0) &&
        (status != "available" || checklistStatus in GOFFY_ROM_CHECKLIST_AVAILABLE_STATUS_VALUES) &&
        (status == "available" || checklistStatus !in GOFFY_ROM_CHECKLIST_AVAILABLE_STATUS_VALUES)

fun GoffyRomChecklistStep.matchesToolContract(): Boolean =
    stepIndex in 1..MAX_GOFFY_ROM_CHECKLIST_STEP_COUNT &&
        title.isSafeRomStatusField(MAX_GOFFY_ROM_CHECKLIST_TITLE_LENGTH) &&
        kind in GOFFY_ROM_CHECKLIST_STEP_KIND_VALUES &&
        status in GOFFY_ROM_CHECKLIST_STEP_STATUS_VALUES &&
        summary.isSafeRomStatusField(MAX_GOFFY_ROM_CHECKLIST_SUMMARY_LENGTH) &&
        blockerCount in 0..MAX_GOFFY_ROM_CHECKLIST_STEP_COUNT &&
        blocked == (status == "BLOCKED" || blockerCount > 0)

fun PhoneBatteryStatus.matchesToolContract(): Boolean =
    levelPercent in MIN_BATTERY_PERCENT..MAX_BATTERY_PERCENT

fun PhoneDeviceInfo.matchesToolContract(): Boolean =
    manufacturer.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        model.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        androidRelease.isSafeDisplayField(MAX_ANDROID_RELEASE_LENGTH) &&
        sdkInt in MIN_SUPPORTED_SDK..MAX_REASONABLE_SDK &&
        (!goffyDefaultHome || goffyHomeCandidate)

fun PhoneQrRead.matchesToolContract(): Boolean =
    status == PHONE_QR_STATUS_AVAILABLE &&
        contentType in PHONE_QR_CONTENT_TYPES &&
        characterCount in 1..MAX_QR_PAYLOAD_CHARACTER_COUNT &&
        if (redacted) {
            preview == null && !previewTruncated
        } else {
            preview != null &&
                preview.isSafeQrPreview() &&
                if (contentType == "url" || previewTruncated || characterCountTruncated) {
                    characterCount >= preview.length
                } else {
                    characterCount == preview.length
                }
        }

fun PhoneOcrRead.matchesToolContract(): Boolean =
    status == PHONE_OCR_STATUS_AVAILABLE &&
        script in PHONE_OCR_SCRIPTS &&
        characterCount in 1..MAX_OCR_CHARACTER_COUNT &&
        lineCount in 1..MAX_OCR_LINE_COUNT &&
        if (redacted) {
            preview == null && !previewTruncated
        } else {
            preview != null &&
                preview.isSafeOcrPreview() &&
                characterCount >= preview.length
        }

fun MacFilesListArguments.matchesToolContract(): Boolean =
    rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
        relativePath.isSafeMacFilesRelativePath() &&
        maxEntries in 1..MAX_MAC_FILES_LIST_ENTRIES

fun MacFilesLargestArguments.matchesToolContract(): Boolean =
    rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
        relativePath.isSafeMacFilesRelativePath() &&
        maxEntries in 1..MAX_MAC_FILES_LARGEST_ENTRIES &&
        maxDepth in 0..MAX_MAC_FILES_LARGEST_DEPTH

fun MacProcessesListArguments.matchesToolContract(): Boolean =
    maxEntries in 1..MAX_MAC_PROCESS_ENTRIES

fun MacAppsListArguments.matchesToolContract(): Boolean =
    maxEntries in 1..MAX_MAC_APP_ENTRIES

fun MacAppsOpenArguments.matchesToolContract(): Boolean =
    displayName.isSafeMacAppDisplayName()

fun MacAppsList.matchesToolContract(): Boolean =
    status.isSafeDisplayField(MAX_MAC_APP_STATUS_LENGTH) &&
        appCount in 0..MAX_MAC_APP_COUNT &&
        entries.size <= MAX_MAC_APP_ENTRIES &&
        entries.size <= appCount &&
        (if (truncated) entries.size < appCount else entries.size == appCount) &&
        entries.all(MacAppCatalogEntry::matchesToolContract) &&
        entries.map { it.appIndex }.toSet().size == entries.size &&
        entries.map { it.displayName.lowercase(Locale.US) }.toSet().size == entries.size &&
        entries.map { it.bundleId.lowercase(Locale.US) }.toSet().size == entries.size

fun MacAppCatalogEntry.matchesToolContract(): Boolean =
    appIndex in 0..MAX_MAC_APP_INDEX &&
        displayName.isSafeMacAppDisplayName() &&
        bundleId.isSafeMacBundleId()

fun MacAppOpened.matchesToolContract(): Boolean =
    status == "running" &&
        displayName.isSafeMacAppDisplayName() &&
        bundleId.isSafeMacBundleId() &&
        verified

fun MacProcessesList.matchesToolContract(): Boolean =
    status.isSafeDisplayField(MAX_MAC_PROCESS_STATUS_TEXT_LENGTH) &&
        processCount in 0..MAX_MAC_PROCESS_COUNT &&
        skippedCount in 0..MAX_MAC_PROCESS_COUNT &&
        skippedCount <= processCount &&
        entries.size <= MAX_MAC_PROCESS_ENTRIES &&
        entries.size <= processCount &&
        (if (truncated) {
            entries.size <= processCount - skippedCount
        } else {
            entries.size == processCount - skippedCount
        }) &&
        entries.all(MacProcessEntry::matchesToolContract) &&
        entries.zipWithNext().all { (first, second) -> first.rssBytes >= second.rssBytes }

fun MacProcessEntry.matchesToolContract(): Boolean =
    pid in 0..MAX_MAC_PROCESS_PID &&
        name.isSafeDisplayField(MAX_MAC_PROCESS_NAME_LENGTH) &&
        !name.contains("/") &&
        !name.contains("\\") &&
        status.isSafeDisplayField(MAX_MAC_PROCESS_STATUS_LENGTH) &&
        rssBytes in 0..MAX_MAC_PROCESS_RSS_BYTES &&
        (createTimeEpochSeconds == null || createTimeEpochSeconds >= 0L)

fun MacFilesLargest.matchesToolContract(): Boolean =
    status.isSafeDisplayField(64) &&
        rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
        rootName.isSafeDisplayField(MAX_MAC_FILES_ROOT_NAME_LENGTH) &&
        relativePath.isSafeMacFilesRelativePath() &&
        maxDepth in 0..MAX_MAC_FILES_LARGEST_DEPTH &&
        scannedEntries in 0..MAX_MAC_FILES_LARGEST_SCANNED_ENTRIES &&
        skippedEntries in 0..MAX_MAC_FILES_LARGEST_SCANNED_ENTRIES &&
        approvedRoots.size <= MAX_MAC_FILES_APPROVED_ROOTS &&
        approvedRoots.any { root -> root.rootIndex == rootIndex && root.name == rootName } &&
        approvedRoots.all { root ->
            root.rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
                root.name.isSafeDisplayField(MAX_MAC_FILES_ROOT_NAME_LENGTH)
        } &&
        entries.size <= MAX_MAC_FILES_LARGEST_ENTRIES &&
        entries.all(MacFilesLargestEntry::matchesToolContract) &&
        entries.zipWithNext().all { (first, second) -> first.sizeBytes >= second.sizeBytes }

fun MacFilesLargestEntry.matchesToolContract(): Boolean =
    relativePath.isSafeMacFilesOutputPath(MAX_MAC_FILES_LARGEST_PATH_LENGTH) &&
        name.isSafeDisplayField(MAX_MAC_FILES_ENTRY_NAME_LENGTH) &&
        sizeBytes in 0..MAX_MAC_FILES_LARGEST_FILE_SIZE_BYTES &&
        (modifiedEpochSeconds == null || modifiedEpochSeconds >= 0L)

fun MacFilesList.matchesToolContract(): Boolean =
    status.isSafeDisplayField(64) &&
        rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
        rootName.isSafeDisplayField(MAX_MAC_FILES_ROOT_NAME_LENGTH) &&
        relativePath.length <= MAX_MAC_FILES_RELATIVE_PATH_LENGTH &&
        relativePath.isSafeMacFilesRelativePath() &&
        approvedRoots.size <= MAX_MAC_FILES_APPROVED_ROOTS &&
        approvedRoots.all { root ->
            root.rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
                root.name.isSafeDisplayField(MAX_MAC_FILES_ROOT_NAME_LENGTH)
        } &&
        entries.size <= MAX_MAC_FILES_LIST_ENTRIES &&
        entries.all(MacFilesListEntry::matchesToolContract)

fun MacFilesListEntry.matchesToolContract(): Boolean =
    name.isSafeDisplayField(MAX_MAC_FILES_ENTRY_NAME_LENGTH) &&
        kind in MAC_FILES_ENTRY_KINDS &&
        (sizeBytes == null || sizeBytes >= 0) &&
        (modifiedEpochSeconds == null || modifiedEpochSeconds >= 0L)

fun GitStatusArguments.matchesToolContract(): Boolean =
    repoIndex in 0..MAX_GIT_STATUS_REPO_INDEX &&
        maxChanges in 1..MAX_GIT_STATUS_CHANGES

fun GitStatus.matchesToolContract(): Boolean =
    status.isSafeDisplayField(MAX_GIT_STATUS_STATUS_LENGTH) &&
        repoIndex in 0..MAX_GIT_STATUS_REPO_INDEX &&
        repoName.isSafeDisplayField(MAX_GIT_STATUS_REPO_NAME_LENGTH) &&
        branch.isNullOrSafeDisplayField(MAX_GIT_STATUS_BRANCH_LENGTH) &&
        headOidShort.isNullOrSafeDisplayField(MAX_GIT_STATUS_OID_LENGTH) &&
        upstream.isNullOrSafeDisplayField(MAX_GIT_STATUS_UPSTREAM_LENGTH) &&
        (ahead == null || ahead in 0..MAX_GIT_STATUS_COUNT) &&
        (behind == null || behind in 0..MAX_GIT_STATUS_COUNT) &&
        stagedCount in 0..MAX_GIT_STATUS_COUNT &&
        unstagedCount in 0..MAX_GIT_STATUS_COUNT &&
        untrackedCount in 0..MAX_GIT_STATUS_COUNT &&
        conflictCount in 0..MAX_GIT_STATUS_COUNT &&
        gitStatusCountsMatchState() &&
        approvedRepos.size <= MAX_GIT_STATUS_REPOS &&
        approvedRepos.any { repo -> repo.repoIndex == repoIndex && repo.name == repoName } &&
        approvedRepos.all { repo ->
            repo.repoIndex in 0..MAX_GIT_STATUS_REPO_INDEX &&
                repo.name.isSafeDisplayField(MAX_GIT_STATUS_REPO_NAME_LENGTH)
        } &&
        changes.size <= MAX_GIT_STATUS_CHANGES &&
        changes.all(GitStatusChange::matchesToolContract)

private fun GitStatus.gitStatusCountsMatchState(): Boolean {
    val totalCount = stagedCount + unstagedCount + untrackedCount + conflictCount
    val minimumShownCount = changes.size
    val nonCleanStateMatchesCounts = !clean || (totalCount == 0 && changes.isEmpty() && !truncated)
    val shownChangesMatchCounts = if (truncated) {
        minimumShownCount <= totalCount
    } else {
        minimumShownCount == totalCount
    }
    return nonCleanStateMatchesCounts && shownChangesMatchCounts
}

fun GitStatusChange.matchesToolContract(): Boolean =
    path.isSafeGitStatusPath() &&
        indexStatus in GIT_STATUS_CODE_VALUES &&
        workingTreeStatus in GIT_STATUS_CODE_VALUES &&
        kind in GIT_STATUS_CHANGE_KINDS

fun MacClipboardRead.matchesToolContract(): Boolean =
    status in MAC_CLIPBOARD_STATUS_VALUES &&
        contentType == "text" &&
        characterCount in 0..MAX_MAC_CLIPBOARD_CHARACTER_COUNT &&
        textMatchesClipboardState() &&
        text.doesNotContainFileUrl()

private fun MacClipboardRead.textMatchesClipboardState(): Boolean = when (status) {
    "available" ->
        text != null &&
            text.isSafeClipboardText() &&
            if (textTruncated || characterCountTruncated) {
                textTruncated && characterCount >= text.length
            } else {
                characterCount == text.length
            }
    "empty", "unsupported" ->
        text == null &&
            !textTruncated &&
            characterCount == 0 &&
            !characterCountTruncated
    else -> false
}

fun PhoneNoteCreated.matchesToolContract(): Boolean =
    noteId > 0 &&
        text.matchesNoteTextContract() &&
        createdAtEpochMillis > 0

fun PhoneMemoryRememberArguments.matchesToolContract(): Boolean =
    text.matchesMemoryTextContract()

fun PhoneMemoryForgetArguments.matchesToolContract(): Boolean =
    memoryId > 0

fun PhoneMemoryUpdateArguments.matchesToolContract(): Boolean =
    memoryId > 0 && text.matchesMemoryTextContract()

fun PhoneMemoryRemembered.matchesToolContract(): Boolean =
    memoryId > 0 &&
        text.matchesMemoryTextContract() &&
        createdAtEpochMillis > 0 &&
        provenance.matchesMemoryProvenanceContract()

fun PhoneMemoryEntry.matchesToolContract(): Boolean =
    memoryId > 0 &&
        text.matchesMemoryTextContract() &&
        createdAtEpochMillis > 0 &&
        provenance.matchesMemoryProvenanceContract()

fun PhoneMemoryList.matchesToolContract(): Boolean =
    status == PHONE_MEMORY_STATUS_AVAILABLE &&
        count in 0..MAX_PHONE_MEMORY_ROWS &&
        entries.size <= MAX_PHONE_MEMORY_LIST_ENTRIES &&
        entries.size <= count &&
        truncated == (count > entries.size) &&
        entries.all(PhoneMemoryEntry::matchesToolContract)

fun PhoneMemoryForgotten.matchesToolContract(): Boolean =
    deletedCount in 0..MAX_PHONE_MEMORY_ROWS &&
        remainingCount == 0

fun PhoneMemoryDeleted.matchesToolContract(): Boolean =
    memoryId > 0 &&
        deletedCount == 1 &&
        remainingCount in 0 until MAX_PHONE_MEMORY_ROWS

fun PhoneMemoryUpdated.matchesToolContract(): Boolean =
    memoryId > 0 &&
        text.matchesMemoryTextContract() &&
        createdAtEpochMillis > 0 &&
        provenance.matchesMemoryProvenanceContract()

fun String.matchesNoteTextContract(): Boolean =
    isNotBlank() &&
        length <= MAX_NOTE_TEXT_LENGTH &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

fun String.matchesMemoryTextContract(): Boolean =
    isNotBlank() &&
        length <= MAX_MEMORY_TEXT_LENGTH &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

fun String.matchesMemoryProvenanceContract(): Boolean =
    this == PHONE_MEMORY_PROVENANCE_USER_APPROVED

fun PhoneTimerCreateArguments.matchesToolContract(): Boolean =
    durationSeconds in MIN_TIMER_SECONDS..MAX_TIMER_SECONDS && skipClockUi

fun PhoneTimerDispatched.matchesToolContract(): Boolean =
    durationSeconds in MIN_TIMER_SECONDS..MAX_TIMER_SECONDS &&
        clockPackage.isAllowlistedSystemClockPackage() &&
        clockActivity.matches(ANDROID_CLASS_NAME) &&
        clockActivity.startsWith("$clockPackage.") &&
        systemApplication &&
        skipClockUiRequested &&
        systemAction == ANDROID_SET_TIMER_ACTION

fun String.isAllowlistedSystemClockPackage(): Boolean = this in ALLOWLISTED_SYSTEM_CLOCK_PACKAGES

private fun String.isSafeMacFilesRelativePath(): Boolean =
    length <= MAX_MAC_FILES_RELATIVE_PATH_LENGTH &&
        !startsWith("/") &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        } &&
        split("/").none { part -> part == ".." }

private fun String.isSafeMacFilesOutputPath(maximum: Int): Boolean =
    isNotBlank() &&
        length <= maximum &&
        !startsWith("/") &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        } &&
        split("/").none { part -> part.isBlank() || part == "." || part == ".." }

private fun String.isSafeGitStatusPath(): Boolean =
    isNotBlank() &&
        length <= MAX_GIT_STATUS_PATH_LENGTH &&
        !startsWith("/") &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        } &&
        split("/").none { part -> part == ".." }

private fun String.isSafeClipboardText(): Boolean =
    isNotEmpty() &&
        length <= MAX_MAC_CLIPBOARD_TEXT_LENGTH &&
        none { character ->
            character == '\u0000' ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

private fun String.isSafeQrPreview(): Boolean =
    isNotBlank() &&
        length <= MAX_QR_PREVIEW_LENGTH &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

private fun String.isSafeOcrPreview(): Boolean =
    isNotBlank() &&
        length <= MAX_OCR_PREVIEW_LENGTH &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

private fun String?.doesNotContainFileUrl(): Boolean =
    this == null || !contains("file://", ignoreCase = true)

private fun String?.isNullOrSafeDisplayField(maximum: Int): Boolean =
    this == null || isSafeDisplayField(maximum)

private fun String.isSafeMacBundleId(): Boolean =
    isNotBlank() &&
        length <= MAX_MAC_APP_BUNDLE_ID_LENGTH &&
        contains(".") &&
        !contains("..") &&
        MAC_APP_BUNDLE_ID.matches(this)

private fun String.isSafeMacAppDisplayName(): Boolean =
    isSafeDisplayField(MAX_MAC_APP_DISPLAY_NAME_LENGTH) &&
        !contains("/") &&
        !contains("\\")

private fun String.isSafeDisplayField(maximum: Int): Boolean =
    isNotBlank() &&
        length <= maximum &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

private fun String.isSafeRomStatusField(maximum: Int): Boolean =
    isSafeDisplayField(maximum) &&
        !containsGoffyRomPathLikeText() &&
        GOFFY_ROM_COMMAND_TEXT_PATTERNS.none { pattern -> pattern.containsMatchIn(this) }

private fun String.containsGoffyRomPathLikeText(): Boolean {
    if (contains("\\", ignoreCase = false) || contains("file://", ignoreCase = true)) {
        return true
    }
    return GOFFY_ROM_SAFE_SLASH_TOKEN.replace(this, "").contains("/")
}

private const val MIN_BATTERY_PERCENT = 0
private const val MAX_BATTERY_PERCENT = 100
const val GOFFY_ROM_MILESTONE = "ROM-0"
const val MAX_GOFFY_ROM_SUMMARY_LENGTH = 192
const val MAX_GOFFY_ROM_TIMESTAMP_LENGTH = 64
const val MAX_GOFFY_ROM_SCHEMA_LENGTH = 64
const val MAX_GOFFY_ROM_STATUS_LENGTH = 96
const val MAX_GOFFY_ROM_BLOCKERS = 8
const val MAX_GOFFY_ROM_BLOCKER_LENGTH = 160
const val MAX_GOFFY_ROM_NEXT_ACTION_LENGTH = 192
const val MAX_GOFFY_ROM_BLOCKER_COUNT = 10_000
const val GOFFY_ROM_READY_STATUS = "READY_FOR_ROM0_READINESS_REVIEW"
const val MAX_GOFFY_ROM_CHECKLIST_STEPS = 6
const val MAX_GOFFY_ROM_CHECKLIST_STEP_COUNT = 100
const val MAX_GOFFY_ROM_CHECKLIST_TITLE_LENGTH = 96
const val MAX_GOFFY_ROM_CHECKLIST_KIND_LENGTH = 48
const val MAX_GOFFY_ROM_CHECKLIST_SUMMARY_LENGTH = 192
val GOFFY_ROM_STATUS_VALUES = setOf("available", "missing", "invalid")
val GOFFY_ROM_INSTALL_DECISION_VALUES = setOf("BLOCKED", "READY_FOR_MANUAL_REVIEW")
val GOFFY_ROM_CHECKLIST_AVAILABLE_STATUS_VALUES = setOf(
    "BLOCKED_EVIDENCE",
    GOFFY_ROM_READY_STATUS,
)
val GOFFY_ROM_CHECKLIST_STATUS_VALUES = GOFFY_ROM_CHECKLIST_AVAILABLE_STATUS_VALUES + setOf(
    "MISSING",
    "INVALID",
)
val GOFFY_ROM_CHECKLIST_STEP_STATUS_VALUES = setOf("DONE", "READY", "BLOCKED")
val GOFFY_ROM_CHECKLIST_NEXT_STEP_STATUS_VALUES = GOFFY_ROM_CHECKLIST_STEP_STATUS_VALUES + setOf(
    "MISSING",
    "INVALID",
)
val GOFFY_ROM_CHECKLIST_STEP_KIND_VALUES = setOf(
    "LOCAL_READ_ONLY",
    "HUMAN_ONLY",
    "TEMPLATE_ONLY",
    "HUMAN_DECISION",
)
private val GOFFY_ROM_COMMAND_TEXT_PATTERNS = listOf(
    Regex(
        "\\b(?:adb|fastboot)\\s+" +
            "(?:reboot|shell|sideload|push|install|uninstall|root|remount|" +
            "disable-verity|enable-verity|flash|flashing|oem|erase|wipe|boot|getvar|devices)\\b",
        RegexOption.IGNORE_CASE,
    ),
    Regex("\\b(?:avbctl|magisk)\\b", RegexOption.IGNORE_CASE),
    Regex("\\b(?:sh|su|pm|cmd|am|rm|dd|mkfs)\\s+", RegexOption.IGNORE_CASE),
    Regex("\\breboot\\s+(?:bootloader|fastboot|recovery)\\b", RegexOption.IGNORE_CASE),
    Regex("\\bflash\\s+(?:boot|system|vendor|vbmeta|image)\\b", RegexOption.IGNORE_CASE),
    Regex("\\bboot\\s+\\S+\\.img\\b", RegexOption.IGNORE_CASE),
    Regex("\\bshell\\b", RegexOption.IGNORE_CASE),
)
private val GOFFY_ROM_SAFE_SLASH_TOKEN = Regex("\\b[A-Z0-9]{2,8}(?:/[A-Z0-9]{2,8})+\\b")
private const val MAX_DEVICE_NAME_LENGTH = 128
private const val MAX_ANDROID_RELEASE_LENGTH = 64
private const val MIN_SUPPORTED_SDK = 26
private const val MAX_REASONABLE_SDK = 10_000
const val DEFAULT_MAC_FILES_LIST_ENTRIES = 25
const val DEFAULT_MAC_FILES_LARGEST_ENTRIES = 10
const val DEFAULT_MAC_FILES_LARGEST_DEPTH = 4
const val MAX_MAC_FILES_APPROVED_ROOTS = 8
const val MAX_MAC_FILES_ROOT_INDEX = MAX_MAC_FILES_APPROVED_ROOTS - 1
const val MAX_MAC_FILES_LIST_ENTRIES = 32
const val MAX_MAC_FILES_LARGEST_ENTRIES = 25
const val MAX_MAC_FILES_LARGEST_DEPTH = 8
const val MAX_MAC_FILES_LARGEST_SCANNED_ENTRIES = 5_000
const val MAX_MAC_FILES_LARGEST_FILE_SIZE_BYTES = Long.MAX_VALUE
const val MAX_MAC_FILES_RELATIVE_PATH_LENGTH = 512
const val MAX_MAC_FILES_LARGEST_PATH_LENGTH = 192
const val MAX_MAC_FILES_ROOT_NAME_LENGTH = 64
const val MAX_MAC_FILES_ENTRY_NAME_LENGTH = 96
val MAC_FILES_ENTRY_KINDS = setOf("file", "directory", "symlink", "other")
const val DEFAULT_MAC_PROCESS_ENTRIES = 10
const val MAX_MAC_PROCESS_ENTRIES = 25
const val MAX_MAC_PROCESS_COUNT = 100_000
const val MAX_MAC_PROCESS_PID = Int.MAX_VALUE
const val MAX_MAC_PROCESS_RSS_BYTES = Long.MAX_VALUE
const val MAX_MAC_PROCESS_NAME_LENGTH = 96
const val MAX_MAC_PROCESS_STATUS_LENGTH = 32
const val MAX_MAC_PROCESS_STATUS_TEXT_LENGTH = 64
const val DEFAULT_MAC_APP_ENTRIES = 10
const val MAX_MAC_APP_ENTRIES = 25
const val MAX_MAC_APP_COUNT = MAX_MAC_APP_ENTRIES
const val MAX_MAC_APP_INDEX = MAX_MAC_APP_ENTRIES - 1
const val MAX_MAC_APP_DISPLAY_NAME_LENGTH = 80
const val MAX_MAC_APP_BUNDLE_ID_LENGTH = 160
const val MAX_MAC_APP_STATUS_LENGTH = 64
const val DEFAULT_GIT_STATUS_CHANGES = 25
const val MAX_GIT_STATUS_REPOS = 8
const val MAX_GIT_STATUS_REPO_INDEX = MAX_GIT_STATUS_REPOS - 1
const val MAX_GIT_STATUS_CHANGES = 32
const val MAX_GIT_STATUS_REPO_NAME_LENGTH = 64
const val MAX_GIT_STATUS_PATH_LENGTH = 160
const val MAX_GIT_STATUS_BRANCH_LENGTH = 96
const val MAX_GIT_STATUS_UPSTREAM_LENGTH = 128
const val MAX_GIT_STATUS_OID_LENGTH = 16
const val MAX_GIT_STATUS_STATUS_LENGTH = 64
const val MAX_GIT_STATUS_COUNT = 10_000
val GIT_STATUS_CHANGE_KINDS = setOf("tracked", "untracked", "conflict")
val GIT_STATUS_CODE_VALUES = setOf(".", "M", "T", "A", "D", "R", "C", "U", "?", "!")
const val DEFAULT_MAC_CLIPBOARD_READ_CHARS = 1_000
const val MAX_MAC_CLIPBOARD_TEXT_LENGTH = 2_000
const val MAX_MAC_CLIPBOARD_CHARACTER_COUNT = 100_000
val MAC_CLIPBOARD_STATUS_VALUES = setOf("available", "empty", "unsupported")
const val MAX_NOTE_TEXT_LENGTH = 2_000
const val MAX_MEMORY_TEXT_LENGTH = 512
const val MAX_PHONE_MEMORY_ROWS = 100
const val MAX_PHONE_MEMORY_LIST_ENTRIES = 20
const val PHONE_MEMORY_STATUS_AVAILABLE = "available"
const val PHONE_MEMORY_PROVENANCE_USER_APPROVED = "user_approved_phone_command"
const val PHONE_QR_STATUS_AVAILABLE = "available"
const val MAX_QR_PREVIEW_LENGTH = 96
const val MAX_QR_PAYLOAD_CHARACTER_COUNT = 10_000
val PHONE_QR_CONTENT_TYPES = setOf("text", "url", "wifi", "sensitive", "unknown")
const val PHONE_OCR_STATUS_AVAILABLE = "available"
const val MAX_OCR_PREVIEW_LENGTH = 600
const val MAX_OCR_CHARACTER_COUNT = 20_000
const val MAX_OCR_LINE_COUNT = 128
val PHONE_OCR_SCRIPTS = setOf("latin")
const val MIN_TIMER_SECONDS = 1
const val MAX_TIMER_SECONDS = 86_400
const val ANDROID_SET_TIMER_ACTION = "android.intent.action.SET_TIMER"
private val ANDROID_CLASS_NAME = Regex("^[A-Za-z0-9_]+(?:[.$][A-Za-z0-9_]+)+$")
private val MAC_APP_BUNDLE_ID = Regex("^[A-Za-z0-9][A-Za-z0-9.-]{0,158}[A-Za-z0-9]$")
private val ALLOWLISTED_SYSTEM_CLOCK_PACKAGES = setOf(
    "com.android.deskclock",
    "com.google.android.deskclock",
)
