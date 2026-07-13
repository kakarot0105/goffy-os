package dev.goffy.os.phone

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.PermissionLevel
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.ToolProgress
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

fun interface BatteryStatusSource {
    suspend fun read(): PhoneBatteryStatus
}

interface PhoneToolGateway {
    fun invoke(plan: GoffyExecutionPlan): Flow<ExecutionEvent>

    fun close()
}

class DefaultPhoneToolGateway internal constructor(
    private val readDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val timeoutMillis: Long = DEFAULT_TIMEOUT_MILLIS,
    private val batteryStatusSource: BatteryStatusSource,
) : PhoneToolGateway {
    init {
        require(timeoutMillis > 0) { "timeoutMillis must be positive" }
    }

    override fun invoke(plan: GoffyExecutionPlan): Flow<ExecutionEvent> = flow {
        if (!plan.isAllowedBatteryStatusPlan()) {
            emit(
                ExecutionEvent.Error(
                    code = "phone_tool_unauthorized",
                    message = "The requested phone tool is unavailable or unauthorized",
                    retryable = false,
                ),
            )
            return@flow
        }

        emit(ExecutionEvent.Starting(attempt = 1))
        emit(ExecutionEvent.Ready)
        emit(
            ExecutionEvent.Progress(
                ToolProgress(
                    toolName = PHONE_BATTERY_STATUS_TOOL,
                    executionTarget = ExecutionTarget.PHONE,
                    stage = "accepted",
                    sequence = 0,
                    message = "Battery status read accepted on this phone.",
                ),
            ),
        )

        val status = try {
            withTimeout(timeoutMillis) {
                withContext(readDispatcher) { batteryStatusSource.read() }
            }
        } catch (_: TimeoutCancellationException) {
            emit(
                ExecutionEvent.Error(
                    code = "phone_tool_timeout",
                    message = "Battery status did not respond before the timeout",
                    retryable = false,
                ),
            )
            return@flow
        } catch (error: Exception) {
            if (error is CancellationException) throw error
            emit(
                ExecutionEvent.Error(
                    code = "phone_tool_failed",
                    message = "Battery status is unavailable on this phone",
                    retryable = false,
                ),
            )
            return@flow
        }

        if (status.levelPercent !in MIN_BATTERY_PERCENT..MAX_BATTERY_PERCENT) {
            emit(
                ExecutionEvent.Error(
                    code = "invalid_tool_output",
                    message = "Battery status failed output validation",
                    retryable = false,
                ),
            )
            return@flow
        }

        emit(
            ExecutionEvent.Progress(
                ToolProgress(
                    toolName = PHONE_BATTERY_STATUS_TOOL,
                    executionTarget = ExecutionTarget.PHONE,
                    stage = "completed",
                    sequence = 1,
                    message = "BatteryManager returned validated local status.",
                ),
            ),
        )
        emit(
            ExecutionEvent.Result(
                toolName = PHONE_BATTERY_STATUS_TOOL,
                executionTarget = ExecutionTarget.PHONE,
                content = status,
            ),
        )
        emit(
            ExecutionEvent.Verification(
                succeeded = true,
                summary = "Battery status matched the local tool contract.",
                checks = listOf(
                    "phone tool allowlist",
                    "battery percentage range",
                    "typed output",
                ),
            ),
        )
    }

    override fun close() = Unit

    private fun GoffyExecutionPlan.isAllowedBatteryStatusPlan(): Boolean =
        executionTarget == ExecutionTarget.PHONE &&
            toolName == PHONE_BATTERY_STATUS_TOOL &&
            permission == PermissionLevel.SAFE

    private companion object {
        const val MIN_BATTERY_PERCENT = 0
        const val MAX_BATTERY_PERCENT = 100
        const val DEFAULT_TIMEOUT_MILLIS = 2_000L
    }
}
