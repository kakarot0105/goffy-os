package dev.goffy.os.hub

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.MacProcessEntry
import dev.goffy.os.protocol.MacProcessesList
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.ToolInvocationRequest
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
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
                        object : DiscoveryServerListener() {
                            override fun onInvocation(webSocket: WebSocket) {
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
                        object : DiscoveryServerListener() {
                            override fun onInvocation(webSocket: WebSocket) {
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
                    summary = "mac.system_info output matched the registered schema.",
                    checks = listOf("tool allowlist", "input schema", "output schema"),
                ),
                events[5],
            )
            assertEquals(1, server.requestCount)
        }
    }

    @Test
    fun streamsMacProcessesListThroughDiscoveryAndInvocation() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onMessage(webSocket: WebSocket, text: String) {
                                when {
                                    text.contains("\"messageType\":\"CapabilityDiscoveryRequest\"") ->
                                        webSocket.send(
                                            capabilityEnvelope(
                                                PROCESS_REQUEST.discoveryMessageId,
                                                processCapabilityTool(),
                                            ),
                                        )
                                    text.contains("\"messageType\":\"ToolInvocation\"") -> {
                                        assertTrue(text.contains("\"toolName\":\"mac.processes.list\""))
                                        assertTrue(text.contains("\"maxEntries\":10"))
                                        webSocket.send(
                                            processProgressEnvelope(
                                                PROCESS_REQUEST.messageId,
                                                0,
                                                "accepted",
                                                "Invocation accepted by the Hub.",
                                            ),
                                        )
                                        webSocket.send(
                                            processProgressEnvelope(
                                                PROCESS_REQUEST.messageId,
                                                1,
                                                "completed",
                                                "Tool returned schema-valid structured output.",
                                            ),
                                        )
                                        webSocket.send(processResultEnvelope(PROCESS_REQUEST.messageId))
                                        webSocket.send(
                                            processVerificationEnvelope(PROCESS_REQUEST.messageId),
                                        )
                                    }
                                    else -> error("unexpected client message")
                                }
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server, PROCESS_REQUEST)

            assertEquals(ExecutionEvent.Starting(1), events[0])
            assertEquals(ExecutionEvent.Ready, events[1])
            assertEquals(
                ExecutionEvent.Result(
                    toolName = "mac.processes.list",
                    executionTarget = ExecutionTarget.MAC,
                    content = MacProcessesList(
                        status = "available",
                        processCount = 2,
                        skippedCount = 0,
                        truncated = false,
                        entries = listOf(
                            MacProcessEntry(
                                pid = 88,
                                name = "WindowServer",
                                status = "running",
                                rssBytes = 512_000_000L,
                                createTimeEpochSeconds = 1_784_620_000L,
                            ),
                            MacProcessEntry(
                                pid = 99,
                                name = "loginwindow",
                                status = "sleeping",
                                rssBytes = 128_000_000L,
                                createTimeEpochSeconds = null,
                            ),
                        ),
                    ),
                ),
                events[4],
            )
            assertEquals(
                ExecutionEvent.Verification(
                    succeeded = true,
                    summary = "mac.processes.list output matched the registered schema.",
                    checks = listOf("tool allowlist", "input schema", "output schema"),
                ),
                events[5],
            )
        }
    }

    @Test
    fun missingCapabilityFailsBeforeReadyOrInvocation() = runTest {
        MockWebServer().use { server ->
            val invocations = AtomicInteger(0)
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onMessage(webSocket: WebSocket, text: String) {
                                if (text.contains("\"messageType\":\"CapabilityDiscoveryRequest\"")) {
                                    webSocket.send(
                                        capabilityEnvelope(TEST_REQUEST.discoveryMessageId, tools = ""),
                                    )
                                } else {
                                    invocations.incrementAndGet()
                                }
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server)

            assertEquals(0, invocations.get())
            assertEquals(listOf(ExecutionEvent.Starting(1)), events.dropLast(1))
            assertEquals("capability_unavailable", (events.last() as ExecutionEvent.Error).code)
        }
    }

    @Test
    fun incompatibleCapabilityFailsClosedBeforeInvocation() = runTest {
        MockWebServer().use { server ->
            val invocations = AtomicInteger(0)
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onMessage(webSocket: WebSocket, text: String) {
                                if (text.contains("\"messageType\":\"CapabilityDiscoveryRequest\"")) {
                                    webSocket.send(
                                        capabilityEnvelope(
                                            TEST_REQUEST.discoveryMessageId,
                                            capabilityTool().replace(
                                                "\"dev.goffy/permission\":\"SAFE\"",
                                                "\"dev.goffy/permission\":\"SENSITIVE\"",
                                            ),
                                        ),
                                    )
                                } else {
                                    invocations.incrementAndGet()
                                }
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server)

            assertEquals(0, invocations.get())
            assertEquals(listOf(ExecutionEvent.Starting(1)), events.dropLast(1))
            assertEquals("protocol_error", (events.last() as ExecutionEvent.Error).code)
        }
    }

    @Test
    fun unansweredDiscoveryTimesOutAndCancelsWithoutInvocation() = runTest {
        MockWebServer().use { server ->
            val discoveryRequests = AtomicInteger(0)
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onMessage(webSocket: WebSocket, text: String) {
                                if (text.contains("\"messageType\":\"CapabilityDiscoveryRequest\"")) {
                                    discoveryRequests.incrementAndGet()
                                }
                            }
                        },
                    )
                    .build(),
            )
            val client = okhttp3.OkHttpClient()
            val gateway = OkHttpHubGateway(client, attemptTimeoutMillis = 1_000)

            val events = try {
                gateway.invoke(loopbackConfig(server), TEST_REQUEST).toList()
            } finally {
                gateway.close()
                client.dispatcher.executorService.shutdown()
                client.connectionPool.evictAll()
            }

            assertEquals(ExecutionEvent.Starting(1), events.first())
            assertEquals("hub_response_timeout", (events.last() as ExecutionEvent.Error).code)
            assertTrue(events.none { it is ExecutionEvent.Ready })
            assertEquals(1, discoveryRequests.get())
            assertEquals(1, server.requestCount)
        }
    }

    @Test
    fun expiredApprovalDoesNotOpenSocketOrRetry() = runTest {
        MockWebServer().use { server ->
            server.start()
            val client = okhttp3.OkHttpClient()
            val gateway = OkHttpHubGateway(client, nowMillis = { 2_000L })

            val events = try {
                gateway.invoke(
                    loopbackConfig(server),
                    TEST_REQUEST.copy(expiresAtEpochMillis = 1_000L),
                ).toList()
            } finally {
                gateway.close()
                client.dispatcher.executorService.shutdown()
                client.connectionPool.evictAll()
            }

            assertEquals(
                listOf(
                    ExecutionEvent.Error(
                        code = "approval_expired",
                        message = "The approved action expired before it could be sent.",
                        retryable = false,
                    ),
                ),
                events,
            )
            assertEquals(0, server.requestCount)
        }
    }

    @Test
    fun approvalExpiringAfterDiscoveryStopsBeforeInvocation() = runTest {
        MockWebServer().use { server ->
            val invocations = AtomicInteger(0)
            val now = AtomicInteger(0)
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : ClosingServerListener() {
                            override fun onMessage(webSocket: WebSocket, text: String) {
                                when {
                                    text.contains("\"messageType\":\"CapabilityDiscoveryRequest\"") -> {
                                        now.set(2_000)
                                        webSocket.send(capabilityEnvelope(TEST_REQUEST.discoveryMessageId))
                                    }
                                    text.contains("\"messageType\":\"ToolInvocation\"") ->
                                        invocations.incrementAndGet()
                                    else -> error("unexpected client message")
                                }
                            }
                        },
                    )
                    .build(),
            )
            val client = okhttp3.OkHttpClient()
            val gateway = OkHttpHubGateway(client, nowMillis = { now.get().toLong() })

            val events = try {
                gateway.invoke(
                    loopbackConfig(server),
                    TEST_REQUEST.copy(expiresAtEpochMillis = 1_000L),
                ).toList()
            } finally {
                gateway.close()
                client.dispatcher.executorService.shutdown()
                client.connectionPool.evictAll()
            }

            assertEquals(0, invocations.get())
            assertEquals(listOf(ExecutionEvent.Starting(1)), events.dropLast(1))
            assertEquals("approval_expired", (events.last() as ExecutionEvent.Error).code)
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
                        object : DiscoveryServerListener() {
                            override fun onInvocation(webSocket: WebSocket) {
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
    fun retriesDiscoveryDisconnectsBeforeInvocationIsSent() = runTest {
        MockWebServer().use { server ->
            server.start()
            repeat(3) {
                server.enqueue(
                    MockResponse.Builder()
                        .webSocketUpgrade(
                            object : ClosingServerListener() {
                                override fun onMessage(webSocket: WebSocket, text: String) {
                                    assertTrue(
                                        text.contains(
                                            "\"messageType\":\"CapabilityDiscoveryRequest\"",
                                        ),
                                    )
                                    webSocket.close(1011, "discovery interrupted")
                                }
                            },
                        )
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
            assertEquals("transport_connect_failed", (events.last() as ExecutionEvent.Error).code)
            assertTrue(events.none { it is ExecutionEvent.Ready })
            assertEquals(3, server.requestCount)
        }
    }

    @Test
    fun neverReplaysAfterInvocationBytesAreSent() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .webSocketUpgrade(
                        object : DiscoveryServerListener() {
                            override fun onInvocation(webSocket: WebSocket) {
                                webSocket.close(1011, "invocation interrupted")
                            }
                        },
                    )
                    .build(),
            )

            val events = collectEvents(server)

            assertEquals(ExecutionEvent.Starting(1), events.first())
            assertEquals(ExecutionEvent.Ready, events[1])
            assertEquals("transport_disconnected", (events.last() as ExecutionEvent.Error).code)
            assertEquals(1, server.requestCount)
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
                        object : DiscoveryServerListener() {
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

    private suspend fun collectEvents(
        server: MockWebServer,
        request: ToolInvocationRequest = TEST_REQUEST,
    ): List<ExecutionEvent> {
        val gateway = OkHttpHubGateway()
        return try {
            gateway.invoke(loopbackConfig(server), request).toList()
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

    private abstract class DiscoveryServerListener : ClosingServerListener() {
        final override fun onMessage(webSocket: WebSocket, text: String) {
            when {
                text.contains("\"messageType\":\"CapabilityDiscoveryRequest\"") ->
                    webSocket.send(capabilityEnvelope(TEST_REQUEST.discoveryMessageId))
                text.contains("\"messageType\":\"ToolInvocation\"") -> onInvocation(webSocket)
                else -> error("unexpected client message")
            }
        }

        open fun onInvocation(webSocket: WebSocket) = Unit
    }

    private companion object {
        private val TEST_REQUEST = ToolInvocationRequest(
            messageId = UUID.fromString("11111111-1111-4111-8111-111111111111"),
            toolName = "mac.system_info",
            encodedMessage =
                """{"protocolVersion":"0.2.0","messageId":"11111111-1111-4111-8111-111111111111","timestamp":"2026-07-13T16:00:00Z","deviceId":"android-test","messageType":"ToolInvocation","payload":{"toolName":"mac.system_info","arguments":{}},"correlationId":null}""",
            discoveryMessageId = UUID.fromString("77777777-7777-4777-8777-777777777777"),
            encodedDiscoveryMessage =
                """{"protocolVersion":"0.2.0","messageId":"77777777-7777-4777-8777-777777777777","timestamp":"2026-07-13T16:00:00Z","deviceId":"android-test","messageType":"CapabilityDiscoveryRequest","payload":{"toolName":"mac.system_info"},"correlationId":null}""",
        )

        private val PROCESS_REQUEST = ToolInvocationRequest(
            messageId = UUID.fromString("12121212-1212-4212-8212-121212121212"),
            toolName = "mac.processes.list",
            encodedMessage =
                """{"protocolVersion":"0.2.0","messageId":"12121212-1212-4212-8212-121212121212","timestamp":"2026-07-13T16:00:00Z","deviceId":"android-test","messageType":"ToolInvocation","payload":{"toolName":"mac.processes.list","arguments":{"maxEntries":10}},"correlationId":null}""",
            discoveryMessageId = UUID.fromString("78787878-7878-4878-8878-787878787878"),
            encodedDiscoveryMessage =
                """{"protocolVersion":"0.2.0","messageId":"78787878-7878-4878-8878-787878787878","timestamp":"2026-07-13T16:00:00Z","deviceId":"android-test","messageType":"CapabilityDiscoveryRequest","payload":{"toolName":"mac.processes.list"},"correlationId":null}""",
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

        private fun processProgressEnvelope(
            correlationId: UUID,
            sequence: Int,
            stage: String,
            message: String,
        ): String =
            eventEnvelope(
                messageId = "77777777-7777-4777-8777-77777777777$sequence",
                messageType = "ToolProgress",
                correlationId = correlationId,
                payload =
                    """{"toolName":"mac.processes.list","executionTarget":"MAC","stage":"$stage","sequence":$sequence,"message":"$message"}""",
            )

        private fun processResultEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "77777777-7777-4777-8777-777777777778",
                messageType = "ToolResult",
                correlationId = correlationId,
                payload =
                    """{"toolName":"mac.processes.list","executionTarget":"MAC","structuredContent":{"status":"available","processCount":2,"skippedCount":0,"truncated":false,"entries":[{"pid":88,"name":"WindowServer","status":"running","rssBytes":512000000,"createTimeEpochSeconds":1784620000},{"pid":99,"name":"loginwindow","status":"sleeping","rssBytes":128000000,"createTimeEpochSeconds":null}]}}""",
            )

        private fun verificationEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "55555555-5555-4555-8555-555555555555",
                messageType = "VerificationResult",
                correlationId = correlationId,
                payload =
                    """{"succeeded":true,"summary":"mac.system_info output matched the registered schema.","checks":["tool allowlist","input schema","output schema"]}""",
            )

        private fun processVerificationEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "77777777-7777-4777-8777-777777777779",
                messageType = "VerificationResult",
                correlationId = correlationId,
                payload =
                    """{"succeeded":true,"summary":"mac.processes.list output matched the registered schema.","checks":["tool allowlist","input schema","output schema"]}""",
            )

        private fun toolErrorEnvelope(correlationId: UUID): String =
            eventEnvelope(
                messageId = "66666666-6666-4666-8666-666666666666",
                messageType = "ToolError",
                correlationId = correlationId,
                payload =
                    """{"code":"tool_not_found","message":"The requested tool is unavailable or unauthorized.","retryable":false}""",
            )

        private fun capabilityEnvelope(correlationId: UUID, tools: String = capabilityTool()): String =
            eventEnvelope(
                messageId = "88888888-8888-4888-8888-888888888888",
                messageType = "CapabilityDiscoveryResponse",
                correlationId = correlationId,
                payload =
                    """{"mcpProtocolVersion":"2025-11-25","listChanged":false,"tools":[$tools]}""",
            )

        private fun capabilityTool(): String =
            """{"name":"mac.system_info","title":"Mac system information","description":"Read a minimal, non-sensitive snapshot of the Hub host.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{},"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"architecture":{"type":"string"},"operatingSystem":{"type":"string"},"status":{"type":"string"}},"required":["status","operatingSystem","architecture"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

        private fun processCapabilityTool(): String =
            """{"name":"mac.processes.list","title":"Mac running process summary","description":"List bounded read-only metadata for running Mac processes without exposing command lines, executable paths, environment variables, open files, or network data.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"maxEntries":{"default":10,"maximum":25,"minimum":1,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"MacProcessEntryOutput":{"additionalProperties":false,"properties":{"createTimeEpochSeconds":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null},"name":{"maxLength":96,"minLength":1,"type":"string"},"pid":{"maximum":2147483647,"minimum":0,"type":"integer"},"rssBytes":{"maximum":9223372036854775807,"minimum":0,"type":"integer"},"status":{"maxLength":32,"minLength":1,"type":"string"}},"required":["pid","name","status","rssBytes"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"entries":{"items":{"${'$'}ref":"#/${'$'}defs/MacProcessEntryOutput"},"maxItems":25,"type":"array"},"processCount":{"maximum":100000,"minimum":0,"type":"integer"},"skippedCount":{"maximum":100000,"minimum":0,"type":"integer"},"status":{"maxLength":64,"minLength":1,"type":"string"},"truncated":{"type":"boolean"}},"required":["status","processCount","skippedCount","truncated","entries"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

        private fun eventEnvelope(
            messageId: String,
            messageType: String,
            correlationId: UUID,
            payload: String,
        ): String =
            """{"protocolVersion":"0.2.0","messageId":"$messageId","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"$messageType","payload":$payload,"correlationId":"$correlationId"}"""
    }
}
