package dev.goffy.os.protocol

import java.time.Instant
import java.time.format.DateTimeParseException
import java.util.UUID
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put

const val GOFFY_PROTOCOL_VERSION = "0.1.0"
const val MAX_PROTOCOL_MESSAGE_BYTES = 32_768

enum class MessageType(val wireName: String) {
    TOOL_INVOCATION("ToolInvocation"),
    TOOL_PROGRESS("ToolProgress"),
    TOOL_RESULT("ToolResult"),
    TOOL_ERROR("ToolError"),
    VERIFICATION_RESULT("VerificationResult"),
    ;

    companion object {
        fun fromWireName(value: String): MessageType? = entries.firstOrNull { it.wireName == value }
    }
}

enum class ExecutionTarget {
    PHONE,
    MAC,
    CLOUD,
}

data class ToolInvocationRequest(
    val messageId: UUID,
    val toolName: String,
    val encodedMessage: String,
)

data class ToolProgress(
    val toolName: String,
    val executionTarget: ExecutionTarget,
    val stage: String,
    val sequence: Int,
    val message: String,
)

sealed interface ToolResultContent

data class MacSystemInfo(
    val status: String,
    val operatingSystem: String,
    val architecture: String,
) : ToolResultContent

data class PhoneBatteryStatus(
    val levelPercent: Int,
    val charging: Boolean,
) : ToolResultContent

data class PhoneDeviceInfo(
    val manufacturer: String,
    val model: String,
    val androidRelease: String,
    val sdkInt: Int,
) : ToolResultContent

sealed interface ExecutionEvent {
    data class Starting(val attempt: Int) : ExecutionEvent

    data object Ready : ExecutionEvent

    data class Progress(val payload: ToolProgress) : ExecutionEvent

    data class Result(
        val toolName: String,
        val executionTarget: ExecutionTarget,
        val content: ToolResultContent,
    ) : ExecutionEvent

    data class Verification(
        val succeeded: Boolean,
        val summary: String,
        val checks: List<String>,
    ) : ExecutionEvent

    data class Error(
        val code: String,
        val message: String,
        val retryable: Boolean,
    ) : ExecutionEvent

}

class ProtocolException(message: String) : IllegalArgumentException(message)

