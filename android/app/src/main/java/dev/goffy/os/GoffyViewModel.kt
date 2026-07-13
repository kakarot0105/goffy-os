package dev.goffy.os

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.audit.AndroidSqliteTerminalAuditStore
import dev.goffy.os.audit.ClosedTerminalAuditLoadResult
import dev.goffy.os.audit.ClosedTerminalAuditRecord
import dev.goffy.os.audit.TerminalAuditStore
import dev.goffy.os.audit.toClosedTerminalAuditRecord
import dev.goffy.os.hub.HubConfig
import dev.goffy.os.hub.HubConfigurationException
import dev.goffy.os.hub.HubGateway
import dev.goffy.os.hub.OkHttpHubGateway
import dev.goffy.os.phone.AndroidBatteryStatusSource
import dev.goffy.os.phone.AndroidDeviceInfoSource
import dev.goffy.os.phone.AndroidFlashlightSource
import dev.goffy.os.phone.AndroidSqliteNoteStore
import dev.goffy.os.phone.AndroidSystemTimerSource
import dev.goffy.os.phone.DefaultPhoneToolGateway
import dev.goffy.os.phone.PhoneToolGateway
import dev.goffy.os.phone.PhoneToolAuthorization
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.PermissionLevel
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class GoffyViewModel internal constructor(
    private val gateway: HubGateway,
    private val phoneGateway: PhoneToolGateway,
    private val codec: GoffyProtocolCodec,
    private val allowInsecureLoopback: Boolean,
    private val defaultEndpoint: String,
    private val deviceId: String,
    private val nextTaskId: () -> UUID,
    private val approvalTtlMillis: Long = DEFAULT_APPROVAL_TTL_MILLIS,
    private val nowMillis: () -> Long = System::currentTimeMillis,
    private val auditStore: TerminalAuditStore = NoOpTerminalAuditStore,
    private val auditDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    constructor(context: Context) : this(
        gateway = OkHttpHubGateway(),
        phoneGateway = DefaultPhoneToolGateway(
            batteryStatusSource = AndroidBatteryStatusSource(context),
            deviceInfoSource = AndroidDeviceInfoSource(),
            noteStore = AndroidSqliteNoteStore(context),
            timerSource = AndroidSystemTimerSource(context),
            flashlightSource = AndroidFlashlightSource(context),
        ),
        codec = GoffyProtocolCodec(),
        allowInsecureLoopback = BuildConfig.DEBUG,
        defaultEndpoint = if (BuildConfig.DEBUG) DEBUG_HUB_ENDPOINT else RELEASE_HUB_ENDPOINT_HINT,
        deviceId = "goffy-android-${UUID.randomUUID()}",
        nextTaskId = UUID::randomUUID,
        auditStore = AndroidSqliteTerminalAuditStore(context),
    )

    private val mutableUiState = MutableStateFlow(GoffyUiState(hubEndpoint = defaultEndpoint))
    val uiState: StateFlow<GoffyUiState> = mutableUiState.asStateFlow()

    private var hubConfig: HubConfig? = null
    private var activeJob: Job? = null
    private var pendingExecution: PendingPhoneExecution? = null
    private var approvalExpiryJob: Job? = null

    init {
        require(approvalTtlMillis > 0) { "approvalTtlMillis must be positive" }
        observeTerminalAudit()
    }

    private fun observeTerminalAudit() {
        viewModelScope.launch {
            val attemptedTaskIds = mutableSetOf<UUID>()
            try {
                val loaded = withContext(auditDispatcher) { auditStore.load() }
                attemptedTaskIds += loaded.records.map(ClosedTerminalAuditRecord::taskId)
                mutableUiState.value = mutableUiState.value.auditLoaded(
                    restoredEntries = loaded.records.map(ClosedTerminalAuditRecord::toTimelineEntry),
                    discardedRecords = loaded.discardedCorruptRows,
                )
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.auditFailed()
            }

            mutableUiState.map { it.timeline.entries }.collect { entries ->
                entries.forEach { entry ->
                    if (entry.id in attemptedTaskIds) return@forEach
                    val terminalAt = entry.terminalAtEpochMillis ?: return@forEach
                    attemptedTaskIds += entry.id
                    try {
                        val record = checkNotNull(entry.toClosedTerminalAuditRecord(terminalAt)) {
                            "only terminal entries may carry terminal timestamps"
                        }
                        val stored = withContext(auditDispatcher) { auditStore.upsert(record) }
                        mutableUiState.value = mutableUiState.value.auditRecorded(
                            stored.taskId,
                            stored.recordedAtEpochMillis,
                        )
                    } catch (error: CancellationException) {
                        throw error
                    } catch (_: Exception) {
                        mutableUiState.value = mutableUiState.value.auditFailed()
                    }
                }
            }
        }
    }

    fun configureHub(endpoint: String, bearerToken: String): Boolean {
        val config = try {
            HubConfig.create(endpoint, bearerToken, allowInsecureLoopback)
        } catch (error: HubConfigurationException) {
            hubConfig = null
            mutableUiState.value = mutableUiState.value.hubConfigurationRejected(
                error.message ?: "Hub configuration is invalid",
            )
            return false
        }
        hubConfig = config
        mutableUiState.value = mutableUiState.value.hubConfigured(config.endpoint)
        return true
    }

    fun forgetHub() {
        cancelActiveTask()
        hubConfig = null
        mutableUiState.value = mutableUiState.value.forgetHub(defaultEndpoint, nowMillis())
    }

    fun submitCommand(command: String) {
        if (mutableUiState.value.isBusy) {
            mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "Another task is already running; cancel it before submitting a new command",
                nowMillis(),
            )
            return
        }
        val decision = GoffyIntentRouter.route(command)
        if (decision is RoutingDecision.Unsupported) {
            mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "No safe deterministic route is available for this command yet",
                nowMillis(),
            )
            return
        }

        val plan = (decision as RoutingDecision.Routed).plan
        when (plan.executionTarget) {
            ExecutionTarget.PHONE -> submitPhonePlan(plan)
            ExecutionTarget.MAC -> {
                val config = hubConfig
                if (config == null) {
                    mutableUiState.value = mutableUiState.value.rejectPlan(
                        plan,
                        "Configure a secure GOFFY Hub link before running a Mac task",
                        nowMillis(),
                    )
                    return
                }
                val request = codec.createToolInvocation(deviceId, plan.toolName)
                executeTask(request.messageId, plan, gateway.invoke(config, request))
            }
            ExecutionTarget.CLOUD -> mutableUiState.value = mutableUiState.value.rejectPlan(
                plan,
                "Cloud execution is not available in this build",
                nowMillis(),
            )
        }
    }

    private fun submitPhonePlan(plan: GoffyExecutionPlan) {
        val taskId = nextTaskId()
        when (plan.permission) {
            PermissionLevel.SAFE -> executeTask(
                taskId,
                plan,
                phoneGateway.invoke(taskId, plan, PhoneToolAuthorization.Safe),
            )
            PermissionLevel.CONFIRM -> requestPhoneApproval(taskId, plan)
            PermissionLevel.SENSITIVE,
            PermissionLevel.BLOCKED,
            -> mutableUiState.value = mutableUiState.value.rejectPlan(
                plan,
                "This phone action is blocked in the current security policy",
                nowMillis(),
            )
        }
    }

    private fun requestPhoneApproval(taskId: UUID, plan: GoffyExecutionPlan) {
        val description = plan.approvalDescription()
        if (description == null) {
            mutableUiState.value = mutableUiState.value.rejectPlan(
                plan,
                "The confirmation request did not match a typed phone tool",
                nowMillis(),
            )
            return
        }
        val expiresAt = nowMillis() + approvalTtlMillis
        val approval = PendingApproval(
            taskId = taskId,
            toolName = plan.toolName,
            description = description,
            expiresAtEpochMillis = expiresAt,
            durationSeconds = (approvalTtlMillis + 999L) / 1_000L,
        )
        mutableUiState.value = mutableUiState.value
            .startTask(taskId, plan)
            .awaitApproval(approval, nowMillis())
        pendingExecution = PendingPhoneExecution(taskId, plan, expiresAt)
        approvalExpiryJob = viewModelScope.launch {
            delay(approvalTtlMillis)
            expirePendingApproval(taskId)
        }
    }

    private fun GoffyExecutionPlan.approvalDescription(): String? = when (val value = arguments) {
        is PhoneNoteCreateArguments ->
            "Approve creating this private note: ${value.text.take(APPROVAL_PREVIEW_LENGTH)}"
        is PhoneTimerCreateArguments ->
            "Approve requesting a ${value.durationSeconds.displayDuration()} system Clock timer. " +
                "GOFFY will request no second Clock confirmation screen."
        is PhoneFlashlightSetArguments ->
            "Approve turning ${if (value.enabled) "on" else "off"} the back-camera flashlight. " +
                "GOFFY will not open the camera or capture images."
        else -> null
    }

    private fun Int.displayDuration(): String = when {
        this % 3_600 == 0 -> "${this / 3_600} ${if (this == 3_600) "hour" else "hours"}"
        this % 60 == 0 -> "${this / 60} ${if (this == 60) "minute" else "minutes"}"
        else -> "$this ${if (this == 1) "second" else "seconds"}"
    }

    fun approvePendingTask(taskId: UUID): Boolean {
        val pending = pendingExecution ?: return false
        if (pending.taskId != taskId) return false
        if (nowMillis() >= pending.expiresAtEpochMillis) {
            expirePendingApproval(taskId)
            return false
        }
        pendingExecution = null
        approvalExpiryJob?.cancel()
        approvalExpiryJob = null
        mutableUiState.value = mutableUiState.value.grantApproval(taskId, nowMillis())
        collectTask(
            taskId,
            phoneGateway.invoke(
                taskId,
                pending.plan,
                PhoneToolAuthorization.Approved(
                    taskId,
                    pending.plan.toolName,
                    pending.plan.arguments,
                    pending.expiresAtEpochMillis,
                ),
            ),
        )
        return true
    }

    fun denyPendingTask(taskId: UUID): Boolean {
        val pending = pendingExecution ?: return false
        if (pending.taskId != taskId) return false
        pendingExecution = null
        approvalExpiryJob?.cancel()
        approvalExpiryJob = null
        mutableUiState.value = mutableUiState.value.denyApproval(
            taskId,
            "Approval denied; no phone tool was invoked",
            nowMillis(),
        )
        return true
    }

    private fun expirePendingApproval(taskId: UUID) {
        val pending = pendingExecution ?: return
        if (pending.taskId != taskId) return
        pendingExecution = null
        approvalExpiryJob = null
        mutableUiState.value = mutableUiState.value.expireApproval(taskId, nowMillis())
    }

    private fun executeTask(
        taskId: UUID,
        plan: GoffyExecutionPlan,
        events: Flow<ExecutionEvent>,
    ) {
        mutableUiState.value = mutableUiState.value.startTask(taskId, plan)
        collectTask(taskId, events)
    }

    private fun collectTask(
        taskId: UUID,
        events: Flow<ExecutionEvent>,
    ) {
        val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
            try {
                events.collect { event ->
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(
                        taskId,
                        event,
                        nowMillis(),
                    )
                }
                if (mutableUiState.value.timeline.activeTaskId == taskId) {
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(
                        taskId,
                        ExecutionEvent.Error(
                            code = "execution_stopped",
                            message = "Execution stopped before verification",
                            retryable = false,
                        ),
                        nowMillis(),
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.applyTaskEvent(
                    taskId,
                    ExecutionEvent.Error(
                        code = "client_failure",
                        message = "The Android execution client stopped before verification",
                        retryable = false,
                    ),
                    nowMillis(),
                )
            } finally {
                if (activeJob === coroutineContext[Job]) {
                    activeJob = null
                }
            }
        }
        activeJob = job
        job.start()
    }

    fun cancelActiveTask() {
        val pending = pendingExecution
        if (pending != null) {
            pendingExecution = null
            approvalExpiryJob?.cancel()
            approvalExpiryJob = null
            mutableUiState.value = mutableUiState.value.denyApproval(
                pending.taskId,
                "Approval cancelled; no phone tool was invoked",
                nowMillis(),
            )
            return
        }
        activeJob?.cancel()
        activeJob = null
        mutableUiState.value = mutableUiState.value.cancelActiveTask(nowMillis())
    }

    override fun onCleared() {
        approvalExpiryJob?.cancel()
        auditStore.close()
        phoneGateway.close()
        gateway.close()
        super.onCleared()
    }

    class Factory(context: Context) : ViewModelProvider.Factory {
        private val applicationContext = context.applicationContext

        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(GoffyViewModel::class.java)) {
                "Unsupported ViewModel class"
            }
            @Suppress("UNCHECKED_CAST")
            return GoffyViewModel(applicationContext) as T
        }
    }

    private companion object {
        const val DEBUG_HUB_ENDPOINT = "ws://127.0.0.1:8787/ws/v1"
        const val RELEASE_HUB_ENDPOINT_HINT = "wss://your-mac.example:8787/ws/v1"
        const val DEFAULT_APPROVAL_TTL_MILLIS = 60_000L
        const val APPROVAL_PREVIEW_LENGTH = 160
    }

    private data class PendingPhoneExecution(
        val taskId: UUID,
        val plan: GoffyExecutionPlan,
        val expiresAtEpochMillis: Long,
    )

    private object NoOpTerminalAuditStore : TerminalAuditStore {
        override suspend fun load() = ClosedTerminalAuditLoadResult(emptyList(), 0)

        override suspend fun upsert(record: ClosedTerminalAuditRecord) = record

        override fun close() = Unit
    }
}
