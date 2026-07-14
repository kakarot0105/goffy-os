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
    fun rejectsRawChallengeJsonBeforeAnyNetworkCall() = runTest {
        MockWebServer().use { server ->
            server.start()
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val failure = runCatching {
                gateway.redeem(
                    endpoint(server),
                    CHALLENGE_JSON,
                    "goffy-android-test",
                    "Moto G",
                )
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("invalid_pairing_payload", (failure as HubPairingException).code)
            assertFalse(failure.message.orEmpty().contains(PAIRING_TOKEN))
            assertEquals(0, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun redeemsExactTypedPairingBundleWithoutPuttingSecretsInTheUrl() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(201, SUCCESS_JSON))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val issued = gateway.redeem(
                endpoint(server),
                pairingBundle(server),
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
    fun rejectsMalformedNestedPairingBundleBeforeAnyNetworkCall() = runTest {
        MockWebServer().use { server ->
            server.start()
            val gateway = OkHttpHubPairingGateway(OkHttpClient())
            val badIdentity = pairingBundle(server).replace(
                "\"hubIdentity\":{\"mode\":\"usb_loopback\",\"verifiedBy\":\"loopback_admin_session\",\"trustedLanSupported\":false}",
                "\"hubIdentity\":true",
            )
            val badChallenge = pairingBundle(server).replace(
                "\"challenge\":$CHALLENGE_JSON",
                "\"challenge\":\"not-an-object\"",
            )

            val identityFailure = runCatching {
                gateway.redeem(endpoint(server), badIdentity, "goffy-test", "Moto G")
            }.exceptionOrNull()
            val challengeFailure = runCatching {
                gateway.redeem(endpoint(server), badChallenge, "goffy-test", "Moto G")
            }.exceptionOrNull()

            assertTrue(identityFailure is HubPairingException)
            assertEquals("invalid_pairing_payload", (identityFailure as HubPairingException).code)
            assertTrue(challengeFailure is HubPairingException)
            assertEquals("invalid_pairing_payload", (challengeFailure as HubPairingException).code)
            assertEquals(0, server.requestCount)
            assertFalse(identityFailure.message.orEmpty().contains(PAIRING_TOKEN))
            assertFalse(challengeFailure.message.orEmpty().contains(PAIRING_TOKEN))
            gateway.close()
        }
    }

    @Test
    fun rejectsMalformedOrExtendedPairingPayloadBeforeAnyNetworkCall() = runTest {
        MockWebServer().use { server ->
            server.start()
            val gateway = OkHttpHubPairingGateway(OkHttpClient())

            val extraField = pairingBundle(server).dropLast(1) + ",\"unexpected\":true}"
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
    fun rejectsMismatchedOrExtendedPairingBundleBeforeAnyNetworkCall() = runTest {
        MockWebServer().use { server ->
            server.start()
            val gateway = OkHttpHubPairingGateway(OkHttpClient())
            val mismatchedEndpoint = pairingBundle(server).replace(
                endpoint(server).webSocketUrl,
                "ws://127.0.0.1:9999/ws/v1",
            )
            val extended = pairingBundle(server).dropLast(1) + ",\"unexpected\":true}"

            val mismatchFailure = runCatching {
                gateway.redeem(endpoint(server), mismatchedEndpoint, "goffy-test", "Moto G")
            }.exceptionOrNull()
            val extendedFailure = runCatching {
                gateway.redeem(endpoint(server), extended, "goffy-test", "Moto G")
            }.exceptionOrNull()

            assertTrue(mismatchFailure is HubPairingException)
            assertEquals("invalid_pairing_payload", (mismatchFailure as HubPairingException).code)
            assertTrue(extendedFailure is HubPairingException)
            assertEquals("invalid_pairing_payload", (extendedFailure as HubPairingException).code)
            assertEquals(0, server.requestCount)
            assertFalse(mismatchFailure.message.orEmpty().contains(PAIRING_TOKEN))
            assertFalse(extendedFailure.message.orEmpty().contains(PAIRING_TOKEN))
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
                gateway.redeem(endpoint(server), pairingBundle(server), "goffy-test", "Moto G")
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
                gateway.redeem(endpoint(server), pairingBundle(server), "goffy-test", "Moto G")
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

    @Test
    fun revokesSelfWithExactTypedRequestAndBearerHeader() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(200, "{\"credentialId\":\"$CREDENTIAL_ID\",\"revoked\":true}"))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())
            val config = HubConfig.create(
                server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
                ACCESS_TOKEN,
                allowInsecureLoopback = true,
            )

            val result = gateway.revokeSelf(config, UUID.fromString(CREDENTIAL_ID))
            val request = server.takeRequest()

            assertEquals("/pairing/v1/self", request.url.encodedPath)
            assertNull(request.url.query)
            assertEquals("DELETE", request.method)
            assertEquals("Bearer $ACCESS_TOKEN", request.headers["Authorization"])
            assertEquals(0, request.bodySize)
            assertEquals(UUID.fromString(CREDENTIAL_ID), result.credentialId)
            assertTrue(result.revoked)
            gateway.close()
        }
    }

    @Test
    fun rejectsMismatchedRevocationResponsesWithoutRetrying() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(200, "{\"credentialId\":\"$OTHER_CREDENTIAL_ID\",\"revoked\":true}"))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())
            val config = HubConfig.create(
                server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
                ACCESS_TOKEN,
                allowInsecureLoopback = true,
            )

            val failure = runCatching {
                gateway.revokeSelf(config, UUID.fromString(CREDENTIAL_ID))
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("invalid_revocation_response", (failure as HubPairingException).code)
            assertEquals(1, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun rejectsFalseRevocationResponsesWithoutRetrying() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(200, "{\"credentialId\":\"$CREDENTIAL_ID\",\"revoked\":false}"))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())
            val config = HubConfig.create(
                server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
                ACCESS_TOKEN,
                allowInsecureLoopback = true,
            )

            val failure = runCatching {
                gateway.revokeSelf(config, UUID.fromString(CREDENTIAL_ID))
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("invalid_revocation_response", (failure as HubPairingException).code)
            assertEquals(1, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun mapsRevocationErrorsWithoutReadingOrEchoingSecretBodies() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(jsonResponse(401, "{\"detail\":\"$ACCESS_TOKEN\"}"))
            val gateway = OkHttpHubPairingGateway(OkHttpClient())
            val config = HubConfig.create(
                server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
                ACCESS_TOKEN,
                allowInsecureLoopback = true,
            )

            val failure = runCatching {
                gateway.revokeSelf(config, UUID.fromString(CREDENTIAL_ID))
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("revocation_authentication_failed", (failure as HubPairingException).code)
            assertFalse(failure.message.orEmpty().contains(ACCESS_TOKEN))
            assertFalse(failure.toString().contains(ACCESS_TOKEN))
            assertEquals(1, server.requestCount)
            gateway.close()
        }
    }

    @Test
    fun defaultClientDoesNotFollowRevocationRedirects() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(
                MockResponse.Builder()
                    .code(307)
                    .addHeader("Location", server.url("/redirected").toString())
                    .build(),
            )
            val gateway = OkHttpHubPairingGateway()
            val config = HubConfig.create(
                server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
                ACCESS_TOKEN,
                allowInsecureLoopback = true,
            )

            val failure = runCatching {
                gateway.revokeSelf(config, UUID.fromString(CREDENTIAL_ID))
            }.exceptionOrNull()

            assertTrue(failure is HubPairingException)
            assertEquals("revocation_rejected", (failure as HubPairingException).code)
            assertEquals(1, server.requestCount)
            assertEquals("/pairing/v1/self", server.takeRequest().url.encodedPath)
            gateway.close()
        }
    }

    @Test
    fun refusesPairedSelfRevocationAgainstNonLoopbackEndpoints() = runTest {
        val gateway = OkHttpHubPairingGateway(OkHttpClient())
        val config = HubConfig.create("wss://hub.example/ws/v1", ACCESS_TOKEN, false)

        val failure = runCatching {
            gateway.revokeSelf(config, UUID.fromString(CREDENTIAL_ID))
        }.exceptionOrNull()

        assertTrue(failure is HubPairingException)
        assertEquals("revocation_loopback_required", (failure as HubPairingException).code)
        gateway.close()
    }

    private fun endpoint(server: MockWebServer): HubEndpoint = HubEndpoint.create(
        server.url("/ws/v1").toString().replaceFirst("http://", "ws://"),
        allowInsecureLoopback = true,
    )

    private fun pairingBundle(server: MockWebServer): String =
        "{\"bundleVersion\":\"goffy.pairing.bundle.v1\"," +
            "\"hubEndpoint\":\"${endpoint(server).webSocketUrl}\"," +
            "\"hubIdentity\":{\"mode\":\"usb_loopback\"," +
            "\"verifiedBy\":\"loopback_admin_session\"," +
            "\"trustedLanSupported\":false}," +
            "\"challenge\":$CHALLENGE_JSON}"

    private fun jsonResponse(status: Int, body: String): MockResponse = MockResponse.Builder()
        .code(status)
        .addHeader("Content-Type", "application/json")
        .body(body)
        .build()

    private companion object {
        const val CHALLENGE_ID = "11111111-1111-4111-8111-111111111111"
        const val CREDENTIAL_ID = "22222222-2222-4222-8222-222222222222"
        const val OTHER_CREDENTIAL_ID = "33333333-3333-4333-8333-333333333333"
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
