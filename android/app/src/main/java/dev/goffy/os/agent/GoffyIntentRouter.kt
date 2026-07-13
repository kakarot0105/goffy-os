package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.NoToolArguments
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.ToolArguments
import dev.goffy.os.protocol.matchesNoteTextContract

enum class PermissionLevel {
    SAFE,
    CONFIRM,
    SENSITIVE,
    BLOCKED,
}

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

    fun route(command: String): RoutingDecision {
        noteCreatePlan(command)?.let { return RoutingDecision.Routed(it) }
        val normalized = command.trim().replace(whitespace, " ")
        val plan = when {
            macStatusCommand.matches(normalized) -> macStatusPlan(normalized)
            batteryStatusCommand.matches(normalized) -> batteryStatusPlan(normalized)
            deviceInfoCommand.matches(normalized) -> deviceInfoPlan(normalized)
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
            permission = PermissionLevel.CONFIRM,
            successCriteria = listOf(
                "The exact approved note text is stored in app-private storage",
                "The stored row is re-read and matches the typed note contract",
            ),
            arguments = PhoneNoteCreateArguments(text),
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
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Phone returns a battery percentage from 0 through 100",
            "Phone emits a successful local verification result",
        ),
    )

    private fun deviceInfoPlan(command: String): GoffyExecutionPlan = GoffyExecutionPlan(
        command = command,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_DEVICE_INFO_TOOL,
        permission = PermissionLevel.SAFE,
        successCriteria = listOf(
            "Phone returns privacy-minimized device and Android version information",
            "Phone emits a successful local verification result",
        ),
    )
}
