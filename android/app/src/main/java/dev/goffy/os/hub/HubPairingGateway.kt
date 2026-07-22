package dev.goffy.os.hub

import java.time.Instant
import java.util.UUID

interface HubPairingGateway {
    suspend fun redeem(
        endpoint: HubEndpoint,
        challengeJson: String,
        deviceId: String,
        displayName: String,
        approvalPublicKey: ApprovalSigningPublicKey,
    ): IssuedHubCredential

    suspend fun revokeSelf(config: HubConfig, expectedCredentialId: UUID): SelfRevocationResult

    suspend fun rotateSelf(config: HubConfig, expectedCredentialId: UUID): RotatedHubCredential

    fun close()
}

data class SelfRevocationResult(
    val credentialId: UUID,
    val revoked: Boolean,
)

class HubPairingException(
    val code: String,
    message: String,
) : Exception(message)

class IssuedHubCredential(
    val credentialId: UUID,
    internal val accessToken: String,
    val createdAt: Instant,
    val hubIdentity: HubIdentityPin,
) {
    override fun toString(): String =
        "IssuedHubCredential(credentialId=$credentialId, accessToken=REDACTED, " +
            "createdAt=$createdAt, hubIdentity=$hubIdentity)"
}

class RotatedHubCredential(
    val credentialId: UUID,
    internal val accessToken: String,
    val rotatedAt: Instant,
) {
    override fun toString(): String =
        "RotatedHubCredential(credentialId=$credentialId, accessToken=REDACTED, " +
            "rotatedAt=$rotatedAt)"
}
