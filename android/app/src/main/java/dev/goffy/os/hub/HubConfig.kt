package dev.goffy.os.hub

class HubConfigurationException(message: String) : IllegalArgumentException(message)

class HubConfig private constructor(
    val endpoint: String,
    internal val bearerToken: String,
) {
    companion object {
        private const val MIN_TOKEN_LENGTH = 24
        private const val MAX_TOKEN_LENGTH = 4096

        fun create(
            endpoint: String,
            bearerToken: String,
            allowInsecureLoopback: Boolean,
        ): HubConfig {
            if (bearerToken.length !in MIN_TOKEN_LENGTH..MAX_TOKEN_LENGTH) {
                throw HubConfigurationException("Hub bearer token must be 24..4096 characters.")
            }
            val parsedEndpoint = HubEndpoint.create(endpoint, allowInsecureLoopback)
            return HubConfig(endpoint = parsedEndpoint.webSocketUrl, bearerToken = bearerToken)
        }
    }

    internal val authorizationHeaderValue: String
        get() = "Bearer $bearerToken"

    override fun toString(): String = "HubConfig(endpoint=$endpoint, bearerToken=REDACTED)"
}
