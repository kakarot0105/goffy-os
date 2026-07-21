package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.MacClipboardRead
import dev.goffy.os.protocol.MacFilesList
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.ToolResultContent

private const val MAX_SPEAKABLE_RESULT_CHARS = 480

private val SpeakableResultPhases = setOf(
    TaskPhase.COMPLETED_UNVERIFIED,
    TaskPhase.UNVERIFIED,
    TaskPhase.VERIFIED,
)

internal fun GoffyUiState.latestSpeakableText(): String? =
    timeline.entries.asReversed().firstNotNullOfOrNull(TaskTimelineEntry::speakableText)

private fun TaskTimelineEntry.speakableText(): String? {
    if (phase !in SpeakableResultPhases) return null
    return result?.speakableText(verified = phase == TaskPhase.VERIFIED)
}

private fun ToolResultContent.speakableText(verified: Boolean): String =
    when (this) {
        is GitStatus ->
            if (clean) {
                "Git status for $repoName is clean."
            } else {
                "Git status for $repoName has " +
                    "${stagedCount + unstagedCount + untrackedCount + conflictCount} changes."
            }
        is MacClipboardRead -> clipboardSpeech()
        is MacFilesList ->
            "Mac file listing returned ${entries.size} entries from approved root $rootName. " +
                if (truncated) "The listing was truncated." else "The listing was not truncated."
        is MacSystemInfo ->
            "Mac status is $status. System: $operatingSystem on $architecture."
        is PhoneBatteryStatus ->
            "Phone battery is $levelPercent percent and ${if (charging) "charging" else "not charging"}."
        is PhoneDeviceInfo -> deviceInfoSpeech()
        is PhoneFlashlightState ->
            "Flashlight is ${if (enabled) "on" else "off"}. State ${if (verified) "verified" else "observed"}."
        is PhoneNoteCreated -> noteCreatedSpeech(verified)
        is PhoneTimerDispatched ->
            "Timer request for $durationSeconds seconds was sent to $clockPackage. " +
                "Final timer state is owned by the Clock app."
    }.toBoundedSpeechText()

private fun MacClipboardRead.clipboardSpeech(): String = when (status) {
    "available" -> "Mac clipboard returned bounded text. I will not read clipboard contents aloud."
    "empty" -> "Mac clipboard has no readable text."
    "unsupported" -> "Mac clipboard content is unsupported and was hidden."
    else -> "Mac clipboard status is unavailable."
}

private fun PhoneDeviceInfo.deviceInfoSpeech(): String {
    val homeStatus = when {
        goffyDefaultHome -> "default home"
        goffyHomeCandidate -> "available as a home app"
        else -> "not available as a home app"
    }
    val systemStatus = if (goffySystemApp) "installed as a system app" else "not a system app"
    return "Phone is $manufacturer $model running Android $androidRelease, API $sdkInt. " +
        "GOFFY is $homeStatus and $systemStatus."
}

private fun PhoneNoteCreated.noteCreatedSpeech(verified: Boolean): String {
    val status = if (verified) "stored and verified" else "stored, but verification is still pending"
    return "Private note $noteId was $status. I will not read the note text aloud."
}

private fun String.toBoundedSpeechText(): String =
    replace(Regex("\\s+"), " ")
        .trim()
        .take(MAX_SPEAKABLE_RESULT_CHARS)
