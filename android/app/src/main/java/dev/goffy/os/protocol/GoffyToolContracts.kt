package dev.goffy.os.protocol

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

fun MacFilesListArguments.matchesToolContract(): Boolean =
    rootIndex in 0..MAX_MAC_FILES_ROOT_INDEX &&
        relativePath.isSafeMacFilesRelativePath() &&
        maxEntries in 1..MAX_MAC_FILES_LIST_ENTRIES

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
        (modifiedEpochSeconds == null || modifiedEpochSeconds >= 0)

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

fun String.matchesNoteTextContract(): Boolean =
    isNotBlank() &&
        length <= MAX_NOTE_TEXT_LENGTH &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

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

private fun String?.doesNotContainFileUrl(): Boolean =
    this == null || !contains("file://", ignoreCase = true)

private fun String?.isNullOrSafeDisplayField(maximum: Int): Boolean =
    this == null || isSafeDisplayField(maximum)

private fun String.isSafeDisplayField(maximum: Int): Boolean =
    isNotBlank() &&
        length <= maximum &&
        none { character ->
            character.isISOControl() ||
                Character.getType(character) == Character.FORMAT.toInt()
        }

private const val MIN_BATTERY_PERCENT = 0
private const val MAX_BATTERY_PERCENT = 100
private const val MAX_DEVICE_NAME_LENGTH = 128
private const val MAX_ANDROID_RELEASE_LENGTH = 64
private const val MIN_SUPPORTED_SDK = 26
private const val MAX_REASONABLE_SDK = 10_000
const val DEFAULT_MAC_FILES_LIST_ENTRIES = 25
const val MAX_MAC_FILES_APPROVED_ROOTS = 8
const val MAX_MAC_FILES_ROOT_INDEX = MAX_MAC_FILES_APPROVED_ROOTS - 1
const val MAX_MAC_FILES_LIST_ENTRIES = 32
const val MAX_MAC_FILES_RELATIVE_PATH_LENGTH = 512
const val MAX_MAC_FILES_ROOT_NAME_LENGTH = 64
const val MAX_MAC_FILES_ENTRY_NAME_LENGTH = 96
val MAC_FILES_ENTRY_KINDS = setOf("file", "directory", "symlink", "other")
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
const val PHONE_QR_STATUS_AVAILABLE = "available"
const val MAX_QR_PREVIEW_LENGTH = 96
const val MAX_QR_PAYLOAD_CHARACTER_COUNT = 10_000
val PHONE_QR_CONTENT_TYPES = setOf("text", "url", "wifi", "sensitive", "unknown")
const val MIN_TIMER_SECONDS = 1
const val MAX_TIMER_SECONDS = 86_400
const val ANDROID_SET_TIMER_ACTION = "android.intent.action.SET_TIMER"
private val ANDROID_CLASS_NAME = Regex("^[A-Za-z0-9_]+(?:[.$][A-Za-z0-9_]+)+$")
private val ALLOWLISTED_SYSTEM_CLOCK_PACKAGES = setOf(
    "com.android.deskclock",
    "com.google.android.deskclock",
)
