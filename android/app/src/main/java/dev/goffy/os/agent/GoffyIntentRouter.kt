package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAC_SYSTEM_INFO_TOOL
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL

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

    fun route(command: String): RoutingDecision {
        val normalized = command.trim().replace(whitespace, " ")
        val plan = when {
            macStatusCommand.matches(normalized) -> macStatusPlan(normalized)
            batteryStatusCommand.matches(normalized) -> batteryStatusPlan(normalized)
            deviceInfoCommand.matches(normalized) -> deviceInfoPlan(normalized)
            else -> return RoutingDecision.Unsupported(normalized)
        }

        return RoutingDecision.Routed(plan)
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
