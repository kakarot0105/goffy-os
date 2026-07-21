package dev.goffy.os.phone

import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.capability.PhoneCapabilityRegistry
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.ToolProgress
import dev.goffy.os.protocol.ToolArguments
import dev.goffy.os.protocol.ToolResultContent
import dev.goffy.os.protocol.matchesToolContract
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
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

fun interface TimerSource {
    suspend fun create(arguments: PhoneTimerCreateArguments): PhoneTimerDispatched
}

fun interface FlashlightSource {
    suspend fun set(arguments: PhoneFlashlightSetArguments): PhoneFlashlightState
}

interface NoteStore {
    suspend fun create(text: String): PhoneNoteCreated

    fun close()
}

sealed interface PhoneToolAuthorization {
    data object Safe : PhoneToolAuthorization

    class Approved internal constructor(
        private val taskId: UUID,
        private val toolName: String,
        private val arguments: ToolArguments,
        private val expiresAtEpochMillis: Long,
    ) : PhoneToolAuthorization {
        private val consumed = AtomicBoolean(false)

        internal fun consumeFor(
            taskId: UUID,
            toolName: String,
            arguments: ToolArguments,
            nowEpochMillis: Long,
        ): Boolean =
            this.taskId == taskId &&
                this.toolName == toolName &&
                this.arguments == arguments &&
                nowEpochMillis < expiresAtEpochMillis &&
                consumed.compareAndSet(false, true)
    }
}

interface PhoneToolGateway {
    fun invoke(
        taskId: UUID,
        plan: GoffyExecutionPlan,
        authorization: PhoneToolAuthorization,
    ): Flow<ExecutionEvent>

    fun close()
}

