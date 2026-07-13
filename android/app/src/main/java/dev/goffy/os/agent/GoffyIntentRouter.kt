package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget

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

    fun route(command: String): RoutingDecision {
        val normalized = command.trim().replace(whitespace, " ")
        if (!macStatusCommand.matches(normalized)) {
            return RoutingDecision.Unsupported(normalized)
        }

        return RoutingDecision.Routed(
            GoffyExecutionPlan(
                command = normalized,
                executionTarget = ExecutionTarget.MAC,
                toolName = MAC_SYSTEM_INFO_TOOL,
                permission = PermissionLevel.SAFE,
                successCriteria = listOf(
                    "Hub returns schema-valid structured system information",
                    "Hub emits a successful verification result",
                ),
            ),
        )
    }

    const val MAC_SYSTEM_INFO_TOOL = "mac.system_info"
}
