package dev.goffy.os

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.goffy.os.agent.GoffyExecutionPlan
import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.hub.HubConfig
import dev.goffy.os.hub.HubConfigurationException
import dev.goffy.os.hub.HubGateway
import dev.goffy.os.hub.OkHttpHubGateway
import dev.goffy.os.phone.AndroidBatteryStatusSource
import dev.goffy.os.phone.AndroidDeviceInfoSource
import dev.goffy.os.phone.DefaultPhoneToolGateway
import dev.goffy.os.phone.PhoneToolGateway
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GoffyProtocolCodec
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class GoffyViewModel internal constructor(
    private val gateway: HubGateway,
    private val phoneGateway: PhoneToolGateway,
    private val codec: GoffyProtocolCodec,
    private val allowInsecureLoopback: Boolean,
    private val defaultEndpoint: String,
    private val deviceId: String,
    private val nextTaskId: () -> UUID,
) : ViewModel() {
    constructor(context: Context) : this(
        gateway = OkHttpHubGateway(),
        phoneGateway = DefaultPhoneToolGateway(
            batteryStatusSource = AndroidBatteryStatusSource(context),
            deviceInfoSource = AndroidDeviceInfoSource(),
        ),
        codec = GoffyProtocolCodec(),
        allowInsecureLoopback = BuildConfig.DEBUG,
        defaultEndpoint = if (BuildConfig.DEBUG) DEBUG_HUB_ENDPOINT else RELEASE_HUB_ENDPOINT_HINT,
        deviceId = "goffy-android-${UUID.randomUUID()}",
        nextTaskId = UUID::randomUUID,
    )

    private val mutableUiState = MutableStateFlow(GoffyUiState(hubEndpoint = defaultEndpoint))
    val uiState: StateFlow<GoffyUiState> = mutableUiState.asStateFlow()

    private var hubConfig: HubConfig? = null
    private var activeJob: Job? = null

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
        mutableUiState.value = mutableUiState.value.forgetHub(defaultEndpoint)
    }

    fun submitCommand(command: String) {
        if (mutableUiState.value.isBusy) {
            mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "Another task is already running; cancel it before submitting a new command",
            )
            return
        }
        val decision = GoffyIntentRouter.route(command)
        if (decision is RoutingDecision.Unsupported) {
            mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "No safe deterministic route is available for this command yet",
            )
            return
        }

        val plan = (decision as RoutingDecision.Routed).plan
        when (plan.executionTarget) {
            ExecutionTarget.PHONE -> {
                val taskId = nextTaskId()
                executeTask(taskId, plan, phoneGateway.invoke(plan))
            }
            ExecutionTarget.MAC -> {
                val config = hubConfig
                if (config == null) {
                    mutableUiState.value = mutableUiState.value.rejectCommand(
                        command,
                        "Configure a secure GOFFY Hub link before running a Mac task",
                    )
                    return
                }
                val request = codec.createToolInvocation(deviceId, plan.toolName)
                executeTask(request.messageId, plan, gateway.invoke(config, request))
            }
            ExecutionTarget.CLOUD -> mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "Cloud execution is not available in this build",
            )
        }
    }

    private fun executeTask(
        taskId: UUID,
        plan: GoffyExecutionPlan,
        events: Flow<ExecutionEvent>,
    ) {
        mutableUiState.value = mutableUiState.value.startTask(taskId, plan)
        val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
            try {
                events.collect { event ->
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(taskId, event)
                }
                if (mutableUiState.value.timeline.activeTaskId == taskId) {
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(
                        taskId,
                        ExecutionEvent.Error(
                            code = "execution_stopped",
                            message = "Execution stopped before verification",
                            retryable = false,
                        ),
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
        activeJob?.cancel()
        activeJob = null
        mutableUiState.value = mutableUiState.value.cancelActiveTask()
    }

    override fun onCleared() {
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
    }
}
