package dev.goffy.os.hub

import java.time.Instant
import java.util.UUID

interface HubCredentialStore {
    fun load(): HubCredentialLoadResult

    fun save(credential: StoredHubCredential): StoredHubCredential

    fun clear()
}

sealed interface HubCredentialLoadResult {
    data object Empty : HubCredentialLoadResult

    class Loaded(val credential: StoredHubCredential) : HubCredentialLoadResult {
        override fun toString(): String = "Loaded(credential=$credential)"
    }

    data object Corrupt : HubCredentialLoadResult
}

class HubCredentialStoreException(message: String, cause: Throwable? = null) :
    Exception(message, cause)

class StoredHubCredential private constructor(
    val endpoint: String,
    val credentialId: UUID,
    val deviceId: String,
    internal val accessToken: String,
    val createdAt: Instant,
) {
    companion object {
        fun create(
            endpoint: String,
            credentialId: UUID,
            deviceId: String,
            accessToken: String,
            createdAt: Instant,
            allowInsecureLoopback: Boolean,
        ): StoredHubCredential {
            HubEndpoint.create(endpoint, allowInsecureLoopback)
            if (!DEVICE_ID_REGEX.matches(deviceId)) {
                throw HubCredentialStoreException("Stored phone identity is invalid.")
            }
            if (accessToken.length !in MIN_TOKEN_LENGTH..MAX_TOKEN_LENGTH) {
                throw HubCredentialStoreException("Stored Hub credential is invalid.")
            }
            return StoredHubCredential(endpoint, credentialId, deviceId, accessToken, createdAt)
        }

        private val DEVICE_ID_REGEX = Regex("^[A-Za-z0-9._:-]{1,64}$")
        private const val MIN_TOKEN_LENGTH = 32
        private const val MAX_TOKEN_LENGTH = 4_096
    }

    fun toHubConfig(allowInsecureLoopback: Boolean): HubConfig =
        HubConfig.create(endpoint, accessToken, allowInsecureLoopback)

    internal fun sameAuthority(other: StoredHubCredential): Boolean =
        endpoint == other.endpoint &&
            credentialId == other.credentialId &&
            deviceId == other.deviceId &&
            accessToken == other.accessToken &&
            createdAt == other.createdAt

    override fun toString(): String =
        "StoredHubCredential(endpoint=$endpoint, credentialId=$credentialId, " +
            "deviceId=$deviceId, accessToken=REDACTED, createdAt=$createdAt)"
}
