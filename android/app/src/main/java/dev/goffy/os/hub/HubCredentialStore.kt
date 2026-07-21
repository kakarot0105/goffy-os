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

class HubIdentityPin private constructor(
    val hubId: UUID,
    val fingerprint: String,
    val createdAt: Instant,
) {
    companion object {
        fun create(
            hubId: UUID,
            fingerprint: String,
            createdAt: Instant,
        ): HubIdentityPin {
            if (!FINGERPRINT_REGEX.matches(fingerprint)) {
                throw HubCredentialStoreException("Stored Hub identity fingerprint is invalid.")
            }
            return HubIdentityPin(hubId, fingerprint, createdAt)
        }

        const val SCHEMA_VERSION = "goffy.hub.identity.v1"
        const val VERIFIED_BY = "loopback_admin_session"
        private val FINGERPRINT_REGEX = Regex("^sha256:[0-9a-f]{64}$")
    }

    override fun toString(): String =
        "HubIdentityPin(hubId=$hubId, fingerprint=$fingerprint, createdAt=$createdAt)"
}

class StoredHubCredential private constructor(
    val endpoint: String,
    val credentialId: UUID,
    val deviceId: String,
    internal val accessToken: String,
    val createdAt: Instant,
    val tokenIssuedAt: Instant,
    val hubIdentity: HubIdentityPin,
) {
    companion object {
        fun create(
            endpoint: String,
            credentialId: UUID,
            deviceId: String,
            accessToken: String,
            createdAt: Instant,
            tokenIssuedAt: Instant = createdAt,
            hubIdentity: HubIdentityPin,
            allowInsecureLoopback: Boolean,
        ): StoredHubCredential {
            HubEndpoint.create(endpoint, allowInsecureLoopback)
            if (!DEVICE_ID_REGEX.matches(deviceId)) {
                throw HubCredentialStoreException("Stored phone identity is invalid.")
            }
            if (accessToken.length !in MIN_TOKEN_LENGTH..MAX_TOKEN_LENGTH) {
                throw HubCredentialStoreException("Stored Hub credential is invalid.")
            }
            if (tokenIssuedAt.isBefore(createdAt)) {
                throw HubCredentialStoreException("Stored Hub token issue time is invalid.")
            }
            return StoredHubCredential(
                endpoint,
                credentialId,
                deviceId,
                accessToken,
                createdAt,
                tokenIssuedAt,
                hubIdentity,
            )
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
            createdAt == other.createdAt &&
            tokenIssuedAt == other.tokenIssuedAt &&
            hubIdentity.hubId == other.hubIdentity.hubId &&
            hubIdentity.fingerprint == other.hubIdentity.fingerprint &&
            hubIdentity.createdAt == other.hubIdentity.createdAt

    override fun toString(): String =
        "StoredHubCredential(endpoint=$endpoint, credentialId=$credentialId, " +
            "deviceId=$deviceId, accessToken=REDACTED, createdAt=$createdAt, " +
            "tokenIssuedAt=$tokenIssuedAt, " +
            "hubIdentity=$hubIdentity)"
}
