package dev.goffy.os.agent

import dev.goffy.os.capability.PhoneCapabilityRegistry
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.MAX_TIMER_SECONDS
import dev.goffy.os.protocol.NoToolArguments
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.ToolArguments
import dev.goffy.os.protocol.matchesNoteTextContract

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

    data class Unsupported(val normalizedCommand: String) : RoutingDecision
}

object GoffyIntentRouter {
    private val phoneCapabilities = PhoneCapabilityRegistry.default
    private val whitespace = Regex("\\s+")
    private val macStatusCommand = Regex(
        pattern = "^(?:show|check)(?: me)? my mac status[.!?]?$",
        option = RegexOption.IGNORE_CASE,
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

    fun route(command: String): RoutingDecision {
        noteCreatePlan(command)?.let { return RoutingDecision.Routed(it) }
        val normalized = command.trim().replace(whitespace, " ")
        val plan = when {
            macStatusCommand.matches(normalized) -> macStatusPlan(normalized)
            batteryStatusCommand.matches(normalized) -> batteryStatusPlan(normalized)
            deviceInfoCommand.matches(normalized) -> deviceInfoPlan(normalized)
            flashlightSetCommand.matches(normalized) -> flashlightSetPlan(normalized)
            timerCreateCommand.matches(normalized) -> timerCreatePlan(normalized)
                ?: return RoutingDecision.Unsupported(normalized)
            else -> return RoutingDecision.Unsupported(normalized)
        }

        return RoutingDecision.Routed(plan)
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
