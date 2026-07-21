package dev.goffy.os.hub

import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.CapabilityDiscoveryMessage
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ProtocolException
import dev.goffy.os.protocol.ToolInvocationRequest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.resume
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString

class OkHttpHubGateway private constructor(
    private val client: OkHttpClient,
    private val codec: GoffyProtocolCodec,
    private val ownsClient: Boolean,
    private val attemptTimeoutMillis: Long,
    private val timeoutDispatcher: CoroutineDispatcher,
    private val nowMillis: () -> Long,
) : HubGateway {
    constructor() : this(
        defaultClient(),
        GoffyProtocolCodec(),
        ownsClient = true,
        attemptTimeoutMillis = DEFAULT_ATTEMPT_TIMEOUT_MILLIS,
        timeoutDispatcher = Dispatchers.IO,
        nowMillis = System::currentTimeMillis,
    )

    internal constructor(
        client: OkHttpClient,
        codec: GoffyProtocolCodec = GoffyProtocolCodec(),
        attemptTimeoutMillis: Long = DEFAULT_ATTEMPT_TIMEOUT_MILLIS,
        timeoutDispatcher: CoroutineDispatcher = Dispatchers.IO,
        nowMillis: () -> Long = System::currentTimeMillis,
    ) : this(
        client,
        codec,
        ownsClient = false,
        attemptTimeoutMillis = attemptTimeoutMillis,
        timeoutDispatcher = timeoutDispatcher,
        nowMillis = nowMillis,
    )

    init {
        require(attemptTimeoutMillis > 0) { "attemptTimeoutMillis must be positive" }
    }

    private val closed = AtomicBoolean(false)
    private val activeSockets = ConcurrentHashMap.newKeySet<WebSocket>()

    override fun invoke(config: HubConfig, request: ToolInvocationRequest): Flow<ExecutionEvent> {
        if (closed.get()) {
            return flowOf(
                ExecutionEvent.Error(
                    code = "gateway_closed",
                    message = "Hub transport is closed.",
                    retryable = true,
                ),
            )
        }

        return callbackFlow {
            val invocationSocket = AtomicReference<WebSocket?>(null)
            val driver = launch {
                try {
                    runInvocation(config, request, invocationSocket) { event ->
                        trySend(event)
                    }
                } finally {
                    channel.close()
                }
            }

            awaitClose {
                driver.cancel()
                invocationSocket.getAndSet(null)?.cancel()
            }
        }
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) {
            return
        }

        activeSockets.toList().forEach { socket -> socket.cancel() }
        if (ownsClient) {
            client.dispatcher.cancelAll()
            client.dispatcher.executorService.shutdown()
            client.connectionPool.evictAll()
            client.cache?.close()
        }
    }

    private suspend fun runInvocation(
        config: HubConfig,
        request: ToolInvocationRequest,
        invocationSocket: AtomicReference<WebSocket?>,
        emit: (ExecutionEvent) -> Unit,
    ) {
        var attempt = 1

        while (attempt <= MAX_ATTEMPTS && !closed.get()) {
            if (request.isExpired()) {
                emit(approvalExpiredError())
                return
            }
            emit(ExecutionEvent.Starting(attempt))

            val outcome = withContext(timeoutDispatcher) {
                withTimeoutOrNull(attemptTimeoutMillis) {
                    performAttempt(
                        config = config,
                        request = request,
                        invocationSocket = invocationSocket,
                        emit = emit,
                    )
                }
            } ?: AttemptOutcome.FinalFailure(
                terminalError(
                    code = "hub_response_timeout",
                    message = "Hub discovery or execution exceeded the bounded response window.",
                ),
            )
            when (outcome) {
                AttemptOutcome.Completed -> return
                is AttemptOutcome.FinalFailure -> {
                    emit(outcome.event)
                    return
                }
                is AttemptOutcome.RetryableFailure -> {
                    if (attempt == MAX_ATTEMPTS) {
                        emit(outcome.event)
                        return
                    }
                }
            }

            attempt += 1
        }

        if (!closed.get()) {
            emit(retryableError("transport_connect_failed", "Hub connection failed before the request was sent."))
        }
    }

    private suspend fun performAttempt(
        config: HubConfig,
        request: ToolInvocationRequest,
        invocationSocket: AtomicReference<WebSocket?>,
        emit: (ExecutionEvent) -> Unit,
    ): AttemptOutcome = suspendCancellableCoroutine { continuation ->
        val discoverySent = AtomicBoolean(false)
        val invocationSent = AtomicBoolean(false)
        val terminalEventReceived = AtomicBoolean(false)
        val closingOutcome = AtomicReference<AttemptOutcome?>(null)
        val finished = AtomicBoolean(false)
        val socketRef = AtomicReference<WebSocket?>(null)

        fun cleanup(socket: WebSocket?) {
            if (socket == null) {
                return
            }
            activeSockets.remove(socket)
            invocationSocket.compareAndSet(socket, null)
        }

        fun clearTrackedSocket() {
            val socket = socketRef.getAndSet(null)
            cleanup(socket)
        }

        fun finish(outcome: AttemptOutcome) {
            if (!finished.compareAndSet(false, true)) {
                return
            }
            clearTrackedSocket()
            if (continuation.isActive) {
                continuation.resume(outcome)
            }
        }

        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (request.isExpired()) {
                    closeWithOutcome(
                        webSocket = webSocket,
                        status = NORMAL_CLOSURE_STATUS,
                        outcome = AttemptOutcome.FinalFailure(approvalExpiredError()),
                        closingOutcome = closingOutcome,
                        finish = ::finish,
                    )
                    return
                }
                discoverySent.set(true)
                if (!webSocket.send(request.encodedDiscoveryMessage)) {
                    discoverySent.set(false)
                    closeWithOutcome(
                        webSocket = webSocket,
                        status = NORMAL_CLOSURE_STATUS,
                        outcome = AttemptOutcome.RetryableFailure(
                            retryableError(
                                code = "transport_send_failed",
                                message = "Hub capability discovery could not be sent.",
                            ),
                        ),
                        closingOutcome = closingOutcome,
                        finish = ::finish,
                    )
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (!invocationSent.get()) {
                    val discovery = try {
                        codec.decodeCapabilityDiscovery(
                            rawMessage = text,
                            expectedCorrelationId = request.discoveryMessageId,
                            expectedToolName = request.toolName,
                        )
                    } catch (_: ProtocolException) {
                        closeWithProtocolFailure(
                            webSocket = webSocket,
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }

                    val failure = when (discovery) {
                        is CapabilityDiscoveryMessage.Error -> discovery.event
                        is CapabilityDiscoveryMessage.Response ->
                            if (discovery.capability == null) {
                                terminalError(
                                    code = "capability_unavailable",
                                    message = "The required Hub capability is unavailable.",
                                )
                            } else {
                                null
                            }
                    }
                    if (failure != null) {
                        closeWithOutcome(
                            webSocket = webSocket,
                            status = NORMAL_CLOSURE_STATUS,
                            outcome = AttemptOutcome.FinalFailure(failure),
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }

                    if (request.isExpired()) {
                        closeWithOutcome(
                            webSocket = webSocket,
                            status = NORMAL_CLOSURE_STATUS,
                            outcome = AttemptOutcome.FinalFailure(approvalExpiredError()),
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }
                    invocationSent.set(true)
                    if (webSocket.send(request.encodedMessage)) {
                        emit(ExecutionEvent.Ready)
                    } else {
                        invocationSent.set(false)
                        closeWithOutcome(
                            webSocket = webSocket,
                            status = NORMAL_CLOSURE_STATUS,
                            outcome = AttemptOutcome.RetryableFailure(
                                retryableError(
                                    code = "transport_send_failed",
                                    message = "Hub request could not be sent.",
                                ),
                            ),
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                    }
                    return
                }

                val approvalRequest = try {
                    codec.decodeApprovalRequestOrNull(
                        rawMessage = text,
                        expectedCorrelationId = request.messageId,
                        expectedToolName = request.toolName,
                        expectedTaskId = request.approvedTaskId,
                        expectedArgumentsSha256 = request.approvedArgumentsSha256,
                    )
                } catch (_: ProtocolException) {
                    closeWithProtocolFailure(
                        webSocket = webSocket,
                        closingOutcome = closingOutcome,
                        finish = ::finish,
                    )
                    return
                }
                if (approvalRequest != null) {
                    val now = nowMillis()
                    if (request.isExpired() || now >= approvalRequest.expiresAtEpochMillis) {
                        closeWithOutcome(
                            webSocket = webSocket,
                            status = NORMAL_CLOSURE_STATUS,
                            outcome = AttemptOutcome.FinalFailure(approvalExpiredError()),
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }
                    val localDeadline = request.expiresAtEpochMillis
                    if (
                        localDeadline != null &&
                        approvalRequest.expiresAtEpochMillis > localDeadline
                    ) {
                        closeWithProtocolFailure(
                            webSocket = webSocket,
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }
                    if (approvalRequest.issuedAtEpochMillis > now + APPROVAL_CLOCK_SKEW_MILLIS) {
                        closeWithProtocolFailure(
                            webSocket = webSocket,
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }
                    val approvalResponse = try {
                        codec.createApprovalResponse(
                            deviceId = request.deviceId,
                            correlationId = request.messageId,
                            approvalRequest = approvalRequest,
                        )
                    } catch (_: ProtocolException) {
                        closeWithProtocolFailure(
                            webSocket = webSocket,
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                        return
                    }
                    if (!webSocket.send(approvalResponse)) {
                        closeWithOutcome(
                            webSocket = webSocket,
                            status = NORMAL_CLOSURE_STATUS,
                            outcome = AttemptOutcome.RetryableFailure(
                                retryableError(
                                    code = "transport_send_failed",
                                    message = "Hub approval response could not be sent.",
                                ),
                            ),
                            closingOutcome = closingOutcome,
                            finish = ::finish,
                        )
                    }
                    return
                }

                val event = try {
                    codec.decodeEvent(
                        rawMessage = text,
                        expectedCorrelationId = request.messageId,
                        expectedToolName = request.toolName,
                    )
                } catch (_: ProtocolException) {
                    closeWithProtocolFailure(
                        webSocket = webSocket,
                        closingOutcome = closingOutcome,
                        finish = ::finish,
                    )
                    return
                }

                emit(event)
                if (event is ExecutionEvent.Verification || event is ExecutionEvent.Error) {
                    terminalEventReceived.set(true)
                    if (!webSocket.close(NORMAL_CLOSURE_STATUS, null)) {
                        finish(AttemptOutcome.Completed)
                    }
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                closeWithProtocolFailure(
                    webSocket = webSocket,
                    closingOutcome = closingOutcome,
                    finish = ::finish,
                )
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                when {
                    closingOutcome.get() != null -> finish(checkNotNull(closingOutcome.get()))
                    terminalEventReceived.get() -> finish(AttemptOutcome.Completed)
                    !invocationSent.get() -> finish(
                        AttemptOutcome.RetryableFailure(
                            retryableError(
                                code = "transport_connect_failed",
                                message = if (discoverySent.get()) {
                                    "Hub connection closed before the request was sent."
                                } else {
                                    "Hub connection closed before capability discovery was sent."
                                },
                            ),
                        ),
                    )
                    else -> finish(
                        AttemptOutcome.FinalFailure(
                            terminalError(
                                code = "transport_disconnected",
                                message = "Hub connection closed before a terminal event was received.",
                            ),
                        ),
                    )
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                response?.close()

                val outcome = when {
                    closingOutcome.get() != null -> checkNotNull(closingOutcome.get())
                    terminalEventReceived.get() -> AttemptOutcome.Completed
                    response != null && (response.code == HTTP_UNAUTHORIZED || response.code == HTTP_FORBIDDEN) -> {
                        AttemptOutcome.FinalFailure(
                            terminalError(
                                code = "authentication_failed",
                                message = "Hub authentication failed.",
                            ),
                        )
                    }
                    response != null -> {
                        AttemptOutcome.FinalFailure(
                            terminalError(
                                code = "upgrade_rejected",
                                message = "Hub rejected the WebSocket upgrade.",
                            ),
                        )
                    }
                    !invocationSent.get() -> {
                        AttemptOutcome.RetryableFailure(
                            retryableError(
                                code = "transport_connect_failed",
                                message = "Hub connection failed before the request was sent.",
                            ),
                        )
                    }
                    else -> {
                        AttemptOutcome.FinalFailure(
                            terminalError(
                                code = "transport_disconnected",
                                message = "Hub connection was lost before a terminal event was received.",
                            ),
                        )
                    }
                }

                finish(outcome)
            }
        }

        val callRequest = Request.Builder()
            .url(config.endpoint)
            .header("Authorization", config.authorizationHeaderValue)
            .build()

        try {
            val socket = client.newWebSocket(callRequest, listener)
            socketRef.set(socket)
            invocationSocket.set(socket)
            activeSockets.add(socket)
        } catch (_: IllegalStateException) {
            finish(
                AttemptOutcome.FinalFailure(
                    terminalError(
                        code = "gateway_closed",
                        message = "Hub transport is closed.",
                    ),
                ),
            )
        } catch (_: RuntimeException) {
            finish(
                AttemptOutcome.RetryableFailure(
                    retryableError(
                        code = "transport_connect_failed",
                        message = "Hub connection failed before the request was sent.",
                    ),
                ),
            )
        }

        continuation.invokeOnCancellation {
            val socket = socketRef.getAndSet(null)
            cleanup(socket)
            socket?.cancel()
        }
    }

    private fun ToolInvocationRequest.isExpired(): Boolean {
        val deadline = expiresAtEpochMillis ?: return false
        return nowMillis() >= deadline
    }

    private fun approvalExpiredError(): ExecutionEvent.Error =
        ExecutionEvent.Error(
            code = "approval_expired",
            message = "The approved action expired before it could be sent.",
            retryable = false,
        )

    private sealed interface AttemptOutcome {
        data object Completed : AttemptOutcome

        data class RetryableFailure(val event: ExecutionEvent.Error) : AttemptOutcome

        data class FinalFailure(val event: ExecutionEvent.Error) : AttemptOutcome
    }

    private companion object {
        private const val MAX_ATTEMPTS = 3
        private const val NORMAL_CLOSURE_STATUS = 1000
        private const val PROTOCOL_ERROR_STATUS = 1002
        private const val HTTP_UNAUTHORIZED = 401
        private const val HTTP_FORBIDDEN = 403
        private const val DEFAULT_ATTEMPT_TIMEOUT_MILLIS = 35_000L
        private const val APPROVAL_CLOCK_SKEW_MILLIS = 5_000L

        private fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .pingInterval(30, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .webSocketCloseTimeout(2, TimeUnit.SECONDS)
                .build()

        private fun retryableError(code: String, message: String): ExecutionEvent.Error =
            ExecutionEvent.Error(code = code, message = message, retryable = true)

        private fun terminalError(code: String, message: String): ExecutionEvent.Error =
            ExecutionEvent.Error(code = code, message = message, retryable = false)

        private fun closeWithProtocolFailure(
            webSocket: WebSocket,
            closingOutcome: AtomicReference<AttemptOutcome?>,
            finish: (AttemptOutcome) -> Unit,
        ) {
            val failure = AttemptOutcome.FinalFailure(
                terminalError(
                    code = "protocol_error",
                    message = "Hub response did not match the supported protocol.",
                ),
            )
            closeWithOutcome(webSocket, PROTOCOL_ERROR_STATUS, failure, closingOutcome, finish)
        }

        private fun closeWithOutcome(
            webSocket: WebSocket,
            status: Int,
            outcome: AttemptOutcome,
            closingOutcome: AtomicReference<AttemptOutcome?>,
            finish: (AttemptOutcome) -> Unit,
        ) {
            closingOutcome.set(outcome)
            if (!webSocket.close(status, null)) finish(outcome)
        }
    }
}
