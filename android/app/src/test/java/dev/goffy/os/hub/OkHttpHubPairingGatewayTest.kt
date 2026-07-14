package dev.goffy.os.hub

import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class OkHttpHubPairingGatewayTest {
    @Test
    fun redeemsExactTypedChallengeWithoutPuttingSecretsInTheUrl() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(201, SUCCESS_JSON))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val issued = gateway.redeem(
                endpoint(server),
                CHALLENGE_JSON,
                "goffy-android-test",
                "Moto G",
            )
            val request = server.takeRequest()

            assertEquals("/pairing/v1/redeem", request.url.encodedPath)
            assertNull(request.url.query)
            assertNull(request.headers["Authorization"])
            assertEquals("application/json; charset=utf-8", request.headers["Content-Type"])
            assertEquals(
                """{"challengeId":"$CHALLENGE_ID","pairingToken":"$PAIRING_TOKEN","deviceId":"goffy-android-test","displayName":"Moto G"}""",
                request.body?.utf8(),
            )
            assertEquals(UUID.fromString(CREDENTIAL_ID), issued.credentialId)
            assertEquals(Instant.parse("2026-07-13T16:00:00Z"), issued.createdAt)
            assertFalse(issued.toString().contains(ACCESS_TOKEN))
            gateway.close()
        }
    }

    @Test
    fun rejectsMalformedOrExtendedChallengeBeforeAnyNetworkCall() = runTest {
        MockWebServer().use { server ->
            server.start()
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val extraField = CHALLENGE_JSON.dropLast(1) + ",\"unexpected\":true}"
            val failure = runCatching {
                gateway.redeem(endpoint(server), extraField, "goffy-test", "Moto G")
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("invalid_pairing_payload", (failure as HubPairingException).code)
            assertFalse(failure.message.orEmpty().contains(PAIRING_TOKEN))
            assertEquals(0, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun rejectsMalformedOrOversizedSuccessAndNeverRetriesRedemption() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(201, "{\"credentialId\":\"$CREDENTIAL_ID\"}"))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val failure = runCatching {
                gateway.redeem(endpoint(server), CHALLENGE_JSON, "goffy-test", "Moto G")
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("invalid_pairing_response", (failure as HubPairingException).code)
            assertEquals(1, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun mapsHubErrorsWithoutReadingOrEchoingSecretBodies() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(400, "{\"detail\":\"$PAIRING_TOKEN\"}"))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val failure = runCatching {
                gateway.redeem(endpoint(server), CHALLENGE_JSON, "goffy-test", "Moto G")
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("invalid_pairing_challenge", (failure as HubPairingException).code)
            assertFalse(failure.message.orEmpty().contains(PAIRING_TOKEN))
            assertFalse(failure.toString().contains(PAIRING_TOKEN))
            gateway.close()
        }
    }

    @Test
    fun refusesToSendPairingMaterialToANonLoopbackTlsEndpoint() = runTest {
        val gateway = OkHttpHubPairingGateway(OkHttpClient())

        val failure = runCatching {
            gateway.redeem(
                HubEndpoint.create("wss://hub.example/ws/v1", false),
                CHALLENGE_JSON,
                "goffy-test",
                "Moto G",
            )
        }.exceptionOrNull()

        assertTrue(failure is HubPairingException)
        assertEquals("pairing_loopback_required", (failure as HubPairingException).code)
        assertFalse(failure.message.orEmpty().contains(PAIRING_TOKEN))
        gateway.close()
    }

    private fun endpoint(server: MockWebServer): HubEndpoint = HubEndpoint.create(
        server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
        allowInsecureLoopback = true,
    )

    private fun jsonResponse(status: Int, body: String): MockResponse = MockResponse.Builder()
        .code(status)
        .addHeader("Content-Type", "application/json")
        .body(body)
        .build()

    private companion object {
        const val CHALLENGE_ID = "11111111-1111-4111-8111-111111111111"
        const val CREDENTIAL_ID = "22222222-2222-4222-8222-222222222222"
        const val PAIRING_TOKEN = "pairing-token-abcdefghijklmnopqrstuvwxyz0123456789"
        const val ACCESS_TOKEN = "paired-access-token-abcdefghijklmnopqrstuvwxyz0123456789"
        const val CHALLENGE_JSON =
            "{\"challengeId\":\"$CHALLENGE_ID\",\"pairingToken\":\"$PAIRING_TOKEN\"," +
                "\"expiresAt\":\"2026-07-13T16:02:00Z\"}"
        const val SUCCESS_JSON =
            "{\"credentialId\":\"$CREDENTIAL_ID\",\"accessToken\":\"$ACCESS_TOKEN\"," +
                "\"createdAt\":\"2026-07-13T16:00:00Z\"}"
    }
}
