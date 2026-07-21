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

const val GOFFY_PROTOCOL_VERSION = "0.2.0"
const val MCP_PROTOCOL_VERSION = "2025-11-25"
const val MAC_SYSTEM_INFO_TOOL_VERSION = "1.0.0"
const val MAC_FILES_LIST_TOOL_VERSION = "1.0.0"
const val MAX_PROTOCOL_MESSAGE_BYTES = 32_768

enum class MessageType(val wireName: String) {
    CAPABILITY_DISCOVERY_REQUEST("CapabilityDiscoveryRequest"),
    CAPABILITY_DISCOVERY_RESPONSE("CapabilityDiscoveryResponse"),
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

enum class PermissionLevel {
    SAFE,
    CONFIRM,
    SENSITIVE,
    BLOCKED,
}

data class ToolInvocationRequest(
    val messageId: UUID,
    val toolName: String,
    val encodedMessage: String,
    val discoveryMessageId: UUID,
    val encodedDiscoveryMessage: String,
)

data class DiscoveredToolCapability(
    val name: String,
    val toolVersion: String,
    val executionTarget: ExecutionTarget,
    val permission: String,
    val timeoutMillis: Int,
)

sealed interface CapabilityDiscoveryMessage {
    data class Response(val capability: DiscoveredToolCapability?) : CapabilityDiscoveryMessage

