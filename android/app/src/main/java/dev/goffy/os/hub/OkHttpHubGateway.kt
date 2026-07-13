package dev.goffy.os.hub

import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.HubStreamEvent
import dev.goffy.os.protocol.ProtocolException
import dev.goffy.os.protocol.ToolInvocationRequest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.resume
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
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
) : HubGateway {
    constructor() : this(defaultClient(), GoffyProtocolCodec(), ownsClient = true)

    internal constructor(
        client: OkHttpClient,
        codec: GoffyProtocolCodec = GoffyProtocolCodec(),
    ) : this(client, codec, ownsClient = false)

    private val closed = AtomicBoolean(false)
    private val activeSockets = ConcurrentHashMap.newKeySet<WebSocket>()

    override fun invoke(config: HubConfig, request: ToolInvocationRequest): Flow<HubStreamEvent> {
        if (closed.get()) {
            return flowOf(
                HubStreamEvent.Error(
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
        emit: (HubStreamEvent) -> Unit,
    ) {
        var attempt = 1

        while (attempt <= MAX_ATTEMPTS && !closed.get()) {
            emit(HubStreamEvent.Connecting(attempt))

            when (
                val outcome = performAttempt(
                    config = config,
                    request = request,
                    invocationSocket = invocationSocket,
                    emit = emit,
                )
            ) {
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
        emit: (HubStreamEvent) -> Unit,
    ): AttemptOutcome = suspendCancellableCoroutine { continuation ->
        val messageSent = AtomicBoolean(false)
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
                emit(HubStreamEvent.Connected)

                if (webSocket.send(request.encodedMessage)) {
                    messageSent.set(true)
                } else {
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
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
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
                if (event is HubStreamEvent.Verification || event is HubStreamEvent.Error) {
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
                    !messageSent.get() -> finish(
                        AttemptOutcome.RetryableFailure(
                            retryableError(
                                code = "transport_connect_failed",
                                message = "Hub connection closed before the request was sent.",
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
                    !messageSent.get() -> {
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

    private sealed interface AttemptOutcome {
        data object Completed : AttemptOutcome

        data class RetryableFailure(val event: HubStreamEvent.Error) : AttemptOutcome

        data class FinalFailure(val event: HubStreamEvent.Error) : AttemptOutcome
    }

    private companion object {
        private const val MAX_ATTEMPTS = 3
        private const val NORMAL_CLOSURE_STATUS = 1000
        private const val PROTOCOL_ERROR_STATUS = 1002
        private const val HTTP_UNAUTHORIZED = 401
        private const val HTTP_FORBIDDEN = 403

        private fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .pingInterval(30, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .webSocketCloseTimeout(2, TimeUnit.SECONDS)
                .build()

        private fun retryableError(code: String, message: String): HubStreamEvent.Error =
            HubStreamEvent.Error(code = code, message = message, retryable = true)

        private fun terminalError(code: String, message: String): HubStreamEvent.Error =
            HubStreamEvent.Error(code = code, message = message, retryable = false)

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
