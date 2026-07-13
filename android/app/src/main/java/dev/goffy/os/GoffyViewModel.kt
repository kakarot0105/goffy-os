package dev.goffy.os

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dev.goffy.os.agent.GoffyIntentRouter
import dev.goffy.os.agent.RoutingDecision
import dev.goffy.os.hub.HubConfig
import dev.goffy.os.hub.HubConfigurationException
import dev.goffy.os.hub.HubGateway
import dev.goffy.os.hub.OkHttpHubGateway
import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.HubStreamEvent
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class GoffyViewModel internal constructor(
    private val gateway: HubGateway,
    private val codec: GoffyProtocolCodec,
    private val allowInsecureLoopback: Boolean,
    private val defaultEndpoint: String,
    private val deviceId: String,
) : ViewModel() {
    constructor() : this(
        gateway = OkHttpHubGateway(),
        codec = GoffyProtocolCodec(),
        allowInsecureLoopback = BuildConfig.DEBUG,
        defaultEndpoint = if (BuildConfig.DEBUG) DEBUG_HUB_ENDPOINT else RELEASE_HUB_ENDPOINT_HINT,
        deviceId = "goffy-android-${UUID.randomUUID()}",
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

        val config = hubConfig
        if (config == null) {
            mutableUiState.value = mutableUiState.value.rejectCommand(
                command,
                "Configure a secure GOFFY Hub link before running a Mac task",
            )
            return
        }

        val plan = (decision as RoutingDecision.Routed).plan
        val request = codec.createToolInvocation(deviceId, plan.toolName)
        mutableUiState.value = mutableUiState.value.startTask(request.messageId, plan)
        val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
            try {
                gateway.invoke(config, request).collect { event ->
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(request.messageId, event)
                }
                if (mutableUiState.value.timeline.activeTaskId == request.messageId) {
                    mutableUiState.value = mutableUiState.value.applyTaskEvent(
                        request.messageId,
                        HubStreamEvent.Error(
                            code = "connection_closed",
                            message = "Hub connection closed before verification",
                            retryable = false,
                        ),
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutableUiState.value = mutableUiState.value.applyTaskEvent(
                    request.messageId,
                    HubStreamEvent.Error(
                        code = "client_failure",
                        message = "The Android client stopped before verification",
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
        gateway.close()
        super.onCleared()
    }

    private companion object {
        const val DEBUG_HUB_ENDPOINT = "ws://127.0.0.1:8787/ws/v1"
        const val RELEASE_HUB_ENDPOINT_HINT = "wss://your-mac.example:8787/ws/v1"
    }
}