class GoffyProtocolCodec(
    private val now: () -> Instant = Instant::now,
    private val nextMessageId: () -> UUID = UUID::randomUUID,
) {
    private val json = Json {
        isLenient = false
        ignoreUnknownKeys = false
        explicitNulls = true
    }

    fun createToolInvocation(deviceId: String, toolName: String): ToolInvocationRequest {
        requireBounded("deviceId", deviceId, 1, 128)
        requireToolName(toolName)
        val messageId = nextMessageId()
        val root = buildJsonObject {
            put("protocolVersion", GOFFY_PROTOCOL_VERSION)
            put("messageId", messageId.toString())
            put("timestamp", now().toString())
            put("deviceId", deviceId)
            put("messageType", MessageType.TOOL_INVOCATION.wireName)
            put(
                "payload",
                buildJsonObject {
                    put("toolName", toolName)
                    put("arguments", JsonObject(emptyMap()))
                },
            )
            put("correlationId", JsonNull)
        }
        val encoded = json.encodeToString(JsonObject.serializer(), root)
        if (encoded.encodeToByteArray().size > MAX_PROTOCOL_MESSAGE_BYTES) {
            throw ProtocolException("outbound message exceeds the protocol size limit")
        }
        return ToolInvocationRequest(messageId, toolName, encoded)
    }

    fun decodeEvent(
        rawMessage: String,
        expectedCorrelationId: UUID,
        expectedToolName: String,
    ): ExecutionEvent {
        if (rawMessage.encodeToByteArray().size > MAX_PROTOCOL_MESSAGE_BYTES) {
            throw ProtocolException("inbound message exceeds the protocol size limit")
        }
        requireToolName(expectedToolName)
        val root = parseObject(rawMessage)
        root.requireKeys(ENVELOPE_REQUIRED_KEYS, ENVELOPE_OPTIONAL_KEYS)
        if (root.requireString("protocolVersion") != GOFFY_PROTOCOL_VERSION) {
            throw ProtocolException("unsupported protocol version")
        }
        parseUuid(root.requireString("messageId"), "messageId")
        parseInstant(root.requireString("timestamp"))
        requireBounded("deviceId", root.requireString("deviceId"), 1, 128)
        val messageType = MessageType.fromWireName(root.requireString("messageType"))
            ?: throw ProtocolException("unsupported message type")
        val correlationId = root.requireNullableString("correlationId")
            ?.let { parseUuid(it, "correlationId") }
            ?: throw ProtocolException("missing event correlation ID")
        if (correlationId != expectedCorrelationId) {
            throw ProtocolException("event correlation ID does not match the invocation")
        }
        val payload = root.requireObject("payload")

        return when (messageType) {
            MessageType.TOOL_PROGRESS -> decodeProgress(payload, expectedToolName)
            MessageType.TOOL_RESULT -> decodeResult(payload, expectedToolName)
            MessageType.TOOL_ERROR -> decodeError(payload)
            MessageType.VERIFICATION_RESULT -> decodeVerification(payload)
            MessageType.TOOL_INVOCATION -> throw ProtocolException("unexpected inbound invocation")
        }
    }

    private fun decodeProgress(payload: JsonObject, expectedToolName: String): ExecutionEvent {
        payload.requireKeys(PROGRESS_KEYS)
        val toolName = payload.requireString("toolName")
        requireExpectedTool(toolName, expectedToolName)
        val stage = payload.requireString("stage")
        requireBounded("stage", stage, 1, 64)
        val message = payload.requireString("message")
        requireBounded("message", message, 1, 256)
        val sequence = payload.requireInt("sequence")
        if (sequence < 0) throw ProtocolException("progress sequence cannot be negative")
        return ExecutionEvent.Progress(
            ToolProgress(
                toolName = toolName,
                executionTarget = payload.requireExecutionTarget(),
                stage = stage,
                sequence = sequence,
                message = message,
            ),
        )
    }

    private fun decodeResult(payload: JsonObject, expectedToolName: String): ExecutionEvent {
        payload.requireKeys(RESULT_KEYS)
        val toolName = payload.requireString("toolName")
        requireExpectedTool(toolName, expectedToolName)
        val target = payload.requireExecutionTarget()
        val content = payload.requireObject("structuredContent")
        val decodedContent = when (toolName) {
            MAC_SYSTEM_INFO_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.system_info returned an unexpected execution target")
                }
                content.requireKeys(SYSTEM_INFO_KEYS)
                MacSystemInfo(
                    status = content.requireBoundedString("status", 1, 64),
                    operatingSystem = content.requireBoundedString("operatingSystem", 1, 128),
                    architecture = content.requireBoundedString("architecture", 1, 128),
                )
            }
            else -> throw ProtocolException("unsupported structured tool result")
        }
        return ExecutionEvent.Result(
            toolName = toolName,
            executionTarget = target,
            content = decodedContent,
        )
    }

    private fun decodeError(payload: JsonObject): ExecutionEvent {
        payload.requireKeys(ERROR_KEYS)
        return ExecutionEvent.Error(
            code = payload.requireBoundedString("code", 1, 64),
            message = payload.requireBoundedString("message", 1, 256),
            retryable = payload.requireBoolean("retryable"),
        )
    }

    private fun decodeVerification(payload: JsonObject): ExecutionEvent {
        payload.requireKeys(VERIFICATION_KEYS)
        val checks = payload.requireArray("checks")
        if (checks.size > 16) throw ProtocolException("verification has too many checks")
        return ExecutionEvent.Verification(
            succeeded = payload.requireBoolean("succeeded"),
            summary = payload.requireBoundedString("summary", 1, 256),
            checks = checks.map { element ->
                val check = element.stringValueOrNull()
                    ?: throw ProtocolException("verification checks must be strings")
                requireBounded("verification check", check, 1, 128)
                check
            },
        )
    }

    private fun parseObject(rawMessage: String): JsonObject {
        val element = try {
            json.parseToJsonElement(rawMessage)
        } catch (_: SerializationException) {
            throw ProtocolException("message is not valid JSON")
        } catch (_: IllegalArgumentException) {
            throw ProtocolException("message is not valid JSON")
        }
        return element as? JsonObject ?: throw ProtocolException("message root must be an object")
    }

    private fun parseUuid(value: String, field: String): UUID = try {
        UUID.fromString(value)
    } catch (_: IllegalArgumentException) {
        throw ProtocolException("$field must be a UUID")
    }

    private fun parseInstant(value: String) {
        try {
            Instant.parse(value)
        } catch (_: DateTimeParseException) {
            throw ProtocolException("timestamp must be an ISO-8601 instant")
        }
    }

    private fun requireExpectedTool(actual: String, expected: String) {
        requireToolName(actual)
        if (actual != expected) throw ProtocolException("event tool does not match the invocation")
    }

    private fun JsonObject.requireExecutionTarget(): ExecutionTarget {
        val value = requireString("executionTarget")
        return ExecutionTarget.entries.firstOrNull { it.name == value }
            ?: throw ProtocolException("unsupported execution target")
    }
}

