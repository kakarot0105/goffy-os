package dev.goffy.os.hub

import java.net.URI
import java.net.URISyntaxException
import java.util.Locale

class HubEndpoint private constructor(
    val webSocketUrl: String,
    internal val pairingRedemptionUrl: String,
    internal val selfRevocationUrl: String,
    internal val isLoopback: Boolean,
) {
    companion object {
        private const val MAX_ENDPOINT_LENGTH = 2_048
        private const val HUB_PATH = "/ws/v1"
        private const val PAIRING_PATH = "/pairing/v1/redeem"
        private const val SELF_REVOCATION_PATH = "/pairing/v1/self"

        fun create(endpoint: String, allowInsecureLoopback: Boolean): HubEndpoint {
            if (endpoint.isEmpty() || endpoint.length > MAX_ENDPOINT_LENGTH) {
                throw HubConfigurationException("Hub endpoint must be 1..2048 characters.")
            }

            val uri = try {
                URI(endpoint)
            } catch (_: URISyntaxException) {
                throw HubConfigurationException("Hub endpoint must be a valid absolute WebSocket URL.")
            }

            if (!uri.isAbsolute) {
                throw HubConfigurationException("Hub endpoint must be a valid absolute WebSocket URL.")
            }
            if (uri.userInfo != null || uri.query != null || uri.fragment != null) {
                throw HubConfigurationException(
                    "Hub endpoint must not include user info, a query string, or a fragment.",
                )
            }
            if (uri.path != HUB_PATH || uri.rawPath != HUB_PATH) {
                throw HubConfigurationException("Hub endpoint path must be exactly /ws/v1.")
            }

            val host = uri.host
                ?.lowercase(Locale.US)
                ?.removePrefix("[")
                ?.removeSuffix("]")
                ?: throw HubConfigurationException("Hub endpoint must include a host.")
            val scheme = uri.scheme.lowercase(Locale.US)
            val isLoopbackHost = host == "localhost" || host == "127.0.0.1"

            when (scheme) {
                "wss" -> Unit
                "ws" -> {
                    if (!isLoopbackHost) {
                        throw HubConfigurationException("Hub endpoint must use wss for non-loopback hosts.")
                    }
                    if (!allowInsecureLoopback) {
                        throw HubConfigurationException("Insecure loopback Hub endpoints are disabled.")
                    }
                }
                else -> throw HubConfigurationException("Hub endpoint must use ws or wss.")
            }

            val httpScheme = if (scheme == "wss") "https" else "http"
            val pairingUrl = URI(httpScheme, null, uri.host, uri.port, PAIRING_PATH, null, null)
                .toASCIIString()
            val selfRevocationUrl = URI(
                httpScheme,
                null,
                uri.host,
                uri.port,
                SELF_REVOCATION_PATH,
                null,
                null,
            ).toASCIIString()
            return HubEndpoint(endpoint, pairingUrl, selfRevocationUrl, isLoopbackHost)
        }
    }

    override fun toString(): String = "HubEndpoint(webSocketUrl=$webSocketUrl)"
}
