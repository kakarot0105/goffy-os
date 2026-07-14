package dev.goffy.os.hub

class HubConfigurationException(message: String) : IllegalArgumentException(message)

class HubConfig private constructor(
    private val hubEndpoint: HubEndpoint,
    internal val bearerToken: String,
) {
    val endpoint: String
        get() = hubEndpoint.webSocketUrl

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
            return HubConfig(hubEndpoint = parsedEndpoint, bearerToken = bearerToken)
        }
    }

    internal val selfRevocationUrl: String
        get() = hubEndpoint.selfRevocationUrl

    internal val tokenRotationUrl: String
        get() = hubEndpoint.tokenRotationUrl

    internal val isLoopback: Boolean
        get() = hubEndpoint.isLoopback

    internal val authorizationHeaderValue: String
        get() = "Bearer $bearerToken"

    override fun toString(): String = "HubConfig(endpoint=$endpoint, bearerToken=REDACTED)"
}
