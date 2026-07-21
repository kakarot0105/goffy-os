package dev.goffy.os.protocol

fun PhoneBatteryStatus.matchesToolContract(): Boolean =
    levelPercent in MIN_BATTERY_PERCENT..MAX_BATTERY_PERCENT

fun PhoneDeviceInfo.matchesToolContract(): Boolean =
    manufacturer.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        model.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        androidRelease.isSafeDisplayField(MAX_ANDROID_RELEASE_LENGTH) &&
        sdkInt in MIN_SUPPORTED_SDK..MAX_REASONABLE_SDK &&
        (!goffyDefaultHome || goffyHomeCandidate)

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
const val MAX_NOTE_TEXT_LENGTH = 2_000
const val MIN_TIMER_SECONDS = 1
const val MAX_TIMER_SECONDS = 86_400
const val ANDROID_SET_TIMER_ACTION = "android.intent.action.SET_TIMER"
private val ANDROID_CLASS_NAME = Regex("^[A-Za-z0-9_]+(?:[.$][A-Za-z0-9_]+)+$")
private val ALLOWLISTED_SYSTEM_CLOCK_PACKAGES = setOf(
    "com.android.deskclock",
    "com.google.android.deskclock",
)
