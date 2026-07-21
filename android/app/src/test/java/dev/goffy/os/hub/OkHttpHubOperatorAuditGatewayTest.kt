package dev.goffy.os.hub

import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class OkHttpHubOperatorAuditGatewayTest {
    @Test
    fun readsSelfAuditEventsWithBearerHeaderAndBoundedLimit() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(200, AUDIT_JSON))
            val gateway = OkHttpHubOperatorAuditGateway(OkHttpClient())
            val config = hubConfig(server)

            val snapshot = gateway.listSelfEvents(config, limit = 5)
            val request = server.takeRequest()

            assertEquals("/paired/v1/audit/events", request.url.encodedPath)
            assertEquals("limit=5", request.url.encodedQuery)
            assertEquals("GET", request.method)
            assertEquals("Bearer $ACCESS_TOKEN", request.headers["Authorization"])
            assertEquals(0, request.bodySize)
            assertEquals("sqlite", snapshot.storageKind)
            assertEquals("verified", snapshot.integrity)
            assertEquals(1, snapshot.events.size)
            assertEquals(7, snapshot.events.single().sequence)
            assertEquals(Instant.parse("2026-07-13T16:01:00Z"), snapshot.events.single().recordedAt)
            assertEquals(UUID.fromString(CREDENTIAL_ID), snapshot.events.single().credentialId)
            assertEquals("mcp", snapshot.events.single().source)
            assertEquals("http.get", snapshot.events.single().action)
            assertFalse(snapshot.toString().contains(ACCESS_TOKEN))
            gateway.close()
        }
    }

    @Test
    fun refusesSelfAuditAgainstNonLoopbackEndpoints() = runTest {
        val gateway = OkHttpHubOperatorAuditGateway(OkHttpClient())
        val config = HubConfig.create("wss://hub.example/ws/v1", ACCESS_TOKEN, false)

        val failure = runCatching {
            gateway.listSelfEvents(config)
        }.exceptionOrNull()

        assertTrue(failure is HubOperatorAuditException)
        assertEquals("audit_loopback_required", (failure as HubOperatorAuditException).code)
        gateway.close()
    }

    @Test
    fun mapsHubErrorsWithoutReadingOrEchoingSecretBodies() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(401, "{\"detail\":\"$ACCESS_TOKEN\"}"))
            val gateway = OkHttpHubOperatorAuditGateway(OkHttpClient())

            val failure = runCatching {
                gateway.listSelfEvents(hubConfig(server))
            }.exceptionOrNull()

            assertTrue(failure is HubOperatorAuditException)
            assertEquals("audit_authentication_failed", (failure as HubOperatorAuditException).code)
            assertFalse(failure.message.orEmpty().contains(ACCESS_TOKEN))
            assertFalse(failure.toString().contains(ACCESS_TOKEN))
            assertEquals(1, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun rejectsExtendedAuditResponses() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(200, AUDIT_JSON.dropLast(1) + ",\"unexpected\":true}"))
            val gateway = OkHttpHubOperatorAuditGateway(OkHttpClient())

            val failure = runCatching {
                gateway.listSelfEvents(hubConfig(server))
            }.exceptionOrNull()

            assertTrue(failure is HubOperatorAuditException)
            assertEquals("invalid_audit_response", (failure as HubOperatorAuditException).code)
            assertEquals(1, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun defaultClientDoesNotFollowAuditRedirects() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .code(307)
                    .addHeader("Location", server.url("/redirected").toString())
                    .build(),
            )
            val gateway = OkHttpHubOperatorAuditGateway()

            val failure = runCatching {
                gateway.listSelfEvents(hubConfig(server))
            }.exceptionOrNull()

            assertTrue(failure is HubOperatorAuditException)
            assertEquals("audit_rejected", (failure as HubOperatorAuditException).code)
            assertEquals(1, server.requestCount)
            assertEquals("/paired/v1/audit/events", server.takeRequest().url.encodedPath)
            gateway.close()
        }
    }

    private fun hubConfig(server: MockWebServer): HubConfig = HubConfig.create(
        server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
        ACCESS_TOKEN,
        allowInsecureLoopback = true,
    )

    private fun jsonResponse(status: Int, body: String): MockResponse = MockResponse.Builder()
        .code(status)
        .addHeader("Content-Type", "application/json")
        .body(body)
        .build()

    private companion object {
        const val ACCESS_TOKEN = "paired-access-token-abcdefghijklmnopqrstuvwxyz0123456789"
        const val CREDENTIAL_ID = "22222222-2222-4222-8222-222222222222"
        const val PREVIOUS_HASH =
            "0000000000000000000000000000000000000000000000000000000000000000"
        const val EVENT_HASH =
            "1111111111111111111111111111111111111111111111111111111111111111"
        const val AUDIT_JSON =
            "{\"storageKind\":\"sqlite\",\"integrity\":\"verified\",\"events\":[{" +
                "\"sequence\":7," +
                "\"recordedAt\":\"2026-07-13T16:01:00Z\"," +
                "\"source\":\"mcp\"," +
                "\"action\":\"http.get\"," +
                "\"outcome\":\"succeeded\"," +
                "\"principalKind\":\"paired\"," +
                "\"credentialId\":\"$CREDENTIAL_ID\"," +
                "\"detailCode\":null," +
                "\"previousHash\":\"$PREVIOUS_HASH\"," +
                "\"eventHash\":\"$EVENT_HASH\"" +
                "}]}"
    }
}
