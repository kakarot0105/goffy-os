package dev.goffy.os.hub

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Test

class HubConfigTest {
    private val token = "test-token-that-is-long-enough"

    @Test
    fun acceptsSecureEndpointsAndExplicitInsecureLoopback() {
        val secure = HubConfig.create("wss://hub.example/ws/v1", token, allowInsecureLoopback = false)
        val localhost = HubConfig.create(
            "ws://localhost:8787/ws/v1",
            token,
            allowInsecureLoopback = true,
        )
        val ipv4 = HubConfig.create(
            "ws://127.0.0.1:8787/ws/v1",
            token,
            allowInsecureLoopback = true,
        )

        assertEquals("wss://hub.example/ws/v1", secure.endpoint)
        assertEquals("ws://localhost:8787/ws/v1", localhost.endpoint)
        assertEquals("ws://127.0.0.1:8787/ws/v1", ipv4.endpoint)
        assertFalse(secure.toString().contains(token))

        val pairingEndpoint = HubEndpoint.create(
            "ws://127.0.0.1:8787/ws/v1",
            allowInsecureLoopback = true,
        )
        assertEquals(
            "http://127.0.0.1:8787/pairing/v1/redeem",
            pairingEndpoint.pairingRedemptionUrl,
        )
        assertFalse(HubEndpoint.create("wss://hub.example/ws/v1", false).isLoopback)
    }

    @Test
    fun rejectsInvalidEndpointsAndDoesNotLeakTheToken() {
        val authError = assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("ws://example.com/ws/v1", token, allowInsecureLoopback = true)
        }

        assertFalse(authError.message.orEmpty().contains(token))

        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("wss://hub.example/ws/v1", "short-token", allowInsecureLoopback = false)
        }
        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("wss://user:pass@hub.example/ws/v1", token, allowInsecureLoopback = false)
        }
        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("wss://hub.example/ws/v1?debug=true", token, allowInsecureLoopback = false)
        }
        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("wss://hub.example/ws/v1#fragment", token, allowInsecureLoopback = false)
        }
        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("wss://hub.example/ws/v2", token, allowInsecureLoopback = false)
        }
        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("ws://localhost:8787/ws/v1", token, allowInsecureLoopback = false)
        }
        assertThrows(HubConfigurationException::class.java) {
            HubConfig.create("ws://[::1]:8787/ws/v1", token, allowInsecureLoopback = true)
        }
    }
}