class DefaultPhoneToolGateway internal constructor(
    private val batteryStatusSource: BatteryStatusSource,
    private val deviceInfoSource: DeviceInfoSource,
    private val noteStore: NoteStore,
    private val timerSource: TimerSource,
    private val flashlightSource: FlashlightSource,
    private val readDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val actionDispatcher: CoroutineDispatcher = Dispatchers.Main.immediate,
    private val timeoutMillis: Long = DEFAULT_TIMEOUT_MILLIS,
    private val flashlightTimeoutMillis: Long = DEFAULT_FLASHLIGHT_TIMEOUT_MILLIS,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) : PhoneToolGateway {
    private val consumedConfirmTaskIds = ConcurrentHashMap.newKeySet<UUID>()
    private val capabilityRegistry = PhoneCapabilityRegistry.create(
        defaultTimeoutMillis = timeoutMillis,
        flashlightTimeoutMillis = flashlightTimeoutMillis,
    )

    init {
        require(timeoutMillis > 0) { "timeoutMillis must be positive" }
        require(flashlightTimeoutMillis > 0) { "flashlightTimeoutMillis must be positive" }
    }

    override fun invoke(
        taskId: UUID,
        plan: GoffyExecutionPlan,
        authorization: PhoneToolAuthorization,
    ): Flow<ExecutionEvent> = flow {
        val operation = plan.toAllowedOperation(taskId, authorization)
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
            withTimeout(operation.timeoutMillis) {
                withContext(operation.dispatcher) { operation.execute() }
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
        emit(operation.verification.toEvent())
    }

    override fun close() {
        consumedConfirmTaskIds.clear()
        noteStore.close()
    }

    private fun GoffyExecutionPlan.toAllowedOperation(
        taskId: UUID,
        authorization: PhoneToolAuthorization,
    ): PhoneToolOperation? {
        val capability = capabilityRegistry.match(
            toolName = toolName,
            executionTarget = executionTarget,
            permission = permission,
            arguments = arguments,
        ) ?: return null
        when (capability.metadata.permission) {
            PermissionLevel.SAFE -> {
                if (authorization != PhoneToolAuthorization.Safe) return null
            }
            PermissionLevel.CONFIRM -> {
                if (!consumeApproval(taskId, authorization)) return null
            }
            PermissionLevel.SENSITIVE,
            PermissionLevel.BLOCKED,
            -> return null
        }

        return when (toolName) {
            PHONE_BATTERY_STATUS_TOOL -> PhoneToolOperation(
                toolName = PHONE_BATTERY_STATUS_TOOL,
                acceptedMessage = "Battery status read accepted on this phone.",
                completedMessage = "BatteryManager returned validated local status.",
                failureMessage = "Battery status is unavailable on this phone",
                execute = batteryStatusSource::read,
                validate = { content -> content is PhoneBatteryStatus && content.matchesToolContract() },
                verification = PhoneToolVerification.Verified(
                    summary = "Battery status matched the local tool contract.",
                    checks = listOf(
                        "phone tool allowlist",
                        "battery percentage range",
                        "typed output",
                    ),
                ),
                dispatcher = readDispatcher,
                timeoutMillis = capability.metadata.timeoutMillis,
            )
            PHONE_DEVICE_INFO_TOOL -> PhoneToolOperation(
                toolName = PHONE_DEVICE_INFO_TOOL,
                acceptedMessage = "Privacy-minimized device info read accepted on this phone.",
                completedMessage = "Android Build returned validated display information.",
                failureMessage = "Device information is unavailable on this phone",
                execute = deviceInfoSource::read,
                validate = { content -> content is PhoneDeviceInfo && content.matchesToolContract() },
                verification = PhoneToolVerification.Verified(
                    summary = "Device information matched the privacy-minimized local contract.",
                    checks = listOf(
                        "phone tool allowlist",
                        "approved display/status fields only",
                        "field bounds and control characters",
                        "minimum SDK contract",
                    ),
                ),
                dispatcher = readDispatcher,
                timeoutMillis = capability.metadata.timeoutMillis,
            )
            PHONE_FLASHLIGHT_SET_TOOL -> {
                val flashlightArguments = arguments as? PhoneFlashlightSetArguments ?: return null
                val requestedState = if (flashlightArguments.enabled) "on" else "off"
                PhoneToolOperation(
                    toolName = PHONE_FLASHLIGHT_SET_TOOL,
                    acceptedMessage = "Approved flashlight $requestedState request accepted on this phone.",
                    completedMessage = "CameraManager reported the flashlight $requestedState.",
                    failureMessage = "The back-camera flashlight could not be set and verified",
                    execute = { flashlightSource.set(flashlightArguments) },
                    validate = { content ->
                        content is PhoneFlashlightState &&
                            content.enabled == flashlightArguments.enabled
                    },
                    verification = PhoneToolVerification.Verified(
                        summary = "TorchCallback confirmed the approved flashlight state.",
                        checks = listOf(
                            "single-use approval",
                            "back-facing flash selection",
                            "exact enabled-state match",
                            "CameraManager callback",
                            "callback cleanup",
                        ),
                    ),
                    dispatcher = actionDispatcher,
                    timeoutMillis = capability.metadata.timeoutMillis,
                )
            }
            PHONE_NOTE_CREATE_TOOL -> {
                val noteArguments = arguments as? PhoneNoteCreateArguments ?: return null
                PhoneToolOperation(
                    toolName = PHONE_NOTE_CREATE_TOOL,
                    acceptedMessage = "Approved note creation accepted on this phone.",
                    completedMessage = "The app-private note row was written and re-read.",
                    failureMessage = "The note could not be stored and verified",
                    execute = { noteStore.create(noteArguments.text) },
                    validate = { content ->
                        content is PhoneNoteCreated &&
                            content.text == noteArguments.text &&
                            content.matchesToolContract()
                    },
                    verification = PhoneToolVerification.Verified(
                        summary = "The approved note was stored and re-read successfully.",
                        checks = listOf(
                            "single-use approval",
                            "app-private database",
                            "exact text match",
                            "post-write row read",
                        ),
                    ),
                    dispatcher = readDispatcher,
                    timeoutMillis = capability.metadata.timeoutMillis,
                )
            }
            PHONE_TIMER_CREATE_TOOL -> {
                val timerArguments = arguments as? PhoneTimerCreateArguments ?: return null
                PhoneToolOperation(
                    toolName = PHONE_TIMER_CREATE_TOOL,
                    acceptedMessage = "Approved timer creation accepted on this phone.",
                    completedMessage = "The timer intent was sent to an allowlisted system Clock.",
                    failureMessage = "An allowlisted system Clock timer could not be started",
                    execute = { timerSource.create(timerArguments) },
                    validate = { content ->
                        content is PhoneTimerDispatched &&
                            content.durationSeconds == timerArguments.durationSeconds &&
                            content.skipClockUiRequested == timerArguments.skipClockUi &&
                            content.matchesToolContract()
                    },
                    verification = PhoneToolVerification.Unverified(
                        summary = "Timer intent dispatched, but Clock timer state is not readable by GOFFY.",
                        checks = listOf(
                            "single-use approval",
                            "exact requested duration",
                            "explicit allowlisted Clock component",
                            "documented system timer action",
                            "Clock postcondition unavailable",
                        ),
                    ),
                    dispatcher = actionDispatcher,
                    timeoutMillis = capability.metadata.timeoutMillis,
                )
            }
            else -> null
        }
    }

    private fun GoffyExecutionPlan.consumeApproval(
        taskId: UUID,
        authorization: PhoneToolAuthorization,
    ): Boolean {
        val approved = authorization as? PhoneToolAuthorization.Approved ?: return false
        return approved.consumeFor(taskId, toolName, arguments, nowMillis()) &&
            consumedConfirmTaskIds.add(taskId)
    }

    private data class PhoneToolOperation(
        val toolName: String,
        val acceptedMessage: String,
        val completedMessage: String,
        val failureMessage: String,
        val execute: suspend () -> ToolResultContent,
        val validate: (ToolResultContent) -> Boolean,
        val verification: PhoneToolVerification,
        val dispatcher: CoroutineDispatcher,
        val timeoutMillis: Long,
    )

    private sealed interface PhoneToolVerification {
        val summary: String
        val checks: List<String>

        data class Verified(
            override val summary: String,
            override val checks: List<String>,
        ) : PhoneToolVerification

        data class Unverified(
            override val summary: String,
            override val checks: List<String>,
        ) : PhoneToolVerification

        fun toEvent(): ExecutionEvent = when (this) {
            is Verified -> ExecutionEvent.Verification(true, summary, checks)
            is Unverified -> ExecutionEvent.Unverified(summary, checks)
        }
    }

    private companion object {
        const val DEFAULT_TIMEOUT_MILLIS = 2_000L
        const val DEFAULT_FLASHLIGHT_TIMEOUT_MILLIS = 3_000L
    }
}
