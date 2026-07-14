package dev.goffy.os.hub

import java.io.IOException
import java.time.Instant
import java.time.format.DateTimeParseException
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okio.Buffer

class OkHttpHubPairingGateway internal constructor(
    private val client: OkHttpClient,
    private val json: Json = strictJson(),
) : HubPairingGateway {
    constructor() : this(defaultClient())

    override suspend fun redeem(
        endpoint: HubEndpoint,
        challengeJson: String,
        deviceId: String,
        displayName: String,
    ): IssuedHubCredential {
        if (!endpoint.isLoopback) {
            throw HubPairingException(
                "pairing_loopback_required",
                "Phone pairing currently requires the USB loopback link.",
            )
        }
        val challenge = parseChallenge(challengeJson, endpoint.webSocketUrl)
        validateMetadata(deviceId, displayName)
        val body = buildJsonObject {
            put("challengeId", challenge.challengeId.toString())
            put("pairingToken", challenge.pairingToken)
            put("deviceId", deviceId)
            put("displayName", displayName)
        }.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url(endpoint.pairingRedemptionUrl)
            .header("Accept", "application/json")
            .post(body)
            .build()

        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        if (continuation.isActive) {
                            continuation.resumeWithException(
                                HubPairingException(
                                    "pairing_transport_failed",
                                    "The Hub pairing service could not be reached.",
                                ),
                            )
                        }
                    }

                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            if (!continuation.isActive) return
                            try {
                                continuation.resume(parseResponse(response))
                            } catch (error: HubPairingException) {
                                continuation.resumeWithException(error)
                            } catch (_: Exception) {
                                continuation.resumeWithException(invalidResponse())
                            }
                        }
                    }
                },
            )
        }
    }

    override suspend fun revokeSelf(
        config: HubConfig,
        expectedCredentialId: UUID,
    ): SelfRevocationResult {
        if (!config.isLoopback) {
            throw HubPairingException(
                "revocation_loopback_required",
                "Paired self-revocation currently requires the USB loopback link.",
            )
        }
        val request = Request.Builder()
            .url(config.selfRevocationUrl)
            .header("Accept", "application/json")
            .header("Authorization", config.authorizationHeaderValue)
            .delete()
            .build()

        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        if (continuation.isActive) {
                            continuation.resumeWithException(
                                HubPairingException(
                                    "revocation_transport_failed",
                                    "The Hub could not be reached to verify revocation.",
                                ),
                            )
                        }
                    }

                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            if (!continuation.isActive) return
                            try {
                                continuation.resume(
                                    parseRevocationResponse(response, expectedCredentialId),
                                )
                            } catch (error: HubPairingException) {
                                continuation.resumeWithException(error)
                            } catch (_: Exception) {
                                continuation.resumeWithException(invalidRevocationResponse())
                            }
                        }
                    }
                },
            )
        }
    }

    override suspend fun rotateSelf(
        config: HubConfig,
        expectedCredentialId: UUID,
    ): RotatedHubCredential {
        if (!config.isLoopback) {
            throw HubPairingException(
                "rotation_loopback_required",
                "Paired token rotation currently requires the USB loopback link.",
            )
        }
        val request = Request.Builder()
            .url(config.tokenRotationUrl)
            .header("Accept", "application/json")
            .header("Authorization", config.authorizationHeaderValue)
            .post(ByteArray(0).toRequestBody(null))
            .build()

        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        if (continuation.isActive) {
                            continuation.resumeWithException(
                                HubPairingException(
                                    "rotation_transport_failed",
                                    "The Hub could not be reached to rotate this credential.",
                                ),
                            )
                        }
                    }

                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            if (!continuation.isActive) return
                            try {
                                continuation.resume(
                                    parseRotationResponse(response, expectedCredentialId),
                                )
                            } catch (error: HubPairingException) {
                                continuation.resumeWithException(error)
                            } catch (_: Exception) {
                                continuation.resumeWithException(invalidRotationResponse())
                            }
                        }
                    }
                },
            )
        }
    }

    override fun close() {
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
    }

    private fun parseChallenge(challengeJson: String, expectedEndpoint: String): PairingChallenge {
        if (challengeJson.toByteArray(Charsets.UTF_8).size !in 1..MAX_PAIRING_JSON_BYTES) {
            throw invalidChallenge()
        }
        return try {
            val value = json.parseToJsonElement(challengeJson).jsonObject
            when (value.keys) {
                PAIRING_BUNDLE_KEYS -> parseBundleObject(value, expectedEndpoint)
                else -> throw invalidChallenge()
            }
        } catch (_: SerializationException) {
            throw invalidChallenge()
        } catch (_: IllegalArgumentException) {
            throw invalidChallenge()
        }
    }

    private fun parseBundleObject(value: JsonObject, expectedEndpoint: String): PairingChallenge {
        value.requireExactKeys(PAIRING_BUNDLE_KEYS)
        if (value.requiredString("bundleVersion") != PAIRING_BUNDLE_VERSION ||
            value.requiredString("hubEndpoint") != expectedEndpoint
        ) {
            throw invalidChallenge()
        }
        val identity = value.requiredObject("hubIdentity")
        identity.requireExactKeys(PAIRING_BUNDLE_IDENTITY_KEYS)
        if (identity.requiredString("mode") != "usb_loopback" ||
            identity.requiredString("verifiedBy") != "loopback_admin_session" ||
            identity.requiredBoolean("trustedLanSupported")
        ) {
            throw invalidChallenge()
        }
        return parseChallengeObject(value.requiredObject("challenge"))
    }

    private fun parseChallengeObject(value: JsonObject): PairingChallenge {
        value.requireExactKeys(CHALLENGE_KEYS)
        val wire = PairingChallengeWire(
            challengeId = value.requiredString("challengeId"),
            pairingToken = value.requiredString("pairingToken"),
            expiresAt = value.requiredString("expiresAt"),
        )
        val challengeId = parseCanonicalUuid(wire.challengeId) ?: throw invalidChallenge()
        if (wire.pairingToken.length !in MIN_PAIRING_TOKEN_LENGTH..MAX_PAIRING_TOKEN_LENGTH) {
            throw invalidChallenge()
        }
        try {
            Instant.parse(wire.expiresAt)
        } catch (_: DateTimeParseException) {
            throw invalidChallenge()
        }
        return PairingChallenge(challengeId, wire.pairingToken)
    }

    private fun validateMetadata(deviceId: String, displayName: String) {
        if (!DEVICE_ID_REGEX.matches(deviceId) ||
            displayName.length !in 1..MAX_DISPLAY_NAME_LENGTH ||
            displayName.any { it.code < 0x20 || it.code == 0x7F }
        ) {
            throw HubPairingException(
                "invalid_device_metadata",
                "This phone's pairing metadata is invalid.",
            )
        }
    }

    private fun parseResponse(response: Response): IssuedHubCredential {
        if (response.code != HTTP_CREATED) throw statusError(response.code)
        val contentType = response.header("Content-Type")
        if (contentType?.substringBefore(';')?.trim()?.lowercase() != "application/json") {
            throw invalidResponse()
        }
        val bytes = readBoundedBody(response, ::invalidResponse)
        val wire = try {
            val value = json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            value.requireExactKeys(SUCCESS_KEYS)
            PairingSuccessWire(
                credentialId = value.requiredString("credentialId"),
                accessToken = value.requiredString("accessToken"),
                createdAt = value.requiredString("createdAt"),
            )
        } catch (_: SerializationException) {
            throw invalidResponse()
        } catch (_: IllegalArgumentException) {
            throw invalidResponse()
        }
        val credentialId = parseCanonicalUuid(wire.credentialId) ?: throw invalidResponse()
        if (wire.accessToken.length !in MIN_ACCESS_TOKEN_LENGTH..MAX_ACCESS_TOKEN_LENGTH) {
            throw invalidResponse()
        }
        val createdAt = try {
            Instant.parse(wire.createdAt)
        } catch (_: DateTimeParseException) {
            throw invalidResponse()
        }
        return IssuedHubCredential(credentialId, wire.accessToken, createdAt)
    }

    private fun parseRevocationResponse(
        response: Response,
        expectedCredentialId: UUID,
    ): SelfRevocationResult {
        if (response.code != HTTP_OK) throw revocationStatusError(response.code)
        val contentType = response.header("Content-Type")
        if (contentType?.substringBefore(';')?.trim()?.lowercase() != "application/json") {
            throw invalidRevocationResponse()
        }
        val bytes = readBoundedBody(response, ::invalidRevocationResponse)
        val value = try {
            json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        } catch (_: Exception) {
            throw invalidRevocationResponse()
        }
        try {
            value.requireExactKeys(REVOCATION_KEYS)
        } catch (_: SerializationException) {
            throw invalidRevocationResponse()
        }
        val credentialId = parseCanonicalUuid(value.requiredString("credentialId"))
            ?: throw invalidRevocationResponse()
        if (credentialId != expectedCredentialId || !value.requiredBoolean("revoked")) {
            throw invalidRevocationResponse()
        }
        return SelfRevocationResult(credentialId, revoked = true)
    }

    private fun parseRotationResponse(
        response: Response,
        expectedCredentialId: UUID,
    ): RotatedHubCredential {
        if (response.code != HTTP_OK) throw rotationStatusError(response.code)
        val contentType = response.header("Content-Type")
        if (contentType?.substringBefore(';')?.trim()?.lowercase() != "application/json") {
            throw invalidRotationResponse()
        }
        val bytes = readBoundedBody(response, ::invalidRotationResponse)
        val value = try {
            json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        } catch (_: Exception) {
            throw invalidRotationResponse()
        }
        try {
            value.requireExactKeys(ROTATION_KEYS)
        } catch (_: SerializationException) {
            throw invalidRotationResponse()
        }
        val credentialId = parseCanonicalUuid(value.requiredString("credentialId"))
            ?: throw invalidRotationResponse()
        if (credentialId != expectedCredentialId) throw invalidRotationResponse()
        val accessToken = value.requiredString("accessToken")
        if (accessToken.length !in MIN_ACCESS_TOKEN_LENGTH..MAX_ACCESS_TOKEN_LENGTH) {
            throw invalidRotationResponse()
        }
        val rotatedAt = try {
            Instant.parse(value.requiredString("rotatedAt"))
        } catch (_: DateTimeParseException) {
            throw invalidRotationResponse()
        }
        return RotatedHubCredential(credentialId, accessToken, rotatedAt)
    }

    private fun readBoundedBody(
        response: Response,
        invalid: () -> HubPairingException,
    ): ByteArray {
        val source = response.body.source()
        val buffer = Buffer()
        while (buffer.size <= MAX_PAIRING_JSON_BYTES) {
            val remaining = MAX_PAIRING_JSON_BYTES + 1L - buffer.size
            val read = source.read(buffer, remaining.coerceAtMost(1_024L))
            if (read == -1L) return buffer.readByteArray()
        }
        throw invalid()
    }

    private fun statusError(status: Int): HubPairingException = when (status) {
        400 -> HubPairingException(
            "invalid_pairing_challenge",
            "The pairing challenge is invalid or expired.",
        )
        409 -> HubPairingException(
            "credential_capacity",
            "The Hub has reached its paired-device limit.",
        )
        429 -> HubPairingException(
            "pairing_rate_limited",
            "The Hub temporarily limited pairing attempts.",
        )
        503 -> HubPairingException(
            "pairing_unavailable",
            "The Hub pairing service is temporarily unavailable.",
        )
        else -> HubPairingException("pairing_rejected", "The Hub rejected this pairing request.")
    }

    private fun revocationStatusError(status: Int): HubPairingException = when (status) {
        401 -> HubPairingException(
            "revocation_authentication_failed",
            "The Hub did not accept this paired credential for revocation.",
        )
        403 -> HubPairingException(
            "revocation_forbidden",
            "The Hub refused paired self-revocation.",
        )
        409 -> HubPairingException(
            "revocation_not_active",
            "The Hub could not verify that this paired credential was active.",
        )
        503 -> HubPairingException(
            "revocation_unavailable",
            "The Hub credential store is unavailable for revocation.",
        )
        else -> HubPairingException(
            "revocation_rejected",
            "The Hub rejected paired self-revocation.",
        )
    }

    private fun rotationStatusError(status: Int): HubPairingException = when (status) {
        401 -> HubPairingException(
            "rotation_authentication_failed",
            "The Hub did not accept this paired credential for rotation.",
        )
        403 -> HubPairingException(
            "rotation_forbidden",
            "The Hub refused paired token rotation.",
        )
        409 -> HubPairingException(
            "rotation_conflict",
            "The Hub could not verify this credential was current before rotation.",
        )
        503 -> HubPairingException(
            "rotation_unavailable",
            "The Hub credential store is unavailable for rotation.",
        )
        else -> HubPairingException(
            "rotation_rejected",
            "The Hub rejected paired token rotation.",
        )
    }

    private fun invalidChallenge() = HubPairingException(
        "invalid_pairing_payload",
        "Paste a complete, current GOFFY pairing challenge.",
    )

    private fun invalidResponse() = HubPairingException(
        "invalid_pairing_response",
        "The Hub returned an invalid pairing response; no credential was saved.",
    )

    private fun invalidRevocationResponse() = HubPairingException(
        "invalid_revocation_response",
        "The Hub returned an invalid revocation response; remote revocation is unverified.",
    )

    private fun invalidRotationResponse() = HubPairingException(
        "invalid_rotation_response",
        "The Hub returned an invalid rotation response; Mac access is disabled until re-pairing.",
    )

    private class PairingChallenge(
        val challengeId: UUID,
        val pairingToken: String,
    ) {
        override fun toString(): String =
            "PairingChallenge(challengeId=$challengeId, pairingToken=REDACTED)"
    }

    private class PairingChallengeWire(
        val challengeId: String,
        val pairingToken: String,
        val expiresAt: String,
    ) {
        override fun toString(): String =
            "PairingChallengeWire(challengeId=$challengeId, pairingToken=REDACTED, " +
                "expiresAt=$expiresAt)"
    }

    private class PairingSuccessWire(
        val credentialId: String,
        val accessToken: String,
        val createdAt: String,
    ) {
        override fun toString(): String =
            "PairingSuccessWire(credentialId=$credentialId, accessToken=REDACTED, " +
                "createdAt=$createdAt)"
    }

    private companion object {
        const val HTTP_CREATED = 201
        const val HTTP_OK = 200
        const val MAX_PAIRING_JSON_BYTES = 2_048
        const val MIN_PAIRING_TOKEN_LENGTH = 32
        const val MAX_PAIRING_TOKEN_LENGTH = 128
        const val MIN_ACCESS_TOKEN_LENGTH = 32
        const val MAX_ACCESS_TOKEN_LENGTH = 4_096
        const val MAX_DISPLAY_NAME_LENGTH = 80
        val DEVICE_ID_REGEX = Regex("^[A-Za-z0-9._:-]{1,64}$")
        const val PAIRING_BUNDLE_VERSION = "goffy.pairing.bundle.v1"
        val CHALLENGE_KEYS = setOf("challengeId", "pairingToken", "expiresAt")
        val PAIRING_BUNDLE_KEYS = setOf(
            "bundleVersion",
            "hubEndpoint",
            "hubIdentity",
            "challenge",
        )
        val PAIRING_BUNDLE_IDENTITY_KEYS = setOf(
            "mode",
            "verifiedBy",
            "trustedLanSupported",
        )
        val SUCCESS_KEYS = setOf("credentialId", "accessToken", "createdAt")
        val REVOCATION_KEYS = setOf("credentialId", "revoked")
        val ROTATION_KEYS = setOf("credentialId", "accessToken", "rotatedAt")
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        fun strictJson() = Json {
            ignoreUnknownKeys = false
            isLenient = false
            explicitNulls = false
        }

        fun parseCanonicalUuid(value: String): UUID? = try {
            UUID.fromString(value).takeIf { it.toString().equals(value, ignoreCase = true) }
        } catch (_: IllegalArgumentException) {
            null
        }

        fun JsonObject.requireExactKeys(expected: Set<String>) {
            if (keys != expected) throw SerializationException("unexpected JSON fields")
        }

        fun JsonObject.requiredString(name: String): String {
            val primitive = get(name) as? JsonPrimitive
                ?: throw SerializationException("missing JSON string")
            if (!primitive.isString) throw SerializationException("JSON value must be a string")
            return primitive.content
        }

        fun JsonObject.requiredBoolean(name: String): Boolean {
            val primitive = get(name) as? JsonPrimitive
                ?: throw SerializationException("missing JSON Boolean")
            if (primitive.isString || primitive.content !in setOf("true", "false")) {
                throw SerializationException("JSON value must be a Boolean")
            }
            return primitive.content == "true"
        }

        fun JsonObject.requiredObject(name: String): JsonObject =
            get(name) as? JsonObject ?: throw SerializationException("missing JSON object")

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .callTimeout(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .followRedirects(false)
            .followSslRedirects(false)
            .build()
    }
}
