package dev.goffy.os.hub

import java.time.Instant
import java.util.UUID

interface HubPairingGateway {
    suspend fun redeem(
        endpoint: HubEndpoint,
        challengeJson: String,
        deviceId: String,
        displayName: String,
    ): IssuedHubCredential

    fun close()
}

class HubPairingException(
    val code: String,
    message: String,
) : Exception(message)

class IssuedHubCredential(
    val credentialId: UUID,
    internal val accessToken: String,
    val createdAt: Instant,
) {
    override fun toString(): String =
        "IssuedHubCredential(credentialId=$credentialId, accessToken=REDACTED, createdAt=$createdAt)"
}
