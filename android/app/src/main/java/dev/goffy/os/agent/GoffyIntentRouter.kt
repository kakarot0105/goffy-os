package dev.goffy.os.agent

import dev.goffy.os.capability.PhoneCapabilityRegistry
import dev.goffy.os.localmodel.DisabledLocalModelIntentFallback
import dev.goffy.os.localmodel.LocalModelIntentFallback
import dev.goffy.os.localmodel.LocalModelIntentObservation
import dev.goffy.os.localmodel.isSafeLocalModelPrompt
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GIT_STATUS_TOOL
import dev.goffy.os.protocol.GitStatusArguments
import dev.goffy.os.protocol.GOFFY_ROM_STATUS_TOOL
import dev.goffy.os.protocol.MAC_APPS_LIST_TOOL
import dev.goffy.os.protocol.MAC_APPS_OPEN_TOOL
import dev.goffy.os.protocol.MAC_CLIPBOARD_READ_TOOL
import dev.goffy.os.protocol.MAC_FILES_LARGEST_TOOL
import dev.goffy.os.protocol.MAC_FILES_LIST_TOOL
import dev.goffy.os.protocol.MAC_PROCESSES_LIST_TOOL
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.MacAppsListArguments
import dev.goffy.os.protocol.MacAppsOpenArguments
import dev.goffy.os.protocol.MacFilesLargestArguments
import dev.goffy.os.protocol.MacFilesListArguments
import dev.goffy.os.protocol.MacProcessesListArguments
import dev.goffy.os.protocol.MAX_TIMER_SECONDS
import dev.goffy.os.protocol.NoToolArguments
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_FORGET_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_FORGET_ALL_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_LIST_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_REMEMBER_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_UPDATE_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PhoneMemoryForgetArguments
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneMemoryRememberArguments
import dev.goffy.os.protocol.PhoneMemoryUpdateArguments
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.ToolArguments
import dev.goffy.os.protocol.matchesMemoryTextContract
import dev.goffy.os.protocol.matchesNoteTextContract
import java.util.Locale

data class GoffyExecutionPlan(
    val command: String,
    val executionTarget: ExecutionTarget,
    val toolName: String,
    val permission: PermissionLevel,
    val successCriteria: List<String>,
    val arguments: ToolArguments = NoToolArguments,
)

sealed interface RoutingDecision {
    data class Routed(val plan: GoffyExecutionPlan) : RoutingDecision

    data class Unsupported(
        val normalizedCommand: String,
        val localModelObservation: LocalModelIntentObservation? = null,
    ) : RoutingDecision
}

