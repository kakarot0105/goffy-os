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
        val challenge = parseChallenge(challengeJson)
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

    override fun close() {
        client.dispatcher.cancelAll()
        client.connectionPool.evictAll()
    }

    private fun parseChallenge(challengeJson: String): PairingChallenge {
        if (challengeJson.toByteArray(Charsets.UTF_8).size !in 1..MAX_PAIRING_JSON_BYTES) {
            throw invalidChallenge()
        }
        val wire = try {
            val value = json.parseToJsonElement(challengeJson).jsonObject
            value.requireExactKeys(CHALLENGE_KEYS)
            PairingChallengeWire(
                challengeId = value.requiredString("challengeId"),
                pairingToken = value.requiredString("pairingToken"),
                expiresAt = value.requiredString("expiresAt"),
            )
        } catch (_: SerializationException) {
            throw invalidChallenge()
        } catch (_: IllegalArgumentException) {
            throw invalidChallenge()
        }
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
        val bytes = readBoundedBody(response)
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

    private fun readBoundedBody(response: Response): ByteArray {
        val source = response.body.source()
        val buffer = Buffer()
        while (buffer.size <= MAX_PAIRING_JSON_BYTES) {
            val remaining = MAX_PAIRING_JSON_BYTES + 1L - buffer.size
            val read = source.read(buffer, remaining.coerceAtMost(1_024L))
            if (read == -1L) return buffer.readByteArray()
        }
        throw invalidResponse()
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

    private fun invalidChallenge() = HubPairingException(
        "invalid_pairing_payload",
        "Paste a complete, current GOFFY pairing challenge.",
    )

    private fun invalidResponse() = HubPairingException(
        "invalid_pairing_response",
        "The Hub returned an invalid pairing response; no credential was saved.",
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
        const val MAX_PAIRING_JSON_BYTES = 2_048
        const val MIN_PAIRING_TOKEN_LENGTH = 32
        const val MAX_PAIRING_TOKEN_LENGTH = 128
        const val MIN_ACCESS_TOKEN_LENGTH = 32
        const val MAX_ACCESS_TOKEN_LENGTH = 4_096
        const val MAX_DISPLAY_NAME_LENGTH = 80
        val DEVICE_ID_REGEX = Regex("^[A-Za-z0-9._:-]{1,64}$")
        val CHALLENGE_KEYS = setOf("challengeId", "pairingToken", "expiresAt")
        val SUCCESS_KEYS = setOf("credentialId", "accessToken", "createdAt")
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

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .callTimeout(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }
}