    data class Error(val event: ExecutionEvent.Error) : CapabilityDiscoveryMessage
}

data class ToolProgress(
    val toolName: String,
    val executionTarget: ExecutionTarget,
    val stage: String,
    val sequence: Int,
    val message: String,
)

sealed interface ToolResultContent

sealed interface ToolArguments

data object NoToolArguments : ToolArguments

data class MacFilesListArguments(
    val rootIndex: Int = 0,
    val relativePath: String = "",
    val maxEntries: Int = DEFAULT_MAC_FILES_LIST_ENTRIES,
    val includeHidden: Boolean = false,
) : ToolArguments

data class PhoneNoteCreateArguments(
    val text: String,
) : ToolArguments

data class PhoneTimerCreateArguments(
    val durationSeconds: Int,
    val skipClockUi: Boolean,
) : ToolArguments

data class PhoneFlashlightSetArguments(
    val enabled: Boolean,
) : ToolArguments

data class MacSystemInfo(
    val status: String,
    val operatingSystem: String,
    val architecture: String,
) : ToolResultContent

data class MacFilesApprovedRoot(
    val rootIndex: Int,
    val name: String,
)

data class MacFilesListEntry(
    val name: String,
    val nameTruncated: Boolean,
    val kind: String,
    val sizeBytes: Int?,
    val modifiedEpochSeconds: Int?,
)

data class MacFilesList(
    val status: String,
    val rootIndex: Int,
    val rootName: String,
    val relativePath: String,
    val truncated: Boolean,
    val approvedRoots: List<MacFilesApprovedRoot>,
    val entries: List<MacFilesListEntry>,
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
    val goffySystemApp: Boolean = false,
    val goffyHomeCandidate: Boolean = false,
    val goffyDefaultHome: Boolean = false,
) : ToolResultContent

data class PhoneNoteCreated(
    val noteId: Long,
    val text: String,
    val createdAtEpochMillis: Long,
) : ToolResultContent

data class PhoneTimerDispatched(
    val durationSeconds: Int,
    val clockPackage: String,
    val clockActivity: String,
    val systemApplication: Boolean,
    val skipClockUiRequested: Boolean,
    val systemAction: String,
) : ToolResultContent

data class PhoneFlashlightState(
    val enabled: Boolean,
    val stateChanged: Boolean,
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

    data class Unverified(
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

    fun createToolInvocation(
        deviceId: String,
        toolName: String,
        arguments: ToolArguments = NoToolArguments,
    ): ToolInvocationRequest {
        requireBounded("deviceId", deviceId, 1, 128)
        requireToolName(toolName)
        val encodedArguments = encodeToolArguments(toolName, arguments)
        val messageId = nextMessageId()
        val discoveryMessageId = nextMessageId()
        if (discoveryMessageId == messageId) {
            throw ProtocolException("discovery and invocation IDs must be unique")
        }
        val invocationPayload = buildJsonObject {
            put("toolName", toolName)
            put("arguments", encodedArguments)
        }
        val discoveryPayload = buildJsonObject { put("toolName", toolName) }
        val encodedDiscoveryMessage = encodeEnvelope(
            messageId = discoveryMessageId,
            deviceId = deviceId,
            messageType = MessageType.CAPABILITY_DISCOVERY_REQUEST,
            payload = discoveryPayload,
        )
        val encodedMessage = encodeEnvelope(
            messageId = messageId,
            deviceId = deviceId,
            messageType = MessageType.TOOL_INVOCATION,
            payload = invocationPayload,
        )
        return ToolInvocationRequest(
            messageId = messageId,
            toolName = toolName,
            encodedMessage = encodedMessage,
            discoveryMessageId = discoveryMessageId,
            encodedDiscoveryMessage = encodedDiscoveryMessage,
        )
    }

    private fun encodeToolArguments(toolName: String, arguments: ToolArguments): JsonObject =
        when (toolName) {
            MAC_SYSTEM_INFO_TOOL -> {
                if (arguments !is NoToolArguments) {
                    throw ProtocolException("mac.system_info does not accept arguments")
                }
                JsonObject(emptyMap())
            }
            MAC_FILES_LIST_TOOL -> {
                val value = arguments as? MacFilesListArguments
                    ?: throw ProtocolException("mac.files.list requires typed arguments")
                if (!value.matchesToolContract()) {
                    throw ProtocolException("mac.files.list arguments failed local policy")
                }
                buildJsonObject {
                    put("rootIndex", value.rootIndex)
                    put("relativePath", value.relativePath)
                    put("maxEntries", value.maxEntries)
                    put("includeHidden", value.includeHidden)
                }
            }
            else -> throw ProtocolException("unsupported invocation tool")
        }

    private fun encodeEnvelope(
        messageId: UUID,
        deviceId: String,
        messageType: MessageType,
        payload: JsonObject,
    ): String {
        val root = buildJsonObject {
            put("protocolVersion", GOFFY_PROTOCOL_VERSION)
            put("messageId", messageId.toString())
            put("timestamp", now().toString())
            put("deviceId", deviceId)
            put("messageType", messageType.wireName)
            put("payload", payload)
            put("correlationId", JsonNull)
        }
        val encoded = json.encodeToString(JsonObject.serializer(), root)
        if (encoded.encodeToByteArray().size > MAX_PROTOCOL_MESSAGE_BYTES) {
            throw ProtocolException("outbound message exceeds the protocol size limit")
        }
        return encoded
    }

    fun decodeEvent(
        rawMessage: String,
        expectedCorrelationId: UUID,
        expectedToolName: String,
    ): ExecutionEvent {
        requireToolName(expectedToolName)
        val envelope = decodeInboundEnvelope(rawMessage, expectedCorrelationId)

        return when (envelope.messageType) {
            MessageType.TOOL_PROGRESS -> decodeProgress(envelope.payload, expectedToolName)
            MessageType.TOOL_RESULT -> decodeResult(envelope.payload, expectedToolName)
            MessageType.TOOL_ERROR -> decodeError(envelope.payload)
            MessageType.VERIFICATION_RESULT -> decodeVerification(envelope.payload)
            MessageType.CAPABILITY_DISCOVERY_REQUEST,
            MessageType.CAPABILITY_DISCOVERY_RESPONSE,
            MessageType.TOOL_INVOCATION,
            -> throw ProtocolException("unexpected inbound message type")
        }
    }

    fun decodeCapabilityDiscovery(
        rawMessage: String,
        expectedCorrelationId: UUID,
        expectedToolName: String,
    ): CapabilityDiscoveryMessage {
        requireToolName(expectedToolName)
        val envelope = decodeInboundEnvelope(rawMessage, expectedCorrelationId)
        return when (envelope.messageType) {
            MessageType.CAPABILITY_DISCOVERY_RESPONSE ->
                decodeCapabilityResponse(envelope.payload, expectedToolName)
            MessageType.TOOL_ERROR -> CapabilityDiscoveryMessage.Error(decodeError(envelope.payload))
            MessageType.CAPABILITY_DISCOVERY_REQUEST,
            MessageType.TOOL_INVOCATION,
            MessageType.TOOL_PROGRESS,
            MessageType.TOOL_RESULT,
            MessageType.VERIFICATION_RESULT,
            -> throw ProtocolException("unexpected discovery response type")
        }
    }

    private fun decodeInboundEnvelope(
        rawMessage: String,
        expectedCorrelationId: UUID,
    ): DecodedEnvelope {
        if (rawMessage.encodeToByteArray().size > MAX_PROTOCOL_MESSAGE_BYTES) {
            throw ProtocolException("inbound message exceeds the protocol size limit")
        }
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
            throw ProtocolException("event correlation ID does not match the request")
        }
        return DecodedEnvelope(messageType, root.requireObject("payload"))
    }

    private fun decodeCapabilityResponse(
        payload: JsonObject,
        expectedToolName: String,
    ): CapabilityDiscoveryMessage.Response {
        payload.requireKeys(CAPABILITY_RESPONSE_KEYS)
        if (payload.requireString("mcpProtocolVersion") != MCP_PROTOCOL_VERSION) {
            throw ProtocolException("unsupported MCP metadata version")
        }
        if (payload.requireBoolean("listChanged")) {
            throw ProtocolException("dynamic capability lists are not supported")
        }
        val tools = payload.requireArray("tools")
        if (tools.size > 1) throw ProtocolException("discovery returned too many tools")
        if (tools.isEmpty()) return CapabilityDiscoveryMessage.Response(capability = null)
        val tool = tools.single() as? JsonObject
            ?: throw ProtocolException("discovered tool must be an object")
        tool.requireKeys(TOOL_CAPABILITY_KEYS)
        val toolName = tool.requireString("name")
        requireExpectedTool(toolName, expectedToolName)
        tool.requireBoundedString("title", 1, 128)
        tool.requireBoundedString("description", 1, 512)
        when (toolName) {
            MAC_SYSTEM_INFO_TOOL -> {
                validateSystemInfoInputSchema(tool.requireObject("inputSchema"))
                validateSystemInfoOutputSchema(tool.requireObject("outputSchema"))
            }
            MAC_FILES_LIST_TOOL -> {
                validateMacFilesListInputSchema(tool.requireObject("inputSchema"))
                validateMacFilesListOutputSchema(tool.requireObject("outputSchema"))
            }
            else -> throw ProtocolException("unsupported discovered tool")
        }
        validateSafeReadOnlyAnnotations(tool.requireObject("annotations"))

        val metadata = tool.requireObject("_meta")
        metadata.requireKeys(GOFFY_METADATA_KEYS)
        val toolVersion = metadata.requireString("dev.goffy/toolVersion")
        val expectedToolVersion = when (toolName) {
            MAC_SYSTEM_INFO_TOOL -> MAC_SYSTEM_INFO_TOOL_VERSION
            MAC_FILES_LIST_TOOL -> MAC_FILES_LIST_TOOL_VERSION
            else -> throw ProtocolException("unsupported discovered tool")
        }
        if (toolVersion != expectedToolVersion) {
            throw ProtocolException("unsupported tool contract version")
        }
        val target = metadata.requireExecutionTarget("dev.goffy/executionTarget")
        if (target != ExecutionTarget.MAC) {
            throw ProtocolException("discovered tool has an unexpected execution target")
        }
        val permission = metadata.requireString("dev.goffy/permission")
        if (permission != "SAFE") {
            throw ProtocolException("discovered tool has an unexpected permission")
        }
        val timeoutMillis = metadata.requireInt("dev.goffy/timeoutMs")
        if (timeoutMillis !in 1..MAX_DISCOVERED_TIMEOUT_MILLIS) {
            throw ProtocolException("discovered tool timeout is outside the client policy")
        }
        return CapabilityDiscoveryMessage.Response(
            DiscoveredToolCapability(
                name = toolName,
                toolVersion = toolVersion,
                executionTarget = target,
                permission = permission,
                timeoutMillis = timeoutMillis,
            ),
        )
    }

    private fun validateSystemInfoInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        schema.requireObject("properties").requireKeys(emptySet())
    }