object GoffyIntentRouter {
    private val phoneCapabilities = PhoneCapabilityRegistry.default
    private val whitespace = Regex("\\s+")
    private val goffyRomStatusCommand = Regex(
        pattern =
            "^(?:(?:show|check|explain)(?: me)? (?:the )?(?:(?:goffy )?(?:rom|rom-0) status|goffy os status)|" +
                "is (?:the )?(?:goffy )?rom ready|what are we building now" +
                "(?: can you explain)?)" +
                "[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macStatusCommand = Regex(
        pattern = "^(?:show|check)(?: me)? my mac status[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macFilesListCommand = Regex(
        pattern = "^(?:show|list)(?: me)? my mac files[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macFilesLargestCommand = Regex(
        pattern = "^(?:find|show|list)(?: me)? (?:the )?largest files on my mac[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macProcessesListCommand = Regex(
        pattern = "^(?:what(?:'s| is) running on my mac|(?:show|check|list)(?: me)? my mac processes)[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macAppsListCommand = Regex(
        pattern = "^(?:(?:show|list)(?: me)? my mac (?:apps|applications)|what apps are approved on my mac)[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macAppOpenCommand = Regex(
        pattern = "^(?:open|launch) ([A-Za-z0-9][A-Za-z0-9 ._-]{0,79}) on my mac[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val gitStatusCommand = Regex(
        pattern = "^(?:show|check)(?: me)? my git status[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val macClipboardReadCommands = setOf(
        "read my mac clipboard",
        "show my mac clipboard",
    )
    private val batteryStatusCommand = Regex(
        pattern =
            "^(?:(?:show|check)(?: me)? my (?:phone )?battery (?:status|level)|" +
                "what(?:'s| is) my (?:phone )?battery (?:status|level))[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val deviceInfoCommand = Regex(
        pattern =
            "^(?:(?:show|check)(?: me)? my (?:phone|device) " +
                "(?:info|information|details)|what phone is this)[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val noteCreatePrefix = Regex(
        pattern = "^(?:create|make)(?: me)? a note (?:saying|that says)\\s+",
        option = RegexOption.IGNORE_CASE,
    )
    private val memoryRememberPrefix = Regex(
        pattern = "^(?:remember|save to memory) (?:that\\s+)?",
        option = RegexOption.IGNORE_CASE,
    )
    private val memoryListCommands = setOf(
        "what do you remember",
        "show my memories",
        "list my memories",
    )
    private val memoryForgetAllCommands = setOf(
        "forget all memories",
        "clear all memories",
        "delete all memories",
    )
    private val memoryForgetCommand = Regex(
        pattern = "^(?:forget|delete) (?:local )?memory #?([0-9]+)[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val memoryUpdateCommand = Regex(
        pattern = "^(?:update|edit) (?:local )?memory #?([0-9]+) to\\s+(.+)[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val timerCreateCommand = Regex(
        pattern = "^(?:set|start|create)(?: me)? a timer for ([0-9]+) " +
            "(second|seconds|minute|minutes|hour|hours)[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )
    private val flashlightSetCommand = Regex(
        pattern = "^(?:turn|switch) (?:(?:the )?(?:flashlight|torch) (on|off)|" +
            "(on|off) (?:the )?(?:flashlight|torch))[.!?]?$",
        option = RegexOption.IGNORE_CASE,
    )

    fun route(
        command: String,
        localModelFallback: LocalModelIntentFallback = DisabledLocalModelIntentFallback,
    ): RoutingDecision {
        memoryRememberPlan(command)?.let { return RoutingDecision.Routed(it) }
        noteCreatePlan(command)?.let { return RoutingDecision.Routed(it) }
        memoryForgetPlan(command)?.let { return RoutingDecision.Routed(it) }
        memoryUpdatePlan(command)?.let { return RoutingDecision.Routed(it) }
        val rawCommandRejectedForLocalModel = command.hasUnsafeControlOrFormatCharacters()
        val normalized = command.trim().replace(whitespace, " ")
        val plan = when {
            goffyRomStatusCommand.matches(normalized) -> goffyRomStatusPlan(normalized)
            macStatusCommand.matches(normalized) -> macStatusPlan(normalized)
            macProcessesListCommand.matches(normalized) -> macProcessesListPlan(normalized)
            macAppOpenCommand.matches(normalized) ->
                macAppOpenPlan(normalized) ?: return unsupported(
                    normalized,
                    localModelFallback,
                    rawCommandRejectedForLocalModel,
                )
            macAppsListCommand.matches(normalized) -> macAppsListPlan(normalized)
            macFilesLargestCommand.matches(normalized) -> macFilesLargestPlan(normalized)
            macFilesListCommand.matches(normalized) -> macFilesListPlan(normalized)
            gitStatusCommand.matches(normalized) -> gitStatusPlan(normalized)
            normalized.lowercase(Locale.US) in macClipboardReadCommands -> macClipboardReadPlan(normalized)
            batteryStatusCommand.matches(normalized) -> batteryStatusPlan(normalized)
            deviceInfoCommand.matches(normalized) -> deviceInfoPlan(normalized)
            normalized.lowercase(Locale.US) in memoryListCommands -> memoryListPlan(normalized)
            normalized.lowercase(Locale.US) in memoryForgetAllCommands -> memoryForgetAllPlan(normalized)
            flashlightSetCommand.matches(normalized) -> flashlightSetPlan(normalized)
            timerCreateCommand.matches(normalized) -> timerCreatePlan(normalized)
                ?: return unsupported(
                    normalized,
                    localModelFallback,
                    rawCommandRejectedForLocalModel,
                )
            else -> return unsupported(normalized, localModelFallback, rawCommandRejectedForLocalModel)
        }

        return RoutingDecision.Routed(plan)
    }

    private fun unsupported(
        normalizedCommand: String,
        localModelFallback: LocalModelIntentFallback,
        rawCommandRejectedForLocalModel: Boolean = false,
    ): RoutingDecision.Unsupported {
        val observation = if (rawCommandRejectedForLocalModel || !isSafeLocalModelPrompt(normalizedCommand)) {
            LocalModelIntentObservation.Rejected(
                "Command is outside local model prompt safety bounds.",
            )
        } else {
            localModelFallback.observeUnsupportedCommand(normalizedCommand)
        }
        return RoutingDecision.Unsupported(normalizedCommand, observation)
    }

    private fun noteCreatePlan(command: String): GoffyExecutionPlan? {
        val trimmed = command.trim()
        val prefix = noteCreatePrefix.find(trimmed) ?: return null
        val text = trimmed.substring(prefix.range.last + 1).trim()
        if (!text.matchesNoteTextContract()) return null
        return GoffyExecutionPlan(
            command = trimmed,
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_NOTE_CREATE_TOOL,
            permission = phonePermission(PHONE_NOTE_CREATE_TOOL),
            successCriteria = listOf(
                "The exact approved note text is stored in app-private storage",
                "The stored row is re-read and matches the typed note contract",
            ),
            arguments = PhoneNoteCreateArguments(text),
        )
    }

    private fun memoryRememberPlan(command: String): GoffyExecutionPlan? {
        val trimmed = command.trim()
        val prefix = memoryRememberPrefix.find(trimmed) ?: return null
        val text = trimmed.substring(prefix.range.last + 1).trim()
        if (!text.matchesMemoryTextContract()) return null
        return GoffyExecutionPlan(
            command = trimmed,
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_MEMORY_REMEMBER_TOOL,
            permission = phonePermission(PHONE_MEMORY_REMEMBER_TOOL),
            successCriteria = listOf(
                "The exact approved memory text is stored in app-private storage",
                "The stored row is re-read with user-approved provenance",
                "The memory remains inspectable and deletable from local phone tools",
            ),
            arguments = PhoneMemoryRememberArguments(text),
        )
    }

    private fun memoryListPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_MEMORY_LIST_TOOL,
        permission = phonePermission(PHONE_MEMORY_LIST_TOOL),
        successCriteria = listOf(
            "GOFFY reads only app-private user-approved memories",
            "The result is bounded and indicates whether it was truncated",
            "Each returned memory includes inspectable provenance",
        ),
    )

