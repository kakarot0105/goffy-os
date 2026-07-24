package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.GoffyRomChecklist
import dev.goffy.os.protocol.GoffyRomStatus
import dev.goffy.os.protocol.MacAppOpened
import dev.goffy.os.protocol.MacAppsList
import dev.goffy.os.protocol.MacClipboardRead
import dev.goffy.os.protocol.MacFilesLargest
import dev.goffy.os.protocol.MacFilesList
import dev.goffy.os.protocol.MacProcessesList
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PhoneMemoryDeleted
import dev.goffy.os.protocol.PhoneMemoryForgotten
import dev.goffy.os.protocol.PhoneMemoryList
import dev.goffy.os.protocol.PhoneMemoryRemembered
import dev.goffy.os.protocol.PhoneMemoryUpdated
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.PhoneOcrRead
import dev.goffy.os.protocol.PhoneQrRead
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
        is GoffyRomChecklist -> romChecklistSpeech()
        is GoffyRomStatus -> romStatusSpeech()
        is MacClipboardRead -> clipboardSpeech()
        is MacAppsList ->
            "Mac approved app catalog returned ${entries.size} apps out of $appCount. " +
                "I will not launch apps without confirmation."
        is MacAppOpened ->
            "Mac app $displayName opened and was verified as running."
        is MacFilesLargest ->
            "Largest-file scan returned ${entries.size} entries from approved root $rootName. " +
                if (truncated) "The scan was truncated." else "The scan was not truncated."
        is MacFilesList ->
            "Mac file listing returned ${entries.size} entries from approved root $rootName. " +
                if (truncated) "The listing was truncated." else "The listing was not truncated."
        is MacProcessesList ->
            "Mac process list returned ${entries.size} process summaries out of $processCount. " +
                "I will not read process names aloud."
        is MacSystemInfo ->
            "Mac status is $status. System: $operatingSystem on $architecture."
        is PhoneBatteryStatus ->
            "Phone battery is $levelPercent percent and ${if (charging) "charging" else "not charging"}."
        is PhoneDeviceInfo -> deviceInfoSpeech()
        is PhoneFlashlightState ->
            "Flashlight is ${if (enabled) "on" else "off"}. State ${if (verified) "verified" else "observed"}."
        is PhoneMemoryDeleted ->
            "Local memory $memoryId was deleted. Remaining count is $remainingCount."
        is PhoneMemoryForgotten ->
            "Deleted $deletedCount local memories. Remaining count is $remainingCount."
        is PhoneMemoryList ->
            "Local memory returned ${entries.size} entries out of $count. I will not read memory text aloud."
        is PhoneMemoryRemembered ->
            "Local memory $memoryId was stored with approved provenance. I will not read the memory text aloud."
        is PhoneMemoryUpdated ->
            "Local memory $memoryId was updated with approved provenance. I will not read the memory text aloud."
        is PhoneNoteCreated -> noteCreatedSpeech(verified)
        is PhoneOcrRead ->
            "OCR read $lineCount lines. " +
                if (redacted) {
                    "The text was hidden from speech and timeline preview."
                } else {
                    "A safe bounded preview is visible on screen."
                }
        is PhoneQrRead ->
            "QR code was read as $contentType. " +
                if (redacted) {
                    "The content was hidden from speech and audit."
                } else {
                    "A safe bounded preview is visible on screen."
                }
        is PhoneTimerDispatched ->
            "Timer request for $durationSeconds seconds was sent to $clockPackage. " +
                "Final timer state is owned by the Clock app."
    }.toBoundedSpeechText()

private fun GoffyRomStatus.romStatusSpeech(): String =
    if (romReady) {
        "GOFFY ROM zero is ready for manual readiness review only. Destructive actions remain withheld."
    } else {
        val safeNextAction = if (nextAction.isSafeRomStatusSpeechText()) {
            "Next action is $nextAction. "
        } else {
            "Next action is hidden because it contained unsafe command or path-like text. "
        }
        "GOFFY ROM zero install decision is $installDecision with $blockerCount blockers. " +
            "DSU preflight is $dsuPreflightGateStatus. " +
            safeNextAction +
            "Destructive actions remain withheld."
    }

private fun GoffyRomChecklist.romChecklistSpeech(): String {
    val safeNextStep = if (nextStepTitle.isSafeRomStatusSpeechText()) {
        "Next step is $nextStepTitle. "
    } else {
        "Next step is hidden because it contained unsafe command or path-like text. "
    }
    return "GOFFY ROM zero checklist has $remainingStepCount steps remaining " +
        "and $blockerCount blockers. " +
        safeNextStep +
        "Destructive actions remain withheld."
}

private fun String.isSafeRomStatusSpeechText(): Boolean =
    isNotBlank() &&
        !containsGoffyRomSpeechPathLikeText() &&
        GoffyRomCommandTextPatterns.none { pattern -> pattern.containsMatchIn(this) }

private fun String.containsGoffyRomSpeechPathLikeText(): Boolean {
    if (contains("\\", ignoreCase = false) || contains("file://", ignoreCase = true)) {
        return true
    }
    return GoffyRomSafeSlashToken.replace(this, "").contains("/")
}

private val GoffyRomCommandTextPatterns = listOf(
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
private val GoffyRomSafeSlashToken = Regex("\\b[A-Z0-9]{2,8}(?:/[A-Z0-9]{2,8})+\\b")

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
