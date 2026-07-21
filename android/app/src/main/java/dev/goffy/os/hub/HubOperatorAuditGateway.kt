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
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

interface HubOperatorAuditGateway {
    suspend fun listSelfEvents(
        config: HubConfig,
        limit: Int = DEFAULT_HUB_OPERATOR_AUDIT_LIMIT,
    ): HubOperatorAuditSnapshot

    fun close()
}

data class HubOperatorAuditSnapshot(
    val storageKind: String,
    val integrity: String,
    val events: List<HubOperatorAuditEvent>,
)

data class HubOperatorAuditEvent(
    val sequence: Int,
    val recordedAt: Instant,
    val source: String,
    val action: String,
    val outcome: String,
    val principalKind: String,
    val credentialId: UUID?,
    val detailCode: String?,
    val previousHash: String?,
    val eventHash: String?,
)

class HubOperatorAuditException(
    val code: String,
    message: String,
) : Exception(message)

class OkHttpHubOperatorAuditGateway private constructor(
    private val client: OkHttpClient,
    private val json: Json,
    private val ownsClient: Boolean,
) : HubOperatorAuditGateway {
    constructor() : this(defaultClient(), strictJson(), ownsClient = true)

    internal constructor(
        client: OkHttpClient,
        json: Json = strictJson(),
    ) : this(client, json, ownsClient = false)

    override suspend fun listSelfEvents(
        config: HubConfig,
        limit: Int,
    ): HubOperatorAuditSnapshot {
        if (!config.isLoopback) {
            throw HubOperatorAuditException(
                "audit_loopback_required",
                "Hub audit retrieval currently requires the USB loopback link.",
            )
        }
        if (limit !in 1..MAX_AUDIT_EVENTS) {
            throw HubOperatorAuditException(
                "invalid_audit_limit",
                "Hub audit retrieval is limited to 1..$MAX_AUDIT_EVENTS events.",
            )
        }
        val url = config.operatorAuditEventsUrl.toHttpUrl().newBuilder()
            .addQueryParameter("limit", limit.toString())
            .build()
        val request = Request.Builder()
            .url(url)
            .header("Accept", "application/json")
            .header("Authorization", config.authorizationHeaderValue)
            .get()
            .build()

        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        if (continuation.isActive) {
                            continuation.resumeWithException(
                                HubOperatorAuditException(
                                    "audit_transport_failed",
                                    "The Hub audit endpoint could not be reached.",
                                ),
                            )
                        }
                    }

                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            if (!continuation.isActive) return
                            try {
                                continuation.resume(parseResponse(response))
                            } catch (error: HubOperatorAuditException) {
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
        if (!ownsClient) return
        client.dispatcher.cancelAll()
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
        client.cache?.close()
    }

    private fun parseResponse(response: Response): HubOperatorAuditSnapshot {
        if (response.code != HTTP_OK) {
            throw statusError(response.code)
        }
        val rawBody = response.peekBody((MAX_RESPONSE_BYTES + 1).toLong()).bytes()
        if (rawBody.size > MAX_RESPONSE_BYTES) throw invalidResponse()
        val root = json.parseToJsonElement(rawBody.toString(Charsets.UTF_8)).jsonObject
        root.requireExactKeys(SNAPSHOT_KEYS)
        val events = root.requiredArray("events")
        if (events.size > MAX_AUDIT_EVENTS) throw invalidResponse()
        return HubOperatorAuditSnapshot(
            storageKind = root.requiredAuditToken("storageKind"),
            integrity = root.requiredAuditToken("integrity"),
            events = events.map { parseEvent(it.jsonObject) },
        )
    }

    private fun parseEvent(value: JsonObject): HubOperatorAuditEvent {
        value.requireExactKeys(EVENT_KEYS)
        return HubOperatorAuditEvent(
            sequence = value.requiredPositiveInt("sequence"),
            recordedAt = value.requiredInstant("recordedAt"),
            source = value.requiredAuditToken("source"),
            action = value.requiredAuditToken("action"),
            outcome = value.requiredAuditToken("outcome"),
            principalKind = value.requiredAuditToken("principalKind"),
            credentialId = value.optionalUuid("credentialId"),
            detailCode = value.optionalAuditText("detailCode"),
            previousHash = value.optionalAuditText("previousHash"),
            eventHash = value.optionalAuditText("eventHash"),
        )
    }

    private fun JsonObject.requireExactKeys(expected: Set<String>) {
        if (keys != expected) throw SerializationException("unexpected JSON fields")
    }

    private fun JsonObject.requiredArray(name: String): JsonArray =
        get(name) as? JsonArray ?: throw SerializationException("missing JSON array")

    private fun JsonObject.requiredPositiveInt(name: String): Int {
        val primitive = get(name) as? JsonPrimitive
            ?: throw SerializationException("missing JSON number")
        if (primitive.isString) throw SerializationException("JSON value must be a number")
        val value = primitive.content.toIntOrNull()
            ?: throw SerializationException("JSON value must be an integer")
        if (value <= 0) throw SerializationException("JSON integer must be positive")
        return value
    }

    private fun JsonObject.requiredInstant(name: String): Instant {
        val raw = requiredString(name, MAX_TIMESTAMP_LENGTH)
        return try {
            Instant.parse(raw)
        } catch (_: DateTimeParseException) {
            throw SerializationException("JSON timestamp must be an ISO instant")
        }
    }

    private fun JsonObject.requiredAuditToken(name: String): String {
        val value = requiredString(name, MAX_AUDIT_TOKEN_LENGTH)
        if (!AUDIT_TOKEN_REGEX.matches(value)) {
            throw SerializationException("JSON audit token is invalid")
        }
        return value
    }

    private fun JsonObject.optionalAuditText(name: String): String? {
        val value = optionalString(name, MAX_AUDIT_TEXT_LENGTH) ?: return null
        if (!AUDIT_TEXT_REGEX.matches(value)) {
            throw SerializationException("JSON audit text is invalid")
        }
        return value
    }

    private fun JsonObject.optionalUuid(name: String): UUID? {
        val raw = optionalString(name, MAX_UUID_LENGTH) ?: return null
        return parseCanonicalUuid(raw)
            ?: throw SerializationException("JSON UUID is invalid")
    }

    private fun JsonObject.requiredString(name: String, maxLength: Int): String {
        val primitive = get(name) as? JsonPrimitive
            ?: throw SerializationException("missing JSON string")
        if (!primitive.isString) throw SerializationException("JSON value must be a string")
        return primitive.content.validatedString(maxLength)
    }

    private fun JsonObject.optionalString(name: String, maxLength: Int): String? {
        val value = get(name) ?: throw SerializationException("missing JSON field")
        if (value is JsonNull) return null
        val primitive = value.jsonPrimitive
        if (!primitive.isString) throw SerializationException("JSON value must be a string or null")
        return primitive.content.validatedString(maxLength)
    }

    private fun String.validatedString(maxLength: Int): String {
        if (isEmpty() || length > maxLength || any { it.code < 0x20 || it.code == 0x7F }) {
            throw SerializationException("JSON string is out of bounds")
        }
        return this
    }

    private fun statusError(status: Int): HubOperatorAuditException = when (status) {
        401 -> HubOperatorAuditException(
            "audit_authentication_failed",
            "The Hub did not accept this paired credential for audit retrieval.",
        )
        403 -> HubOperatorAuditException(
            "audit_forbidden",
            "The Hub refused paired audit retrieval.",
        )
        503 -> HubOperatorAuditException(
            "audit_unavailable",
            "The Hub audit store is temporarily unavailable.",
        )
        else -> HubOperatorAuditException("audit_rejected", "The Hub rejected audit retrieval.")
    }

    private fun invalidResponse() = HubOperatorAuditException(
        "invalid_audit_response",
        "The Hub returned an invalid audit response.",
    )

    private companion object {
        const val HTTP_OK = 200
        const val MAX_RESPONSE_BYTES = 96 * 1024
        const val MAX_AUDIT_EVENTS = 20
        const val MAX_AUDIT_TOKEN_LENGTH = 64
        const val MAX_AUDIT_TEXT_LENGTH = 128
        const val MAX_TIMESTAMP_LENGTH = 40
        const val MAX_UUID_LENGTH = 36
        val AUDIT_TOKEN_REGEX = Regex("^[A-Za-z0-9._:-]+$")
        val AUDIT_TEXT_REGEX = Regex("^[A-Za-z0-9._:-]+$")
        val SNAPSHOT_KEYS = setOf("storageKind", "integrity", "events")
        val EVENT_KEYS = setOf(
            "sequence",
            "recordedAt",
            "source",
            "action",
            "outcome",
            "principalKind",
            "credentialId",
            "detailCode",
            "previousHash",
            "eventHash",
        )

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

const val DEFAULT_HUB_OPERATOR_AUDIT_LIMIT = 20
