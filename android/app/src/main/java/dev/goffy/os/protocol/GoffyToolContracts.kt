package dev.goffy.os.protocol

fun PhoneBatteryStatus.matchesToolContract(): Boolean =
    levelPercent in MIN_BATTERY_PERCENT..MAX_BATTERY_PERCENT

fun PhoneDeviceInfo.matchesToolContract(): Boolean =
    manufacturer.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        model.isSafeDisplayField(MAX_DEVICE_NAME_LENGTH) &&
        androidRelease.isSafeDisplayField(MAX_ANDROID_RELEASE_LENGTH) &&
        sdkInt in MIN_SUPPORTED_SDK..MAX_REASONABLE_SDK

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
