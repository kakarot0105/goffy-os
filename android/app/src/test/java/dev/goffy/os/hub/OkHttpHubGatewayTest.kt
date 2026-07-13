package dev.goffy.os.hub

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.ToolInvocationRequest
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.SocketEffect
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OkHttpHubGatewayTest {
    private val token = "test-token-that-is-long-enough"

    @Test
    fun sendsBearerAuthorizationHeader() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onOpen(webSocket: WebSocket, response: Response) {
                                webSocket.send(toolErrorEnvelope(TEST_REQUEST.messageId))
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server)
            val request = server.takeRequest()

            assertEquals("Bearer $token", request.headers["Authorization"])
            assertNull(request.headers["Proxy-Authorization"])
            assertEquals("tool_not_found", (events.last() as ExecutionEvent.Error).code)
        }
    }

    @Test
    fun streamsConnectingConnectedAndFourHubEvents() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onOpen(webSocket: WebSocket, response: Response) {
                                webSocket.send(progressEnvelope(TEST_REQUEST.messageId, 0, "accepted", "Invocation accepted by the Hub."))
                                webSocket.send(progressEnvelope(TEST_REQUEST.messageId, 1, "completed", "Tool returned schema-valid structured output."))
                                webSocket.send(resultEnvelope(TEST_REQUEST.messageId))
                                webSocket.send(verificationEnvelope(TEST_REQUEST.messageId))
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server)

            assertEquals(
                listOf(
                    ExecutionEvent.Starting(1),
                    ExecutionEvent.Ready,
                ),
                events.take(2),
            )
            assertTrue(events[2] is ExecutionEvent.Progress)
            assertTrue(events[3] is ExecutionEvent.Progress)
            assertEquals(
                ExecutionEvent.Result(
                    toolName = "mac.system_info",
                    executionTarget = ExecutionTarget.MAC,
                    content = MacSystemInfo(
                        status = "available",
                        operatingSystem = "Darwin",
                        architecture = "arm64",
                    ),
                ),
                events[4],
            )
            assertEquals(
                ExecutionEvent.Verification(
                    succeeded = true,
                    summary = "System information output matched the registered schema.",
                    checks = listOf("tool allowlist", "input schema", "output schema"),
                ),
                events[5],
            )
            assertEquals(1, server.requestCount)
        }
    }

    @Test
    fun authenticationFailureDoesNotRetry() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .code(401)
                    .body("unauthorized")
                    .build(),
            )

            val events = collectEvents(server)

            assertEquals(listOf(ExecutionEvent.Starting(1)), events.take(1))
            assertEquals(
                ExecutionEvent.Error(
                    code = "authentication_failed",
                    message = "Hub authentication failed.",
                    retryable = false,
                ),
                events.last(),
            )
            assertEquals(1, server.requestCount)
        }
    }

    @Test
    fun protocolFailureFromMismatchedCorrelationIdDoesNotRetry() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onOpen(webSocket: WebSocket, response: Response) {
                                webSocket.send(resultEnvelope(UUID.fromString("22222222-2222-4222-8222-222222222222")))
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server)

            assertEquals(ExecutionEvent.Starting(1), events[0])
            assertEquals(ExecutionEvent.Ready, events[1])
            assertEquals(
                ExecutionEvent.Error(
                    code = "protocol_error",
                    message = "Hub response did not match the supported protocol.",
                    retryable = false,
                ),
                events[2],
            )
            assertEquals(1, server.requestCount)
        }
    }

    @Test
    fun retriesAtMostTwiceBeforeSend() = runTest {
        MockWebServer().use { server ->
            server.start()
            repeat(3) {
                server.enqueue(
                    MockResponse.Builder()
                        .onRequestStart(SocketEffect.CloseSocket())
                        .build(),
                )
            }

            val events = collectEvents(server)

            assertEquals(
                listOf(
                    ExecutionEvent.Starting(1),
                    ExecutionEvent.Starting(2),
                    ExecutionEvent.Starting(3),
                ),
                events.take(3),
            )
            assertEquals(
                ExecutionEvent.Error(
                    code = "transport_connect_failed",
                    message = "Hub connection failed before the request was sent.",
                    retryable = true,
                ),
                events.last(),
            )
            assertEquals(3, server.requestCount)
        }
    }

    @Test
    fun collectorCancellationCancelsTheActiveSocket() = runTest {
        MockWebServer().use { server ->
            server.start()
            val disconnectLatch = CountDownLatch(1)

            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                                disconnectLatch.countDown()
                            }

                            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                                disconnectLatch.countDown()
                            }
                        },
                    )
                    .build(),
            )

            val gateway = OkHttpHubGateway()
            try {
                val events = gateway.invoke(loopbackConfig(server), TEST_REQUEST).take(2).toList()

                assertEquals(
                    listOf(ExecutionEvent.Starting(1), ExecutionEvent.Ready),
                    events,
                )
                assertTrue(disconnectLatch.await(5, TimeUnit.SECONDS))
            } finally {
                gateway.close()
            }
        }
    }

    @Test
    fun closingGatewayDoesNotShutDownAnInjectedClient() {
        val client = okhttp3.OkHttpClient()
        val gateway = OkHttpHubGateway(client)

        gateway.close()

        assertFalse(client.dispatcher.executorService.isShutdown)
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }

    private suspend fun collectEvents(server: MockWebServer): List<ExecutionEvent> {
        val gateway = OkHttpHubGateway()
        return try {
            gateway.invoke(loopbackConfig(server), TEST_REQUEST).toList()
        } finally {
            gateway.close()
        }
    }

    private fun loopbackConfig(server: MockWebServer): HubConfig =
        HubConfig.create(
            endpoint = server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
            bearerToken = token,
            allowInsecureLoopback = true,
        )

    private abstract class ClosingServerListener : WebSocketListener() {
        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, null)
        }
    }

    private companion object {
        private val TEST_REQUEST = ToolInvocationRequest(
            messageId = UUID.fromString("11111111-1111-4111-8111-111111111111"),
            toolName = "mac.system_info",
            encodedMessage =
                """{"protocolVersion":"0.1.0","messageId":"11111111-1111-4111-8111-111111111111","timestamp":"2026-07-13T16:00:00Z","deviceId":"android-test","messageType":"ToolInvocation","payload":{"toolName":"mac.system_info","arguments":{}},"correlationId":null}""",
        )

        private fun progressEnvelope(
            correlationId: UUID,
            sequence: Int,
            stage: String,
            message: String,
        ): String =
            eventEnvelope(
                messageId = "33333333-3333-4333-8333-33333333333$sequence",
                messageType = "ToolProgress",
                correlationId = correlationId,
                payload =
                    """{"toolName":"mac.system_info","executionTarget":"MAC","stage":"$stage","sequence":$sequence,"message":"$message"}""",
            )

        private fun resultEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "44444444-4444-4444-8444-444444444444",
                messageType = "ToolResult",
                correlationId = correlationId,
                payload =
                    """{"toolName":"mac.system_info","executionTarget":"MAC","structuredContent":{"status":"available","operatingSystem":"Darwin","architecture":"arm64"}}""",
            )

        private fun verificationEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "55555555-5555-4555-8555-555555555555",
                messageType = "VerificationResult",
                correlationId = correlationId,
                payload =
                    """{"succeeded":true,"summary":"System information output matched the registered schema.","checks":["tool allowlist","input schema","output schema"]}""",
            )

        private fun toolErrorEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "66666666-6666-4666-8666-666666666666",
                messageType = "ToolError",
                correlationId = correlationId,
                payload =
                    """{"code":"tool_not_found","message":"The requested tool is unavailable or unauthorized.","retryable":false}""",
            )

        private fun eventEnvelope(
            messageId: String,
            messageType: String,
            correlationId: UUID,
            payload: String,
        ): String =
            """{"protocolVersion":"0.1.0","messageId":"$messageId","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"$messageType","payload":$payload,"correlationId":"$correlationId"}"""
    }
}
