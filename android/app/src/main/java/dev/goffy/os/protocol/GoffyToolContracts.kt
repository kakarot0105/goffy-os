package dev.goffy.os.protocol

fun PhoneBatteryStatus.matchesToolContract(): Boolean =
    levelPercent in MIN_BATTERY_PERCENT..MAX_BATTERY_PERCENT

fun PhoneDeviceInfo.matchesToolContract(): Boolean =
    manufacturer.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        model.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        androidRelease.isSafeDisplayField(MAX_ANDROID_RELEASE_LENGTH) &&
        sdkInt in MIN_SUPPORTED_SDK..MAX_REASONABLE_SDK &&
        (!goffyDefaultHome || goffyHomeCandidate)

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
const val MAX_NOTE_TEXT_LENGTH = 2_000
const val MIN_TIMER_SECONDS = 1
const val MAX_TIMER_SECONDS = 86_400
const val ANDROID_SET_TIMER_ACTION = "android.intent.action.SET_TIMER"
private val ANDROID_CLASS_NAME = Regex("^[A-Za-z0-9_]+(?:[.$][A-Za-z0-9_]+)+$")
private val ALLOWLISTED_SYSTEM_CLOCK_PACKAGES = setOf(
    "com.android.deskclock",
    "com.google.android.deskclock",
)
