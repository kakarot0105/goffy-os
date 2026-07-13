package dev.goffy.os.hub

import java.net.URI
import java.net.URISyntaxException
import java.util.Locale

class HubConfigurationException(message: String) : IllegalArgumentException(message)

class HubConfig private constructor(
    val endpoint: String,
    internal val bearerToken: String,
) {
    companion object {
        private const val MAX_ENDPOINT_LENGTH = 2048
        private const val MIN_TOKEN_LENGTH = 24
        private const val MAX_TOKEN_LENGTH = 4096
        private const val HUB_PATH = "/ws/v1"

        fun create(
            endpoint: String,
            bearerToken: String,
            allowInsecureLoopback: Boolean,
        ): HubConfig {
            if (endpoint.isEmpty() || endpoint.length > MAX_ENDPOINT_LENGTH) {
                throw HubConfigurationException("Hub endpoint must be 1..2048 characters.")
            }
            if (bearerToken.length !in MIN_TOKEN_LENGTH..MAX_TOKEN_LENGTH) {
                throw HubConfigurationException("Hub bearer token must be 24..4096 characters.")
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

            return HubConfig(endpoint = endpoint, bearerToken = bearerToken)
        }
    }

    internal val authorizationHeaderValue: String
        get() = "Bearer $bearerToken"

    override fun toString(): String = "HubConfig(endpoint=$endpoint, bearerToken=REDACTED)"
}
