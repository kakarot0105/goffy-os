package dev.goffy.os.phone

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.PermissionLevel
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.ToolProgress
import dev.goffy.os.protocol.ToolResultContent
import dev.goffy.os.protocol.matchesToolContract
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

fun interface DeviceInfoSource {
    suspend fun read(): PhoneDeviceInfo
}

interface PhoneToolGateway {
    fun invoke(plan: GoffyExecutionPlan): Flow<ExecutionEvent>

    fun close()
}

class DefaultPhoneToolGateway internal constructor(
    private val batteryStatusSource: BatteryStatusSource,
    private val deviceInfoSource: DeviceInfoSource,
    private val readDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val timeoutMillis: Long = DEFAULT_TIMEOUT_MILLIS,
) : PhoneToolGateway {
    init {
        require(timeoutMillis > 0) { "timeoutMillis must be positive" }
    }

    override fun invoke(plan: GoffyExecutionPlan): Flow<ExecutionEvent> = flow {
        val operation = plan.toAllowedOperation()
        if (operation == null) {
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
                    toolName = operation.toolName,
                    executionTarget = ExecutionTarget.PHONE,
                    stage = "accepted",
                    sequence = 0,
                    message = operation.acceptedMessage,
                ),
            ),
        )

        val content = try {
            withTimeout(timeoutMillis) {
                withContext(readDispatcher) { operation.read() }
            }
        } catch (_: TimeoutCancellationException) {
            emit(
                ExecutionEvent.Error(
                    code = "phone_tool_timeout",
                    message = "The local phone tool did not respond before the timeout",
                    retryable = false,
                ),
            )
            return@flow
        } catch (error: Exception) {
            if (error is CancellationException) throw error
            emit(
                ExecutionEvent.Error(
                    code = "phone_tool_failed",
                    message = operation.failureMessage,
                    retryable = false,
                ),
            )
            return@flow
        }

        if (!operation.validate(content)) {
            emit(
                ExecutionEvent.Error(
                    code = "invalid_tool_output",
                    message = "The local phone tool failed output validation",
                    retryable = false,
                ),
            )
            return@flow
        }

        emit(
            ExecutionEvent.Progress(
                ToolProgress(
                    toolName = operation.toolName,
                    executionTarget = ExecutionTarget.PHONE,
                    stage = "completed",
                    sequence = 1,
                    message = operation.completedMessage,
                ),
            ),
        )
        emit(
            ExecutionEvent.Result(
                toolName = operation.toolName,
                executionTarget = ExecutionTarget.PHONE,
                content = content,
            ),
        )
        emit(
            ExecutionEvent.Verification(
                succeeded = true,
                summary = operation.verificationSummary,
                checks = operation.verificationChecks,
            ),
        )
    }

    override fun close() = Unit

    private fun GoffyExecutionPlan.toAllowedOperation(): PhoneToolOperation? {
        if (executionTarget != ExecutionTarget.PHONE || permission != PermissionLevel.SAFE) return null
        return when (toolName) {
            PHONE_BATTERY_STATUS_TOOL -> PhoneToolOperation(
                toolName = PHONE_BATTERY_STATUS_TOOL,
                acceptedMessage = "Battery status read accepted on this phone.",
                completedMessage = "BatteryManager returned validated local status.",
                failureMessage = "Battery status is unavailable on this phone",
                read = batteryStatusSource::read,
                validate = { content -> content is PhoneBatteryStatus && content.matchesToolContract() },
                verificationSummary = "Battery status matched the local tool contract.",
                verificationChecks = listOf(
                    "phone tool allowlist",
                    "battery percentage range",
                    "typed output",
                ),
            )
            PHONE_DEVICE_INFO_TOOL -> PhoneToolOperation(
                toolName = PHONE_DEVICE_INFO_TOOL,
                acceptedMessage = "Privacy-minimized device info read accepted on this phone.",
                completedMessage = "Android Build returned validated display information.",
                failureMessage = "Device information is unavailable on this phone",
                read = deviceInfoSource::read,
                validate = { content -> content is PhoneDeviceInfo && content.matchesToolContract() },
                verificationSummary = "Device information matched the privacy-minimized local contract.",
                verificationChecks = listOf(
                    "phone tool allowlist",
                    "approved display fields only",
                    "field bounds and control characters",
                    "minimum SDK contract",
                ),
            )
            else -> null
        }
    }

    private data class PhoneToolOperation(
        val toolName: String,
        val acceptedMessage: String,
        val completedMessage: String,
        val failureMessage: String,
        val read: suspend () -> ToolResultContent,
        val validate: (ToolResultContent) -> Boolean,
        val verificationSummary: String,
        val verificationChecks: List<String>,
    )

    private companion object {
        const val DEFAULT_TIMEOUT_MILLIS = 2_000L
    }
}