    private fun memoryForgetAllPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_MEMORY_FORGET_ALL_TOOL,
        permission = phonePermission(PHONE_MEMORY_FORGET_ALL_TOOL),
        successCriteria = listOf(
            "GOFFY deletes only app-private user-approved memories after approval",
            "The delete count is captured",
            "The remaining memory count is verified as zero",
        ),
    )

    private fun memoryForgetPlan(command: String): GoffyExecutionPlan? {
        if (command.hasUnsafeControlOrFormatCharacters()) return null
        val normalized = command.trim().replace(whitespace, " ")
        val match = memoryForgetCommand.matchEntire(normalized) ?: return null
        val memoryId = match.groupValues[1].toLongOrNull()?.takeIf { it > 0 } ?: return null
        return GoffyExecutionPlan(
            command = normalized,
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_MEMORY_FORGET_TOOL,
            permission = phonePermission(PHONE_MEMORY_FORGET_TOOL),
            successCriteria = listOf(
                "GOFFY deletes only the exact approved app-private memory ID",
                "The selected memory is re-read and verified absent",
                "The remaining memory count is reported",
            ),
            arguments = PhoneMemoryForgetArguments(memoryId),
        )
    }

    private fun memoryUpdatePlan(command: String): GoffyExecutionPlan? {
        if (command.hasUnsafeControlOrFormatCharacters()) return null
        val normalized = command.trim().replace(whitespace, " ")
        val match = memoryUpdateCommand.matchEntire(normalized) ?: return null
        val memoryId = match.groupValues[1].toLongOrNull()?.takeIf { it > 0 } ?: return null
        val text = match.groupValues[2].trim()
        if (!text.matchesMemoryTextContract()) return null
        return GoffyExecutionPlan(
            command = normalized,
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_MEMORY_UPDATE_TOOL,
            permission = phonePermission(PHONE_MEMORY_UPDATE_TOOL),
            successCriteria = listOf(
                "GOFFY updates only the exact approved app-private memory ID",
                "The stored row is re-read and matches the approved replacement text",
                "The memory remains inspectable and deletable from local phone tools",
            ),
            arguments = PhoneMemoryUpdateArguments(memoryId, text),
        )
    }

    private fun timerCreatePlan(command: String): GoffyExecutionPlan? {
        val match = timerCreateCommand.matchEntire(command) ?: return null
        val amount = match.groupValues[1].toLongOrNull() ?: return null
        val multiplier = when (match.groupValues[2].lowercase()) {
            "second", "seconds" -> 1L
            "minute", "minutes" -> 60L
            "hour", "hours" -> 3_600L
            else -> return null
        }
        if (amount !in 1L..(MAX_TIMER_SECONDS / multiplier)) return null
        val durationSeconds = amount * multiplier
        return GoffyExecutionPlan(
            command = command,
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_TIMER_CREATE_TOOL,
            permission = phonePermission(PHONE_TIMER_CREATE_TOOL),
            successCriteria = listOf(
                "GOFFY sends the exact approved duration to an explicit allowlisted system Clock",
                "GOFFY reports the unreadable Clock postcondition as unverified",
            ),
            arguments = PhoneTimerCreateArguments(
                durationSeconds = durationSeconds.toInt(),
                skipClockUi = true,
            ),
        )
    }

    private fun flashlightSetPlan(command: String): GoffyExecutionPlan {
        val match = requireNotNull(flashlightSetCommand.matchEntire(command))
        val requestedState = match.groupValues.drop(1).first(String::isNotEmpty)
        val enabled = requestedState.equals("on", ignoreCase = true)
        return GoffyExecutionPlan(
            command = command,
            executionTarget = ExecutionTarget.PHONE,
            toolName = PHONE_FLASHLIGHT_SET_TOOL,
            permission = phonePermission(PHONE_FLASHLIGHT_SET_TOOL),
            successCriteria = listOf(
                "The back-camera torch reaches the exact approved state",
                "CameraManager confirms the state through TorchCallback",
                "The callback is unregistered after the bounded operation",
            ),
            arguments = PhoneFlashlightSetArguments(enabled),
        )
    }

    private fun macStatusPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_SYSTEM_INFO_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid structured system information",
            "Hub emits a successful verification result",
        ),
    )

    private fun goffyRomStatusPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = GOFFY_ROM_STATUS_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid ROM-0 status from fixed GOFFY readiness artifacts",
            "Hub emits a successful verification result",
            "The result contains no unlock, reboot, flash, erase, wipe, boot, or shell authority",
        ),
    )

    private fun macProcessesListPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_PROCESSES_LIST_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid bounded running-process metadata",
            "Hub emits a successful verification result",
            "The result contains no command lines, executable paths, environment variables, open files, or network data",
        ),
        arguments = MacProcessesListArguments(),
    )

    private fun macAppsListPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_APPS_LIST_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid bounded approved app catalog metadata",
            "Hub emits a successful verification result",
            "The result contains no app launch, file open, installed-app scan, app path, or shell authority",
        ),
        arguments = MacAppsListArguments(),
    )

    private fun macAppOpenPlan(command: String): GoffyExecutionPlan? {
        val match = requireNotNull(macAppOpenCommand.matchEntire(command))
        val displayName = match.groupValues[1].trim()
        val words = displayName.lowercase(Locale.US).split(whitespace)
        if (words.any { it == "and" || it == "then" }) return null
        return GoffyExecutionPlan(
            command = command,
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_APPS_OPEN_TOOL,
            permission = PermissionLevel.CONFIRM,
            successCriteria = listOf(
                "The user grants one visible approval before the Mac request is sent",
                "Hub maps the typed display name to an explicitly approved bundle identifier",
                "Hub verifies the approved app is running after Launch Services accepts the request",
                "The result contains no file path, shell command, or installed-app scan authority",
            ),
            arguments = MacAppsOpenArguments(displayName),
        )
    }

    private fun macFilesListPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_FILES_LIST_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid approved-root directory metadata",
            "Hub emits a successful verification result",
            "The result contains no absolute approved-root path or file contents",
        ),
        arguments = MacFilesListArguments(rootIndex = 0),
    )

    private fun macFilesLargestPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_FILES_LARGEST_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid largest-file metadata from an approved root",
            "Hub emits a successful verification result",
            "The result contains no absolute approved-root path, file contents, or symlink targets",
        ),
        arguments = MacFilesLargestArguments(rootIndex = 0),
    )

    private fun gitStatusPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = GIT_STATUS_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid approved-repo Git status metadata",
            "Hub emits a successful verification result",
            "The result contains no absolute repo root, file contents, diff, fetch, commit, or push",
        ),
        arguments = GitStatusArguments(repoIndex = 0),
    )

    private fun macClipboardReadPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.MAC,
        toolName = MAC_CLIPBOARD_READ_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Hub returns schema-valid bounded plaintext clipboard metadata",
            "Hub emits a successful verification result",
            "The result contains no file URLs, binary formats, or clipboard write authority",
        ),
    )

    private fun batteryStatusPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_BATTERY_STATUS_TOOL,
        permission = phonePermission(PHONE_BATTERY_STATUS_TOOL),
        successCriteria = listOf(
            "Phone returns a battery percentage from 0 through 100",
            "Phone emits a successful local verification result",
        ),
    )

    private fun deviceInfoPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_DEVICE_INFO_TOOL,
        permission = phonePermission(PHONE_DEVICE_INFO_TOOL),
        successCriteria = listOf(
            "Phone returns privacy-minimized device and Android version information",
            "Phone emits a successful local verification result",
        ),
    )

    private fun phonePermission(toolName: String): PermissionLevel =
        checkNotNull(phoneCapabilities.find(toolName)) {
            "Missing compiled PHONE capability: $toolName"
        }.metadata.permission
}

private fun String.hasUnsafeControlOrFormatCharacters(): Boolean =
    any { character ->
        character.isISOControl() ||
            Character.getType(character) == Character.FORMAT.toInt()
    }