private fun JsonObject.requireKeys(required: Set<String>, optional: Set<String> = emptySet()) {
    val allowed = required + optional
    if (!keys.containsAll(required) || keys.any { it !in allowed }) {
        throw ProtocolException("message contains missing or unsupported fields")
    }
}

private fun JsonObject.requireString(key: String): String = this[key].stringValueOrNull()
    ?: throw ProtocolException("$key must be a string")

private fun JsonObject.requireNullableString(key: String): String? {
    val value = this[key] ?: return null
    if (value === JsonNull) return null
    return value.stringValueOrNull() ?: throw ProtocolException("$key must be a string or null")
}

private fun JsonObject.requireObject(key: String): JsonObject = this[key] as? JsonObject
    ?: throw ProtocolException("$key must be an object")

private fun JsonObject.requireArray(key: String): JsonArray = this[key] as? JsonArray
    ?: throw ProtocolException("$key must be an array")

private fun JsonObject.requireInt(key: String): Int = (this[key] as? JsonPrimitive)?.intOrNull
    ?: throw ProtocolException("$key must be an integer")

private fun JsonObject.requireBoolean(key: String): Boolean =
    (this[key] as? JsonPrimitive)?.booleanOrNull
        ?: throw ProtocolException("$key must be a boolean")

private fun JsonObject.requireBoundedString(key: String, minimum: Int, maximum: Int): String {
    val value = requireString(key)
    requireBounded(key, value, minimum, maximum)
    return value
}

private fun JsonElement?.stringValueOrNull(): String? {
    val primitive = this as? JsonPrimitive ?: return null
    return primitive.takeIf { it.isString }?.content
}

private fun requireToolName(value: String) {
    requireBounded("toolName", value, 1, 128)
    if (!TOOL_NAME.matches(value)) throw ProtocolException("toolName has an invalid format")
}

private fun requireBounded(field: String, value: String, minimum: Int, maximum: Int) {
    if (value.length !in minimum..maximum) {
        throw ProtocolException("$field is outside the supported length")
    }
}

private val TOOL_NAME = Regex("^[a-z][a-z0-9_.]*$")
private val ENVELOPE_REQUIRED_KEYS = setOf(
    "protocolVersion",
    "messageId",
    "timestamp",
    "deviceId",
    "messageType",
    "payload",
)
private val ENVELOPE_OPTIONAL_KEYS = setOf("correlationId")
private val PROGRESS_KEYS = setOf(
    "toolName",
    "executionTarget",
    "stage",
    "sequence",
    "message",
)
private val RESULT_KEYS = setOf("toolName", "executionTarget", "structuredContent")
private val SYSTEM_INFO_KEYS = setOf("status", "operatingSystem", "architecture")
private val ERROR_KEYS = setOf("code", "message", "retryable")
private val VERIFICATION_KEYS = setOf("succeeded", "summary", "checks")