    private fun validateSystemInfoOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(SYSTEM_INFO_KEYS)
        SYSTEM_INFO_KEYS.forEach { field ->
            val fieldSchema = properties.requireObject(field)
            fieldSchema.requireKeys(STRING_SCHEMA_KEYS)
            if (fieldSchema.requireString("type") != "string") {
                throw ProtocolException("system information field schema must be a string")
            }
        }
        schema.requireArray("required").requireExactStrings(SYSTEM_INFO_KEYS, "required")
    }

    private fun validateMacFilesListInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_FILES_LIST_INPUT_KEYS)
        properties.requireObject("rootIndex").also { rootIndex ->
            rootIndex.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "exclusiveMaximum" + "default")
            rootIndex.requireType("integer")
            rootIndex.requireInt("minimum").requireExactValue(0, "rootIndex minimum")
            rootIndex.requireInt("exclusiveMaximum").requireExactValue(
                MAX_MAC_FILES_APPROVED_ROOTS,
                "rootIndex maximum",
            )
        }
        properties.requireObject("relativePath").also { relativePath ->
            relativePath.requireKeys(STRING_SCHEMA_KEYS + "maxLength" + "default")
            relativePath.requireType("string")
            relativePath.requireInt("maxLength").requireExactValue(
                MAX_MAC_FILES_RELATIVE_PATH_LENGTH,
                "relativePath maxLength",
            )
        }
        properties.requireObject("maxEntries").also { maxEntries ->
            maxEntries.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum" + "default")
            maxEntries.requireType("integer")
            maxEntries.requireInt("minimum").requireExactValue(1, "maxEntries minimum")
            maxEntries.requireInt("maximum").requireExactValue(
                MAX_MAC_FILES_LIST_ENTRIES,
                "maxEntries maximum",
            )
        }
        properties.requireObject("includeHidden").also { includeHidden ->
            includeHidden.requireKeys(BOOLEAN_SCHEMA_KEYS + "default")
            includeHidden.requireType("boolean")
        }
    }

    private fun validateMacFilesListOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS + "\$defs")
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_FILES_LIST_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(MAC_FILES_LIST_OUTPUT_KEYS, "required")

        properties.requireObject("approvedRoots").also { approvedRoots ->
            approvedRoots.requireKeys(ARRAY_REF_SCHEMA_KEYS + "maxItems")
            approvedRoots.requireType("array")
            approvedRoots.requireInt("maxItems").requireExactValue(
                MAX_MAC_FILES_APPROVED_ROOTS,
                "approvedRoots maxItems",
            )
            approvedRoots.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/MacFilesApprovedRootOutput",
                "approvedRoots ref",
            )
        }
        properties.requireObject("entries").also { entries ->
            entries.requireKeys(ARRAY_REF_SCHEMA_KEYS + "maxItems")
            entries.requireType("array")
            entries.requireInt("maxItems").requireExactValue(
                MAX_MAC_FILES_LIST_ENTRIES,
                "entries maxItems",
            )
            entries.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/MacFilesListEntryOutput",
                "entries ref",
            )
        }
        setOf("status", "rootName", "relativePath").forEach { field ->
            properties.requireObject(field).requireTypeOnly("string")
        }
        properties.requireObject("rootIndex").requireTypeOnly("integer")
        properties.requireObject("truncated").requireTypeOnly("boolean")

        val definitions = schema.requireObject("\$defs")
        definitions.requireKeys(MAC_FILES_LIST_DEFINITION_KEYS)
        validateMacFilesApprovedRootDefinition(definitions.requireObject("MacFilesApprovedRootOutput"))
        validateMacFilesEntryDefinition(definitions.requireObject("MacFilesListEntryOutput"))
    }

    private fun validateMacFilesApprovedRootDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(MAC_FILES_APPROVED_ROOT_KEYS)
        properties.requireObject("rootIndex").requireTypeOnly("integer")
        properties.requireObject("name").requireTypeOnly("string")
        definition.requireArray("required")
            .requireExactStrings(MAC_FILES_APPROVED_ROOT_KEYS, "approved root required")
    }

    private fun validateMacFilesEntryDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(MAC_FILES_ENTRY_KEYS)
        properties.requireObject("name").requireTypeOnly("string")
        properties.requireObject("nameTruncated").requireTypeOnly("boolean")
        properties.requireObject("kind").also { kind ->
            kind.requireKeys(ENUM_STRING_SCHEMA_KEYS)
            kind.requireType("string")
            kind.requireArray("enum").requireExactStrings(MAC_FILES_ENTRY_KINDS, "entry kind enum")
        }
        properties.requireObject("sizeBytes").validateNullableIntegerSchema()
        properties.requireObject("modifiedEpochSeconds").validateNullableIntegerSchema()
        definition.requireArray("required").requireExactStrings(MAC_FILES_ENTRY_KEYS, "entry required")
    }

    private fun validateObjectSchemaRoot(schema: JsonObject) {
        if (schema.requireString("\$schema") != JSON_SCHEMA_DIALECT ||
            !schema.isObjectSchemaRoot()
        ) {
            throw ProtocolException("tool schema is incompatible with the local contract")
        }
    }

    private fun validateObjectSchemaRootWithoutDialect(schema: JsonObject) {
        if (!schema.isObjectSchemaRoot()) {
            throw ProtocolException("tool schema is incompatible with the local contract")
        }
    }

    private fun JsonObject.isObjectSchemaRoot(): Boolean =
        requireString("type") == "object" && !requireBoolean("additionalProperties")

    private fun validateSafeReadOnlyAnnotations(annotations: JsonObject) {
        annotations.requireKeys(ANNOTATION_KEYS)
        if (!annotations.requireBoolean("readOnlyHint") ||
            annotations.requireBoolean("destructiveHint") ||
            !annotations.requireBoolean("idempotentHint") ||
            annotations.requireBoolean("openWorldHint")
        ) {
            throw ProtocolException("tool annotations are incompatible with the local policy")
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
            MAC_FILES_LIST_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.files.list returned an unexpected execution target")
                }
                decodeMacFilesList(content)
            }
            else -> throw ProtocolException("unsupported structured tool result")
        }
        return ExecutionEvent.Result(
            toolName = toolName,
            executionTarget = target,
            content = decodedContent,
        )
    }

    private fun decodeError(payload: JsonObject): ExecutionEvent.Error {
        payload.requireKeys(ERROR_KEYS)
        return ExecutionEvent.Error(
            code = payload.requireBoundedString("code", 1, 64),
            message = payload.requireBoundedString("message", 1, 256),
            retryable = payload.requireBoolean("retryable"),
        )
    }

    private fun decodeMacFilesList(content: JsonObject): MacFilesList {
        content.requireKeys(MAC_FILES_LIST_OUTPUT_KEYS)
        val approvedRoots = content.requireArray("approvedRoots").boundedObjects(
            maximum = MAX_MAC_FILES_APPROVED_ROOTS,
            field = "approvedRoots",
        ) { root ->
            root.requireKeys(MAC_FILES_APPROVED_ROOT_KEYS)
            MacFilesApprovedRoot(
                rootIndex = root.requireBoundedInt("rootIndex", 0, MAX_MAC_FILES_ROOT_INDEX),
                name = root.requireBoundedString("name", 1, MAX_MAC_FILES_ROOT_NAME_LENGTH),
            )
        }
        val entries = content.requireArray("entries").boundedObjects(
            maximum = MAX_MAC_FILES_LIST_ENTRIES,
            field = "entries",
        ) { entry ->
            entry.requireKeys(MAC_FILES_ENTRY_KEYS)
            MacFilesListEntry(
                name = entry.requireBoundedString("name", 1, MAX_MAC_FILES_ENTRY_NAME_LENGTH),
                nameTruncated = entry.requireBoolean("nameTruncated"),
                kind = entry.requireString("kind").also { kind ->
                    if (kind !in MAC_FILES_ENTRY_KINDS) {
                        throw ProtocolException("unsupported Mac file entry kind")
                    }
                },
                sizeBytes = entry.requireNullableInt("sizeBytes")?.also { size ->
                    if (size < 0) throw ProtocolException("sizeBytes cannot be negative")
                },
                modifiedEpochSeconds = entry.requireNullableInt("modifiedEpochSeconds")
                    ?.also { modified ->
                        if (modified < 0) {
                            throw ProtocolException("modifiedEpochSeconds cannot be negative")
                        }
                    },
            )
        }
        return MacFilesList(
            status = content.requireBoundedString("status", 1, 64),
            rootIndex = content.requireBoundedInt("rootIndex", 0, MAX_MAC_FILES_ROOT_INDEX),
            rootName = content.requireBoundedString("rootName", 1, MAX_MAC_FILES_ROOT_NAME_LENGTH),
            relativePath = content.requireBoundedString(
                "relativePath",
                0,
                MAX_MAC_FILES_RELATIVE_PATH_LENGTH,
            ),
            truncated = content.requireBoolean("truncated"),
            approvedRoots = approvedRoots,
            entries = entries,
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
        return requireExecutionTarget("executionTarget")
    }

    private fun JsonObject.requireExecutionTarget(key: String): ExecutionTarget {
        val value = requireString(key)
        return ExecutionTarget.entries.firstOrNull { it.name == value }
            ?: throw ProtocolException("unsupported execution target")
    }

    private data class DecodedEnvelope(
        val messageType: MessageType,
        val payload: JsonObject,
    )
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

private fun JsonObject.requireNullableInt(key: String): Int? {
    val value = this[key] ?: return null
    if (value === JsonNull) return null
    return (value as? JsonPrimitive)?.intOrNull ?: throw ProtocolException("$key must be an integer or null")
}

private fun JsonObject.requireBoolean(key: String): Boolean =
    (this[key] as? JsonPrimitive)?.booleanOrNull
        ?: throw ProtocolException("$key must be a boolean")

private fun JsonObject.requireType(expected: String) {
    if (requireString("type") != expected) {
        throw ProtocolException("schema type does not match the local contract")
    }
}

private fun JsonObject.requireTypeOnly(expected: String) {
    requireKeys(setOf("type"))
    requireType(expected)
}

private fun JsonObject.validateNullableIntegerSchema() {
    requireKeys(setOf("anyOf"))
    val anyOf = requireArray("anyOf")
    if (anyOf.size != 2) throw ProtocolException("nullable integer schema is incompatible")
    val types = anyOf.map { element ->
        val schema = element as? JsonObject
            ?: throw ProtocolException("nullable integer schema entries must be objects")
        schema.requireKeys(setOf("type"))
        schema.requireString("type")
    }.toSet()
    if (types != setOf("integer", "null")) {
        throw ProtocolException("nullable integer schema is incompatible")
    }
}

private fun JsonArray.requireExactStrings(expected: Set<String>, field: String) {
    val values = map { element ->
        element.stringValueOrNull()
            ?: throw ProtocolException("$field entries must be strings")
    }
    if (values.size != expected.size || values.toSet() != expected) {
        throw ProtocolException("$field entries do not match the local contract")
    }
}

private fun Int.requireExactValue(expected: Int, field: String) {
    if (this != expected) {
        throw ProtocolException("$field does not match the local contract")
    }
}

private fun String.requireExactString(expected: String, field: String) {
    if (this != expected) {
        throw ProtocolException("$field does not match the local contract")
    }
}

private fun JsonObject.requireBoundedInt(key: String, minimum: Int, maximum: Int): Int {
    val value = requireInt(key)
    if (value !in minimum..maximum) {
        throw ProtocolException("$key is outside the supported range")
    }
    return value
}

private fun <T> JsonArray.boundedObjects(
    maximum: Int,
    field: String,
    decode: (JsonObject) -> T,
): List<T> {
    if (size > maximum) throw ProtocolException("$field has too many entries")
    return map { element ->
        decode(element as? JsonObject ?: throw ProtocolException("$field entries must be objects"))
    }
}

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
private val MAC_FILES_LIST_INPUT_KEYS = setOf(
    "rootIndex",
    "relativePath",
    "maxEntries",
    "includeHidden",
)
private val MAC_FILES_LIST_OUTPUT_KEYS = setOf(
    "status",
    "rootIndex",
    "rootName",
    "relativePath",
    "truncated",
    "approvedRoots",
    "entries",
)
private val MAC_FILES_LIST_DEFINITION_KEYS = setOf(
    "MacFilesApprovedRootOutput",
    "MacFilesListEntryOutput",
)
private val MAC_FILES_APPROVED_ROOT_KEYS = setOf("rootIndex", "name")
private val MAC_FILES_ENTRY_KEYS = setOf(
    "name",
    "nameTruncated",
    "kind",
    "sizeBytes",
    "modifiedEpochSeconds",
)
private val ERROR_KEYS = setOf("code", "message", "retryable")
private val VERIFICATION_KEYS = setOf("succeeded", "summary", "checks")
private const val JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
private const val MAX_DISCOVERED_TIMEOUT_MILLIS = 30_000
private val CAPABILITY_RESPONSE_KEYS = setOf("mcpProtocolVersion", "listChanged", "tools")
private val TOOL_CAPABILITY_KEYS = setOf(
    "name",
    "title",
    "description",
    "inputSchema",
    "outputSchema",
    "annotations",
    "_meta",
)
private val GOFFY_METADATA_KEYS = setOf(
    "dev.goffy/toolVersion",
    "dev.goffy/executionTarget",
    "dev.goffy/permission",
    "dev.goffy/timeoutMs",
)
private val ANNOTATION_KEYS = setOf(
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
)
private val EMPTY_INPUT_SCHEMA_KEYS = setOf(
    "\$schema",
    "type",
    "additionalProperties",
    "properties",
)
private val OUTPUT_SCHEMA_KEYS = EMPTY_INPUT_SCHEMA_KEYS + "required"
private val STRING_SCHEMA_KEYS = setOf("type")
private val BOOLEAN_SCHEMA_KEYS = setOf("type")
private val INTEGER_BOUNDED_SCHEMA_KEYS = setOf("type", "minimum")
private val ARRAY_REF_SCHEMA_KEYS = setOf("type", "items")
private val OBJECT_DEFINITION_KEYS = setOf("type", "additionalProperties", "properties", "required")
private val ENUM_STRING_SCHEMA_KEYS = setOf("type", "enum")
