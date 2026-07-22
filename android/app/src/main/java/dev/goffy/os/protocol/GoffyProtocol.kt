package dev.goffy.os.protocol

import java.security.MessageDigest
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
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

const val GOFFY_PROTOCOL_VERSION = "0.2.0"
const val MCP_PROTOCOL_VERSION = "2025-11-25"
const val MAC_SYSTEM_INFO_TOOL_VERSION = "1.0.0"
const val MAC_FILES_LARGEST_TOOL_VERSION = "1.0.0"
const val MAC_FILES_LIST_TOOL_VERSION = "1.0.0"
const val MAC_CLIPBOARD_READ_TOOL_VERSION = "1.0.0"
const val MAC_PROCESSES_LIST_TOOL_VERSION = "1.0.0"
const val MAC_APPS_LIST_TOOL_VERSION = "1.0.0"
const val MAC_APPS_OPEN_TOOL_VERSION = "1.0.0"
const val GIT_STATUS_TOOL_VERSION = "1.0.0"
const val MAX_PROTOCOL_MESSAGE_BYTES = 32_768
const val APPROVAL_PROOF_SCHEMA_VERSION = "goffy.approval.proof.v1"
const val APPROVAL_PROOF_ALGORITHM = "ECDSA_P256_SHA256"
const val APPROVAL_SIGNING_PAYLOAD_SCHEMA_VERSION = "goffy.approval.signed-payload.v1"
const val MIN_APPROVAL_SIGNATURE_BASE64_LENGTH = 64
const val MAX_APPROVAL_SIGNATURE_BASE64_LENGTH = 512

enum class MessageType(val wireName: String) {
    CAPABILITY_DISCOVERY_REQUEST("CapabilityDiscoveryRequest"),
    CAPABILITY_DISCOVERY_RESPONSE("CapabilityDiscoveryResponse"),
    APPROVAL_REQUEST("ApprovalRequest"),
    APPROVAL_RESPONSE("ApprovalResponse"),
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
    val expiresAtEpochMillis: Long? = null,
    val deviceId: String = "android-test",
    val approvedTaskId: UUID? = null,
    val approvedCredentialId: UUID? = null,
    val approvedArgumentsSha256: String? = null,
)

data class ToolApprovalGrant(
    val taskId: UUID,
    val credentialId: UUID,
    val issuedAtEpochMillis: Long,
    val expiresAtEpochMillis: Long,
)

data class HubApprovalRequest(
    val approvalId: UUID,
    val taskId: UUID,
    val toolName: String,
    val argumentsSha256: String,
    val issuedAtEpochMillis: Long,
    val expiresAtEpochMillis: Long,
)

data class ApprovalResponseProof(
    val algorithm: String,
    val publicKeySha256: String,
    val signatureBase64: String,
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

data class MacProcessesListArguments(
    val maxEntries: Int = DEFAULT_MAC_PROCESS_ENTRIES,
) : ToolArguments

data class MacAppsListArguments(
    val maxEntries: Int = DEFAULT_MAC_APP_ENTRIES,
) : ToolArguments

data class MacAppsOpenArguments(
    val displayName: String,
) : ToolArguments

data class MacFilesListArguments(
    val rootIndex: Int = 0,
    val relativePath: String = "",
    val maxEntries: Int = DEFAULT_MAC_FILES_LIST_ENTRIES,
    val includeHidden: Boolean = false,
) : ToolArguments

data class MacFilesLargestArguments(
    val rootIndex: Int = 0,
    val relativePath: String = "",
    val maxEntries: Int = DEFAULT_MAC_FILES_LARGEST_ENTRIES,
    val maxDepth: Int = DEFAULT_MAC_FILES_LARGEST_DEPTH,
    val includeHidden: Boolean = false,
) : ToolArguments

data class GitStatusArguments(
    val repoIndex: Int = 0,
    val maxChanges: Int = DEFAULT_GIT_STATUS_CHANGES,
    val includeUntracked: Boolean = true,
) : ToolArguments

data class PhoneNoteCreateArguments(
    val text: String,
) : ToolArguments

data class PhoneMemoryRememberArguments(
    val text: String,
) : ToolArguments

data class PhoneMemoryForgetArguments(
    val memoryId: Long,
) : ToolArguments

data class PhoneMemoryUpdateArguments(
    val memoryId: Long,
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

data class MacProcessEntry(
    val pid: Int,
    val name: String,
    val status: String,
    val rssBytes: Long,
    val createTimeEpochSeconds: Long?,
)

data class MacProcessesList(
    val status: String,
    val processCount: Int,
    val skippedCount: Int,
    val truncated: Boolean,
    val entries: List<MacProcessEntry>,
) : ToolResultContent

data class MacAppCatalogEntry(
    val appIndex: Int,
    val displayName: String,
    val bundleId: String,
)

data class MacAppsList(
    val status: String,
    val appCount: Int,
    val truncated: Boolean,
    val entries: List<MacAppCatalogEntry>,
) : ToolResultContent

data class MacAppOpened(
    val status: String,
    val displayName: String,
    val bundleId: String,
    val verified: Boolean,
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
    val modifiedEpochSeconds: Long?,
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

data class MacFilesLargestEntry(
    val relativePath: String,
    val pathTruncated: Boolean,
    val name: String,
    val nameTruncated: Boolean,
    val sizeBytes: Long,
    val modifiedEpochSeconds: Long?,
)

data class MacFilesLargest(
    val status: String,
    val rootIndex: Int,
    val rootName: String,
    val relativePath: String,
    val maxDepth: Int,
    val scannedEntries: Int,
    val skippedEntries: Int,
    val truncated: Boolean,
    val approvedRoots: List<MacFilesApprovedRoot>,
    val entries: List<MacFilesLargestEntry>,
) : ToolResultContent

data class GitStatusApprovedRepo(
    val repoIndex: Int,
    val name: String,
)

data class GitStatusChange(
    val path: String,
    val pathTruncated: Boolean,
    val indexStatus: String,
    val workingTreeStatus: String,
    val kind: String,
)

data class GitStatus(
    val status: String,
    val repoIndex: Int,
    val repoName: String,
    val branch: String?,
    val headOidShort: String?,
    val upstream: String?,
    val ahead: Int?,
    val behind: Int?,
    val clean: Boolean,
    val stagedCount: Int,
    val unstagedCount: Int,
    val untrackedCount: Int,
    val conflictCount: Int,
    val truncated: Boolean,
    val approvedRepos: List<GitStatusApprovedRepo>,
    val changes: List<GitStatusChange>,
) : ToolResultContent

data class MacClipboardRead(
    val status: String,
    val contentType: String,
    val text: String?,
    val textTruncated: Boolean,
    val characterCount: Int,
    val characterCountTruncated: Boolean,
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

data class PhoneQrRead(
    val status: String,
    val contentType: String,
    val characterCount: Int,
    val characterCountTruncated: Boolean,
    val preview: String?,
    val previewTruncated: Boolean,
    val redacted: Boolean,
) : ToolResultContent

data class PhoneOcrRead(
    val status: String,
    val script: String,
    val characterCount: Int,
    val characterCountTruncated: Boolean,
    val lineCount: Int,
    val lineCountTruncated: Boolean,
    val preview: String?,
    val previewTruncated: Boolean,
    val redacted: Boolean,
) : ToolResultContent

data class PhoneNoteCreated(
    val noteId: Long,
    val text: String,
    val createdAtEpochMillis: Long,
) : ToolResultContent

data class PhoneMemoryRemembered(
    val memoryId: Long,
    val text: String,
    val createdAtEpochMillis: Long,
    val provenance: String,
) : ToolResultContent

data class PhoneMemoryEntry(
    val memoryId: Long,
    val text: String,
    val createdAtEpochMillis: Long,
    val provenance: String,
)

data class PhoneMemoryList(
    val status: String,
    val count: Int,
    val truncated: Boolean,
    val entries: List<PhoneMemoryEntry>,
) : ToolResultContent

data class PhoneMemoryForgotten(
    val deletedCount: Int,
    val remainingCount: Int,
) : ToolResultContent

data class PhoneMemoryDeleted(
    val memoryId: Long,
    val deletedCount: Int,
    val remainingCount: Int,
) : ToolResultContent

data class PhoneMemoryUpdated(
    val memoryId: Long,
    val text: String,
    val createdAtEpochMillis: Long,
    val provenance: String,
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
        expiresAtEpochMillis: Long? = null,
        approvalGrant: ToolApprovalGrant? = null,
    ): ToolInvocationRequest {
        requireBounded("deviceId", deviceId, 1, 128)
        requireToolName(toolName)
        val requestExpiresAt = approvalGrant?.expiresAtEpochMillis ?: expiresAtEpochMillis
        if (requestExpiresAt != null && requestExpiresAt <= 0L) {
            throw ProtocolException("invocation deadline must be positive")
        }
        val encodedArguments = encodeToolArguments(toolName, arguments)
        if (approvalGrant != null) {
            requireApprovalGrant(approvalGrant)
        }
        val argumentsSha256 = approvalGrant?.let { sha256Hex(canonicalJson(encodedArguments)) }
        val messageId = nextMessageId()
        val discoveryMessageId = nextMessageId()
        if (discoveryMessageId == messageId) {
            throw ProtocolException("discovery and invocation IDs must be unique")
        }
        val invocationPayload = buildJsonObject {
            put("toolName", toolName)
            put("arguments", encodedArguments)
            if (approvalGrant != null) {
                put("taskId", approvalGrant.taskId.toString())
            }
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
            expiresAtEpochMillis = requestExpiresAt,
            deviceId = deviceId,
            approvedTaskId = approvalGrant?.taskId,
            approvedCredentialId = approvalGrant?.credentialId,
            approvedArgumentsSha256 = argumentsSha256,
        )
    }

    private fun requireApprovalGrant(approvalGrant: ToolApprovalGrant) {
        if (approvalGrant.expiresAtEpochMillis <= approvalGrant.issuedAtEpochMillis) {
            throw ProtocolException("approval grant must expire after it is issued")
        }
    }

    fun createApprovalResponse(
        deviceId: String,
        correlationId: UUID,
        approvalRequest: HubApprovalRequest,
        approved: Boolean = true,
        proof: ApprovalResponseProof? = null,
    ): String {
        requireBounded("deviceId", deviceId, 1, 128)
        requireToolName(approvalRequest.toolName)
        proof?.let(::requireApprovalResponseProof)
        val payload = buildJsonObject {
            put("schemaVersion", "goffy.approval.v1")
            put("approvalId", approvalRequest.approvalId.toString())
            put("taskId", approvalRequest.taskId.toString())
            put("approved", approved)
            if (proof != null) {
                put("proof", buildJsonObject {
                    put("schemaVersion", APPROVAL_PROOF_SCHEMA_VERSION)
                    put("algorithm", proof.algorithm)
                    put("publicKeySha256", proof.publicKeySha256)
                    put("signatureBase64", proof.signatureBase64)
                })
            }
        }
        return encodeEnvelope(
            messageId = nextMessageId(),
            deviceId = deviceId,
            messageType = MessageType.APPROVAL_RESPONSE,
            payload = payload,
            correlationId = correlationId,
        )
    }

    private fun requireApprovalResponseProof(proof: ApprovalResponseProof) {
        proof.algorithm.requireExactString(APPROVAL_PROOF_ALGORITHM, "approval proof algorithm")
        if (!SHA256_HEX.matches(proof.publicKeySha256)) {
            throw ProtocolException("approval proof public key hash is invalid")
        }
        if (
            proof.signatureBase64.length !in MIN_APPROVAL_SIGNATURE_BASE64_LENGTH..MAX_APPROVAL_SIGNATURE_BASE64_LENGTH ||
            !BASE64.matches(proof.signatureBase64)
        ) {
            throw ProtocolException("approval proof signature is invalid")
        }
    }

    fun approvalSigningPayload(
        approvalRequest: HubApprovalRequest,
        credentialId: UUID,
        approved: Boolean = true,
    ): ByteArray {
        requireToolName(approvalRequest.toolName)
        val payload = buildJsonObject {
            put("schemaVersion", APPROVAL_SIGNING_PAYLOAD_SCHEMA_VERSION)
            put("approvalId", approvalRequest.approvalId.toString())
            put("argumentsSha256", approvalRequest.argumentsSha256)
            put("approved", approved)
            put("credentialId", credentialId.toString())
            put("expiresAtEpochMillis", approvalRequest.expiresAtEpochMillis)
            put("issuedAtEpochMillis", approvalRequest.issuedAtEpochMillis)
            put("taskId", approvalRequest.taskId.toString())
            put("toolName", approvalRequest.toolName)
        }
        return canonicalJson(payload).toByteArray(Charsets.UTF_8)
    }

    private fun encodeToolArguments(toolName: String, arguments: ToolArguments): JsonObject =
        when (toolName) {
            MAC_SYSTEM_INFO_TOOL -> {
                if (arguments !is NoToolArguments) {
                    throw ProtocolException("mac.system_info does not accept arguments")
                }
                JsonObject(emptyMap())
            }
            MAC_CLIPBOARD_READ_TOOL -> {
                if (arguments !is NoToolArguments) {
                    throw ProtocolException("mac.clipboard.read does not accept Android arguments")
                }
                JsonObject(emptyMap())
            }
            MAC_APPS_LIST_TOOL -> {
                val value = arguments as? MacAppsListArguments
                    ?: throw ProtocolException("mac.apps.list requires typed arguments")
                if (!value.matchesToolContract()) {
                    throw ProtocolException("mac.apps.list arguments failed local policy")
                }
                buildJsonObject {
                    put("maxEntries", value.maxEntries)
                }
            }
            MAC_APPS_OPEN_TOOL -> {
                val value = arguments as? MacAppsOpenArguments
                    ?: throw ProtocolException("mac.apps.open requires typed arguments")
                if (!value.matchesToolContract()) {
                    throw ProtocolException("mac.apps.open arguments failed local policy")
                }
                buildJsonObject {
                    put("displayName", value.displayName)
                }
            }
            MAC_PROCESSES_LIST_TOOL -> {
                val value = arguments as? MacProcessesListArguments
                    ?: throw ProtocolException("mac.processes.list requires typed arguments")
                if (!value.matchesToolContract()) {
                    throw ProtocolException("mac.processes.list arguments failed local policy")
                }
                buildJsonObject {
                    put("maxEntries", value.maxEntries)
                }
            }
            MAC_FILES_LARGEST_TOOL -> {
                val value = arguments as? MacFilesLargestArguments
                    ?: throw ProtocolException("mac.files.largest requires typed arguments")
                if (!value.matchesToolContract()) {
                    throw ProtocolException("mac.files.largest arguments failed local policy")
                }
                buildJsonObject {
                    put("rootIndex", value.rootIndex)
                    put("relativePath", value.relativePath)
                    put("maxEntries", value.maxEntries)
                    put("maxDepth", value.maxDepth)
                    put("includeHidden", value.includeHidden)
                }
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
            GIT_STATUS_TOOL -> {
                val value = arguments as? GitStatusArguments
                    ?: throw ProtocolException("git.status requires typed arguments")
                if (!value.matchesToolContract()) {
                    throw ProtocolException("git.status arguments failed local policy")
                }
                buildJsonObject {
                    put("repoIndex", value.repoIndex)
                    put("maxChanges", value.maxChanges)
                    put("includeUntracked", value.includeUntracked)
                }
            }
            else -> throw ProtocolException("unsupported invocation tool")
        }

    private fun encodeEnvelope(
        messageId: UUID,
        deviceId: String,
        messageType: MessageType,
        payload: JsonObject,
        correlationId: UUID? = null,
    ): String {
        val root = buildJsonObject {
            put("protocolVersion", GOFFY_PROTOCOL_VERSION)
            put("messageId", messageId.toString())
            put("timestamp", now().toString())
            put("deviceId", deviceId)
            put("messageType", messageType.wireName)
            put("payload", payload)
            put("correlationId", correlationId?.toString()?.let(::JsonPrimitive) ?: JsonNull)
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
            MessageType.APPROVAL_REQUEST,
            MessageType.APPROVAL_RESPONSE,
            MessageType.CAPABILITY_DISCOVERY_REQUEST,
            MessageType.CAPABILITY_DISCOVERY_RESPONSE,
            MessageType.TOOL_INVOCATION,
            -> throw ProtocolException("unexpected inbound message type")
        }
    }

    fun decodeApprovalRequestOrNull(
        rawMessage: String,
        expectedCorrelationId: UUID,
        expectedToolName: String,
        expectedTaskId: UUID?,
        expectedArgumentsSha256: String?,
    ): HubApprovalRequest? {
        if (expectedTaskId == null || expectedArgumentsSha256 == null) {
            return null
        }
        requireToolName(expectedToolName)
        val envelope = decodeInboundEnvelope(rawMessage, expectedCorrelationId)
        if (envelope.messageType != MessageType.APPROVAL_REQUEST) {
            return null
        }
        val payload = envelope.payload
        payload.requireKeys(APPROVAL_REQUEST_KEYS)
        payload.requireString("schemaVersion").requireExactString(
            "goffy.approval.v1",
            "approval schema version",
        )
        val approvalId = parseUuid(payload.requireString("approvalId"), "approvalId")
        val taskId = parseUuid(payload.requireString("taskId"), "taskId")
        if (taskId != expectedTaskId) {
            throw ProtocolException("approval request task does not match the approved task")
        }
        val toolName = payload.requireString("toolName")
        requireExpectedTool(toolName, expectedToolName)
        val argumentsSha256 = payload.requireString("argumentsSha256")
        if (!SHA256_HEX.matches(argumentsSha256)) {
            throw ProtocolException("approval request argument hash is invalid")
        }
        if (argumentsSha256 != expectedArgumentsSha256) {
            throw ProtocolException("approval request arguments do not match the approved task")
        }
        val expiresAt = payload.requireLong("expiresAtEpochMillis")
        if (expiresAt <= 0L) {
            throw ProtocolException("approval request expiry is invalid")
        }
        val issuedAt = payload.requireLong("issuedAtEpochMillis")
        if (expiresAt <= issuedAt) {
            throw ProtocolException("approval request expiry is invalid")
        }
        return HubApprovalRequest(
            approvalId = approvalId,
            taskId = taskId,
            toolName = toolName,
            argumentsSha256 = argumentsSha256,
            issuedAtEpochMillis = issuedAt,
            expiresAtEpochMillis = expiresAt,
        )
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
            MessageType.APPROVAL_REQUEST,
            MessageType.APPROVAL_RESPONSE,
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
            MAC_FILES_LARGEST_TOOL -> {
                validateMacFilesLargestInputSchema(tool.requireObject("inputSchema"))
                validateMacFilesLargestOutputSchema(tool.requireObject("outputSchema"))
            }
            MAC_FILES_LIST_TOOL -> {
                validateMacFilesListInputSchema(tool.requireObject("inputSchema"))
                validateMacFilesListOutputSchema(tool.requireObject("outputSchema"))
            }
            MAC_CLIPBOARD_READ_TOOL -> {
                validateMacClipboardReadInputSchema(tool.requireObject("inputSchema"))
                validateMacClipboardReadOutputSchema(tool.requireObject("outputSchema"))
            }
            MAC_APPS_LIST_TOOL -> {
                validateMacAppsListInputSchema(tool.requireObject("inputSchema"))
                validateMacAppsListOutputSchema(tool.requireObject("outputSchema"))
            }
            MAC_APPS_OPEN_TOOL -> {
                validateMacAppsOpenInputSchema(tool.requireObject("inputSchema"))
                validateMacAppsOpenOutputSchema(tool.requireObject("outputSchema"))
            }
            MAC_PROCESSES_LIST_TOOL -> {
                validateMacProcessesListInputSchema(tool.requireObject("inputSchema"))
                validateMacProcessesListOutputSchema(tool.requireObject("outputSchema"))
            }
            GIT_STATUS_TOOL -> {
                validateGitStatusInputSchema(tool.requireObject("inputSchema"))
                validateGitStatusOutputSchema(tool.requireObject("outputSchema"))
            }
            else -> throw ProtocolException("unsupported discovered tool")
        }
        val metadata = tool.requireObject("_meta")
        metadata.requireKeys(GOFFY_METADATA_KEYS)
        val toolVersion = metadata.requireString("dev.goffy/toolVersion")
        val expectedToolVersion = when (toolName) {
            MAC_SYSTEM_INFO_TOOL -> MAC_SYSTEM_INFO_TOOL_VERSION
            MAC_FILES_LARGEST_TOOL -> MAC_FILES_LARGEST_TOOL_VERSION
            MAC_FILES_LIST_TOOL -> MAC_FILES_LIST_TOOL_VERSION
            MAC_CLIPBOARD_READ_TOOL -> MAC_CLIPBOARD_READ_TOOL_VERSION
            MAC_PROCESSES_LIST_TOOL -> MAC_PROCESSES_LIST_TOOL_VERSION
            MAC_APPS_LIST_TOOL -> MAC_APPS_LIST_TOOL_VERSION
            MAC_APPS_OPEN_TOOL -> MAC_APPS_OPEN_TOOL_VERSION
            GIT_STATUS_TOOL -> GIT_STATUS_TOOL_VERSION
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
        val expectedPermission = when (toolName) {
            MAC_APPS_OPEN_TOOL -> "CONFIRM"
            else -> "SAFE"
        }
        if (permission != expectedPermission) {
            throw ProtocolException("discovered tool has an unexpected permission")
        }
        validateToolAnnotations(tool.requireObject("annotations"), expectedPermission)
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

    private fun validateMacFilesLargestInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_FILES_LARGEST_INPUT_KEYS)
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
                MAX_MAC_FILES_LARGEST_ENTRIES,
                "maxEntries maximum",
            )
            maxEntries.requireInt("default").requireExactValue(
                DEFAULT_MAC_FILES_LARGEST_ENTRIES,
                "maxEntries default",
            )
        }
        properties.requireObject("maxDepth").also { maxDepth ->
            maxDepth.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum" + "default")
            maxDepth.requireType("integer")
            maxDepth.requireInt("minimum").requireExactValue(0, "maxDepth minimum")
            maxDepth.requireInt("maximum").requireExactValue(
                MAX_MAC_FILES_LARGEST_DEPTH,
                "maxDepth maximum",
            )
            maxDepth.requireInt("default").requireExactValue(
                DEFAULT_MAC_FILES_LARGEST_DEPTH,
                "maxDepth default",
            )
        }
        properties.requireObject("includeHidden").also { includeHidden ->
            includeHidden.requireKeys(BOOLEAN_SCHEMA_KEYS + "default")
            includeHidden.requireType("boolean")
        }
    }

    private fun validateMacFilesLargestOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS + "\$defs")
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_FILES_LARGEST_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(MAC_FILES_LARGEST_OUTPUT_KEYS, "required")

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
                MAX_MAC_FILES_LARGEST_ENTRIES,
                "entries maxItems",
            )
            entries.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/MacFilesLargestEntryOutput",
                "entries ref",
            )
        }
        setOf("status", "rootName", "relativePath").forEach { field ->
            properties.requireObject(field).requireTypeOnly("string")
        }
        setOf("rootIndex", "maxDepth").forEach { field ->
            properties.requireObject(field).requireTypeOnly("integer")
        }
        setOf("scannedEntries", "skippedEntries").forEach { field ->
            properties.requireObject(field).validateNonNegativeIntegerSchema(field)
        }
        properties.requireObject("truncated").requireTypeOnly("boolean")

        val definitions = schema.requireObject("\$defs")
        definitions.requireKeys(MAC_FILES_LARGEST_DEFINITION_KEYS)
        validateMacFilesApprovedRootDefinition(definitions.requireObject("MacFilesApprovedRootOutput"))
        validateMacFilesLargestEntryDefinition(definitions.requireObject("MacFilesLargestEntryOutput"))
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

    private fun validateMacFilesLargestEntryDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(MAC_FILES_LARGEST_ENTRY_KEYS)
        properties.requireObject("relativePath").requireTypeOnly("string")
        properties.requireObject("pathTruncated").requireTypeOnly("boolean")
        properties.requireObject("name").requireTypeOnly("string")
        properties.requireObject("nameTruncated").requireTypeOnly("boolean")
        properties.requireObject("sizeBytes").validateNonNegativeIntegerSchema("sizeBytes")
        properties.requireObject("modifiedEpochSeconds").validateNullableIntegerSchema()
        definition.requireArray("required").requireExactStrings(
            MAC_FILES_LARGEST_ENTRY_KEYS,
            "largest file entry required",
        )
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

    private fun validateMacClipboardReadInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_CLIPBOARD_READ_INPUT_KEYS)
        properties.requireObject("maxChars").also { maxChars ->
            maxChars.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum" + "default")
            maxChars.requireType("integer")
            maxChars.requireInt("minimum").requireExactValue(1, "maxChars minimum")
            maxChars.requireInt("maximum").requireExactValue(
                MAX_MAC_CLIPBOARD_TEXT_LENGTH,
                "maxChars maximum",
            )
            maxChars.requireInt("default").requireExactValue(
                DEFAULT_MAC_CLIPBOARD_READ_CHARS,
                "maxChars default",
            )
        }
    }

    private fun validateMacClipboardReadOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_CLIPBOARD_READ_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(
            MAC_CLIPBOARD_READ_REQUIRED_KEYS,
            "clipboard required",
        )

        properties.requireObject("status").also { status ->
            status.requireKeys(ENUM_STRING_SCHEMA_KEYS)
            status.requireType("string")
            status.requireArray("enum").requireExactStrings(
                MAC_CLIPBOARD_STATUS_VALUES,
                "clipboard status enum",
            )
        }
        properties.requireObject("contentType").also { contentType ->
            contentType.requireKeys(setOf("const", "default", "type"))
            contentType.requireType("string")
            contentType.requireString("const").requireExactString("text", "contentType const")
            contentType.requireString("default").requireExactString("text", "contentType default")
        }
        properties.requireObject("text").validateNullableBoundedStringSchema(
            "clipboard text",
            MAX_MAC_CLIPBOARD_TEXT_LENGTH,
        )
        properties.requireObject("textTruncated").requireTypeOnly("boolean")
        properties.requireObject("characterCount").also { characterCount ->
            characterCount.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum")
            characterCount.requireType("integer")
            characterCount.requireInt("minimum").requireExactValue(0, "characterCount minimum")
            characterCount.requireInt("maximum").requireExactValue(
                MAX_MAC_CLIPBOARD_CHARACTER_COUNT,
                "characterCount maximum",
            )
        }
        properties.requireObject("characterCountTruncated").requireTypeOnly("boolean")
    }

    private fun validateMacAppsListInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_APPS_LIST_INPUT_KEYS)
        properties.requireObject("maxEntries").also { maxEntries ->
            maxEntries.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum" + "default")
            maxEntries.requireType("integer")
            maxEntries.requireInt("minimum").requireExactValue(1, "maxEntries minimum")
            maxEntries.requireInt("maximum").requireExactValue(
                MAX_MAC_APP_ENTRIES,
                "maxEntries maximum",
            )
            maxEntries.requireInt("default").requireExactValue(
                DEFAULT_MAC_APP_ENTRIES,
                "maxEntries default",
            )
        }
    }

    private fun validateMacAppsListOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS + "\$defs")
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_APPS_LIST_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(
            MAC_APPS_LIST_OUTPUT_KEYS,
            "app list required",
        )
        properties.requireObject("status").validateBoundedStringSchema(
            "status",
            1,
            MAX_MAC_APP_STATUS_LENGTH,
        )
        properties.requireObject("appCount").validateBoundedIntInclusiveSchema(
            "appCount",
            0,
            MAX_MAC_APP_COUNT,
        )
        properties.requireObject("truncated").requireTypeOnly("boolean")
        properties.requireObject("entries").also { entries ->
            entries.requireKeys(ARRAY_REF_SCHEMA_KEYS + "maxItems")
            entries.requireType("array")
            entries.requireInt("maxItems").requireExactValue(
                MAX_MAC_APP_ENTRIES,
                "entries maxItems",
            )
            entries.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/MacAppCatalogEntryOutput",
                "entries ref",
            )
        }

        val definitions = schema.requireObject("\$defs")
        definitions.requireKeys(setOf("MacAppCatalogEntryOutput"))
        validateMacAppCatalogEntryDefinition(
            definitions.requireObject("MacAppCatalogEntryOutput"),
        )
    }

    private fun validateMacAppCatalogEntryDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(MAC_APP_CATALOG_ENTRY_KEYS)
        properties.requireObject("appIndex").validateBoundedIntegerSchema(
            "appIndex",
            0,
            MAX_MAC_APP_ENTRIES,
        )
        properties.requireObject("displayName").validateBoundedStringSchema(
            "displayName",
            1,
            MAX_MAC_APP_DISPLAY_NAME_LENGTH,
        )
        properties.requireObject("bundleId").validateBoundedStringSchema(
            "bundleId",
            1,
            MAX_MAC_APP_BUNDLE_ID_LENGTH,
        )
        definition.requireArray("required").requireExactStrings(
            MAC_APP_CATALOG_ENTRY_KEYS,
            "app catalog entry required",
        )
    }

    private fun validateMacAppsOpenInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS + "required")
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_APPS_OPEN_INPUT_KEYS)
        schema.requireArray("required").requireExactStrings(
            MAC_APPS_OPEN_INPUT_KEYS,
            "app open input required",
        )
        properties.requireObject("displayName").validateBoundedStringSchema(
            "displayName",
            1,
            MAX_MAC_APP_DISPLAY_NAME_LENGTH,
        )
    }

    private fun validateMacAppsOpenOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_APPS_OPEN_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(
            MAC_APPS_OPEN_OUTPUT_KEYS,
            "app open required",
        )
        properties.requireObject("status").validateBoundedStringSchema(
            "status",
            1,
            MAX_MAC_APP_STATUS_LENGTH,
        )
        properties.requireObject("displayName").validateBoundedStringSchema(
            "displayName",
            1,
            MAX_MAC_APP_DISPLAY_NAME_LENGTH,
        )
        properties.requireObject("bundleId").validateBoundedStringSchema(
            "bundleId",
            1,
            MAX_MAC_APP_BUNDLE_ID_LENGTH,
        )
        properties.requireObject("verified").requireTypeOnly("boolean")
    }

    private fun validateMacProcessesListInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_PROCESSES_LIST_INPUT_KEYS)
        properties.requireObject("maxEntries").also { maxEntries ->
            maxEntries.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum" + "default")
            maxEntries.requireType("integer")
            maxEntries.requireInt("minimum").requireExactValue(1, "maxEntries minimum")
            maxEntries.requireInt("maximum").requireExactValue(
                MAX_MAC_PROCESS_ENTRIES,
                "maxEntries maximum",
            )
            maxEntries.requireInt("default").requireExactValue(
                DEFAULT_MAC_PROCESS_ENTRIES,
                "maxEntries default",
            )
        }
    }

    private fun validateMacProcessesListOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS + "\$defs")
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(MAC_PROCESSES_LIST_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(
            MAC_PROCESSES_LIST_OUTPUT_KEYS,
            "process list required",
        )

        properties.requireObject("status").validateBoundedStringSchema(
            "status",
            1,
            MAX_MAC_PROCESS_STATUS_TEXT_LENGTH,
        )
        properties.requireObject("processCount").validateBoundedIntInclusiveSchema(
            "processCount",
            0,
            MAX_MAC_PROCESS_COUNT,
        )
        properties.requireObject("skippedCount").validateBoundedIntInclusiveSchema(
            "skippedCount",
            0,
            MAX_MAC_PROCESS_COUNT,
        )
        properties.requireObject("truncated").requireTypeOnly("boolean")
        properties.requireObject("entries").also { entries ->
            entries.requireKeys(ARRAY_REF_SCHEMA_KEYS + "maxItems")
            entries.requireType("array")
            entries.requireInt("maxItems").requireExactValue(
                MAX_MAC_PROCESS_ENTRIES,
                "entries maxItems",
            )
            entries.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/MacProcessEntryOutput",
                "entries ref",
            )
        }

        val definitions = schema.requireObject("\$defs")
        definitions.requireKeys(setOf("MacProcessEntryOutput"))
        validateMacProcessEntryDefinition(definitions.requireObject("MacProcessEntryOutput"))
    }

    private fun validateMacProcessEntryDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(MAC_PROCESS_ENTRY_KEYS)
        properties.requireObject("pid").validateBoundedIntInclusiveSchema(
            "pid",
            0,
            MAX_MAC_PROCESS_PID,
        )
        properties.requireObject("name").validateBoundedStringSchema(
            "process name",
            1,
            MAX_MAC_PROCESS_NAME_LENGTH,
        )
        properties.requireObject("status").validateBoundedStringSchema(
            "process status",
            1,
            MAX_MAC_PROCESS_STATUS_LENGTH,
        )
        properties.requireObject("rssBytes").validateBoundedLongSchema(
            "rssBytes",
            0,
            MAX_MAC_PROCESS_RSS_BYTES,
        )
        properties.requireObject("createTimeEpochSeconds").validateNullableNonNegativeIntegerSchema(
            "createTimeEpochSeconds",
        )
        definition.requireArray("required").requireExactStrings(
            MAC_PROCESS_ENTRY_REQUIRED_KEYS,
            "process entry required",
        )
    }

    private fun validateGitStatusInputSchema(schema: JsonObject) {
        schema.requireKeys(EMPTY_INPUT_SCHEMA_KEYS)
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(GIT_STATUS_INPUT_KEYS)
        properties.requireObject("repoIndex").also { repoIndex ->
            repoIndex.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "exclusiveMaximum" + "default")
            repoIndex.requireType("integer")
            repoIndex.requireInt("minimum").requireExactValue(0, "repoIndex minimum")
            repoIndex.requireInt("exclusiveMaximum").requireExactValue(
                MAX_GIT_STATUS_REPOS,
                "repoIndex maximum",
            )
        }
        properties.requireObject("maxChanges").also { maxChanges ->
            maxChanges.requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum" + "default")
            maxChanges.requireType("integer")
            maxChanges.requireInt("minimum").requireExactValue(1, "maxChanges minimum")
            maxChanges.requireInt("maximum").requireExactValue(
                MAX_GIT_STATUS_CHANGES,
                "maxChanges maximum",
            )
        }
        properties.requireObject("includeUntracked").also { includeUntracked ->
            includeUntracked.requireKeys(BOOLEAN_SCHEMA_KEYS + "default")
            includeUntracked.requireType("boolean")
        }
    }

    private fun validateGitStatusOutputSchema(schema: JsonObject) {
        schema.requireKeys(OUTPUT_SCHEMA_KEYS + "\$defs")
        validateObjectSchemaRoot(schema)
        val properties = schema.requireObject("properties")
        properties.requireKeys(GIT_STATUS_OUTPUT_KEYS)
        schema.requireArray("required").requireExactStrings(GIT_STATUS_REQUIRED_KEYS, "required")

        properties.requireObject("approvedRepos").also { approvedRepos ->
            approvedRepos.requireKeys(ARRAY_REF_SCHEMA_KEYS + "maxItems")
            approvedRepos.requireType("array")
            approvedRepos.requireInt("maxItems").requireExactValue(
                MAX_GIT_STATUS_REPOS,
                "approvedRepos maxItems",
            )
            approvedRepos.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/GitStatusApprovedRepoOutput",
                "approvedRepos ref",
            )
        }
        properties.requireObject("changes").also { changes ->
            changes.requireKeys(ARRAY_REF_SCHEMA_KEYS + "maxItems")
            changes.requireType("array")
            changes.requireInt("maxItems").requireExactValue(
                MAX_GIT_STATUS_CHANGES,
                "changes maxItems",
            )
            changes.requireObject("items").requireString("\$ref").requireExactString(
                "#/\$defs/GitStatusChangeOutput",
                "changes ref",
            )
        }
        properties.requireObject("status").validateBoundedStringSchema(
            "status",
            1,
            MAX_GIT_STATUS_STATUS_LENGTH,
        )
        properties.requireObject("repoName").validateBoundedStringSchema(
            "repoName",
            1,
            MAX_GIT_STATUS_REPO_NAME_LENGTH,
        )
        properties.requireObject("repoIndex").validateBoundedIntegerSchema(
            "repoIndex",
            0,
            MAX_GIT_STATUS_REPOS,
        )
        setOf("stagedCount", "unstagedCount", "untrackedCount", "conflictCount").forEach { field ->
            properties.requireObject(field).validateNonNegativeIntegerSchema(field)
        }
        properties.requireObject("clean").requireTypeOnly("boolean")
        properties.requireObject("truncated").requireTypeOnly("boolean")
        properties.requireObject("branch").validateNullableBoundedStringSchema(
            "branch",
            MAX_GIT_STATUS_BRANCH_LENGTH,
        )
        properties.requireObject("headOidShort").validateNullableBoundedStringSchema(
            "headOidShort",
            MAX_GIT_STATUS_OID_LENGTH,
        )
        properties.requireObject("upstream").validateNullableBoundedStringSchema(
            "upstream",
            MAX_GIT_STATUS_UPSTREAM_LENGTH,
        )
        properties.requireObject("ahead").validateNullableNonNegativeIntegerSchema("ahead")
        properties.requireObject("behind").validateNullableNonNegativeIntegerSchema("behind")

        val definitions = schema.requireObject("\$defs")
        definitions.requireKeys(GIT_STATUS_DEFINITION_KEYS)
        validateGitStatusApprovedRepoDefinition(
            definitions.requireObject("GitStatusApprovedRepoOutput"),
        )
        validateGitStatusChangeDefinition(definitions.requireObject("GitStatusChangeOutput"))
    }

    private fun validateGitStatusApprovedRepoDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(GIT_STATUS_APPROVED_REPO_KEYS)
        properties.requireObject("repoIndex").validateBoundedIntegerSchema(
            "repoIndex",
            0,
            MAX_GIT_STATUS_REPOS,
        )
        properties.requireObject("name").validateBoundedStringSchema(
            "approved repo name",
            1,
            MAX_GIT_STATUS_REPO_NAME_LENGTH,
        )
        definition.requireArray("required")
            .requireExactStrings(GIT_STATUS_APPROVED_REPO_KEYS, "approved repo required")
    }

    private fun validateGitStatusChangeDefinition(definition: JsonObject) {
        definition.requireKeys(OBJECT_DEFINITION_KEYS)
        validateObjectSchemaRootWithoutDialect(definition)
        val properties = definition.requireObject("properties")
        properties.requireKeys(GIT_STATUS_CHANGE_KEYS)
        properties.requireObject("path").validateBoundedStringSchema(
            "change path",
            1,
            MAX_GIT_STATUS_PATH_LENGTH,
        )
        properties.requireObject("pathTruncated").requireTypeOnly("boolean")
        properties.requireObject("indexStatus").validateBoundedStringSchema(
            "indexStatus",
            1,
            1,
        )
        properties.requireObject("workingTreeStatus").validateBoundedStringSchema(
            "workingTreeStatus",
            1,
            1,
        )
        properties.requireObject("kind").also { kind ->
            kind.requireKeys(ENUM_STRING_SCHEMA_KEYS)
            kind.requireType("string")
            kind.requireArray("enum").requireExactStrings(GIT_STATUS_CHANGE_KINDS, "git kind enum")
        }
        definition.requireArray("required").requireExactStrings(GIT_STATUS_CHANGE_KEYS, "change required")
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

    private fun validateToolAnnotations(
        annotations: JsonObject,
        expectedPermission: String,
    ) {
        annotations.requireKeys(ANNOTATION_KEYS)
        val readOnly = annotations.requireBoolean("readOnlyHint")
        val destructive = annotations.requireBoolean("destructiveHint")
        val idempotent = annotations.requireBoolean("idempotentHint")
        val openWorld = annotations.requireBoolean("openWorldHint")
        val compatible = when (expectedPermission) {
            "SAFE" -> readOnly && !destructive && idempotent && !openWorld
            "CONFIRM" -> !readOnly && !destructive && !idempotent && !openWorld
            else -> false
        }
        if (!compatible) {
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
            MAC_FILES_LARGEST_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.files.largest returned an unexpected execution target")
                }
                decodeMacFilesLargest(content)
            }
            MAC_FILES_LIST_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.files.list returned an unexpected execution target")
                }
                decodeMacFilesList(content)
            }
            MAC_CLIPBOARD_READ_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.clipboard.read returned an unexpected execution target")
                }
                decodeMacClipboardRead(content)
            }
            MAC_APPS_LIST_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.apps.list returned an unexpected execution target")
                }
                decodeMacAppsList(content)
            }
            MAC_APPS_OPEN_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.apps.open returned an unexpected execution target")
                }
                decodeMacAppsOpen(content)
            }
            MAC_PROCESSES_LIST_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("mac.processes.list returned an unexpected execution target")
                }
                decodeMacProcessesList(content)
            }
            GIT_STATUS_TOOL -> {
                if (target != ExecutionTarget.MAC) {
                    throw ProtocolException("git.status returned an unexpected execution target")
                }
                decodeGitStatus(content)
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

    private fun decodeMacFilesLargest(content: JsonObject): MacFilesLargest {
        content.requireKeys(MAC_FILES_LARGEST_OUTPUT_KEYS)
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
            maximum = MAX_MAC_FILES_LARGEST_ENTRIES,
            field = "entries",
        ) { entry ->
            entry.requireKeys(MAC_FILES_LARGEST_ENTRY_KEYS)
            MacFilesLargestEntry(
                relativePath = entry.requireBoundedString(
                    "relativePath",
                    1,
                    MAX_MAC_FILES_LARGEST_PATH_LENGTH,
                ),
                pathTruncated = entry.requireBoolean("pathTruncated"),
                name = entry.requireBoundedString("name", 1, MAX_MAC_FILES_ENTRY_NAME_LENGTH),
                nameTruncated = entry.requireBoolean("nameTruncated"),
                sizeBytes = entry.requireBoundedLong(
                    "sizeBytes",
                    0L,
                    MAX_MAC_FILES_LARGEST_FILE_SIZE_BYTES,
                ),
                modifiedEpochSeconds = entry.requireNullableLong("modifiedEpochSeconds")
                    ?.also { modified ->
                        if (modified < 0L) {
                            throw ProtocolException("modifiedEpochSeconds cannot be negative")
                        }
                    },
            )
        }
        val result = MacFilesLargest(
            status = content.requireBoundedString("status", 1, 64),
            rootIndex = content.requireBoundedInt("rootIndex", 0, MAX_MAC_FILES_ROOT_INDEX),
            rootName = content.requireBoundedString("rootName", 1, MAX_MAC_FILES_ROOT_NAME_LENGTH),
            relativePath = content.requireBoundedString(
                "relativePath",
                0,
                MAX_MAC_FILES_RELATIVE_PATH_LENGTH,
            ),
            maxDepth = content.requireBoundedInt("maxDepth", 0, MAX_MAC_FILES_LARGEST_DEPTH),
            scannedEntries = content.requireBoundedInt(
                "scannedEntries",
                0,
                MAX_MAC_FILES_LARGEST_SCANNED_ENTRIES,
            ),
            skippedEntries = content.requireBoundedInt(
                "skippedEntries",
                0,
                MAX_MAC_FILES_LARGEST_SCANNED_ENTRIES,
            ),
            truncated = content.requireBoolean("truncated"),
            approvedRoots = approvedRoots,
            entries = entries,
        )
        if (!result.matchesToolContract()) {
            throw ProtocolException("largest files result failed local policy")
        }
        return result
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
                modifiedEpochSeconds = entry.requireNullableLong("modifiedEpochSeconds")
                    ?.also { modified ->
                        if (modified < 0L) {
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

    private fun decodeGitStatus(content: JsonObject): GitStatus {
        content.requireKeys(GIT_STATUS_REQUIRED_KEYS, GIT_STATUS_OPTIONAL_KEYS)
        val approvedRepos = content.requireArray("approvedRepos").boundedObjects(
            maximum = MAX_GIT_STATUS_REPOS,
            field = "approvedRepos",
        ) { repo ->
            repo.requireKeys(GIT_STATUS_APPROVED_REPO_KEYS)
            GitStatusApprovedRepo(
                repoIndex = repo.requireBoundedInt("repoIndex", 0, MAX_GIT_STATUS_REPO_INDEX),
                name = repo.requireBoundedString("name", 1, MAX_GIT_STATUS_REPO_NAME_LENGTH),
            )
        }
        val changes = content.requireArray("changes").boundedObjects(
            maximum = MAX_GIT_STATUS_CHANGES,
            field = "changes",
        ) { change ->
            change.requireKeys(GIT_STATUS_CHANGE_KEYS)
            GitStatusChange(
                path = change.requireBoundedString("path", 1, MAX_GIT_STATUS_PATH_LENGTH),
                pathTruncated = change.requireBoolean("pathTruncated"),
                indexStatus = change.requireBoundedString("indexStatus", 1, 1),
                workingTreeStatus = change.requireBoundedString("workingTreeStatus", 1, 1),
                kind = change.requireString("kind").also { kind ->
                    if (kind !in GIT_STATUS_CHANGE_KINDS) {
                        throw ProtocolException("unsupported Git status change kind")
                    }
                },
            )
        }
        return GitStatus(
            status = content.requireBoundedString("status", 1, MAX_GIT_STATUS_STATUS_LENGTH),
            repoIndex = content.requireBoundedInt("repoIndex", 0, MAX_GIT_STATUS_REPO_INDEX),
            repoName = content.requireBoundedString("repoName", 1, MAX_GIT_STATUS_REPO_NAME_LENGTH),
            branch = content.requireNullableBoundedString(
                "branch",
                MAX_GIT_STATUS_BRANCH_LENGTH,
            ),
            headOidShort = content.requireNullableBoundedString(
                "headOidShort",
                MAX_GIT_STATUS_OID_LENGTH,
            ),
            upstream = content.requireNullableBoundedString(
                "upstream",
                MAX_GIT_STATUS_UPSTREAM_LENGTH,
            ),
            ahead = content.requireNullableNonNegativeInt("ahead"),
            behind = content.requireNullableNonNegativeInt("behind"),
            clean = content.requireBoolean("clean"),
            stagedCount = content.requireBoundedInt("stagedCount", 0, MAX_GIT_STATUS_COUNT),
            unstagedCount = content.requireBoundedInt("unstagedCount", 0, MAX_GIT_STATUS_COUNT),
            untrackedCount = content.requireBoundedInt("untrackedCount", 0, MAX_GIT_STATUS_COUNT),
            conflictCount = content.requireBoundedInt("conflictCount", 0, MAX_GIT_STATUS_COUNT),
            truncated = content.requireBoolean("truncated"),
            approvedRepos = approvedRepos,
            changes = changes,
        )
    }

    private fun decodeMacClipboardRead(content: JsonObject): MacClipboardRead {
        content.requireKeys(MAC_CLIPBOARD_READ_REQUIRED_KEYS, MAC_CLIPBOARD_READ_OPTIONAL_KEYS)
        val contentType = content["contentType"]?.let { element ->
            element.stringValueOrNull()
                ?: throw ProtocolException("contentType must be a string")
        } ?: "text"
        if (contentType != "text") {
            throw ProtocolException("unsupported clipboard content type")
        }
        val status = content.requireString("status").also { value ->
            if (value !in MAC_CLIPBOARD_STATUS_VALUES) {
                throw ProtocolException("unsupported clipboard status")
            }
        }
        val text = content.requireNullableBoundedString(
            "text",
            MAX_MAC_CLIPBOARD_TEXT_LENGTH,
        )
        if (text?.contains("file://", ignoreCase = true) == true) {
            throw ProtocolException("clipboard text contains an unsupported file URL")
        }
        val result = MacClipboardRead(
            status = status,
            contentType = contentType,
            text = text,
            textTruncated = content.requireBoolean("textTruncated"),
            characterCount = content.requireBoundedInt(
                "characterCount",
                0,
                MAX_MAC_CLIPBOARD_CHARACTER_COUNT,
            ),
            characterCountTruncated = content.requireBoolean("characterCountTruncated"),
        )
        if (!result.matchesToolContract()) {
            throw ProtocolException("clipboard result failed local policy")
        }
        return result
    }

    private fun decodeMacAppsList(content: JsonObject): MacAppsList {
        content.requireKeys(MAC_APPS_LIST_OUTPUT_KEYS)
        val entries = content.requireArray("entries").boundedObjects(
            maximum = MAX_MAC_APP_ENTRIES,
            field = "entries",
        ) { entry ->
            entry.requireKeys(MAC_APP_CATALOG_ENTRY_KEYS)
            MacAppCatalogEntry(
                appIndex = entry.requireBoundedInt("appIndex", 0, MAX_MAC_APP_INDEX),
                displayName = entry.requireBoundedString(
                    "displayName",
                    1,
                    MAX_MAC_APP_DISPLAY_NAME_LENGTH,
                ),
                bundleId = entry.requireBoundedString(
                    "bundleId",
                    1,
                    MAX_MAC_APP_BUNDLE_ID_LENGTH,
                ),
            )
        }
        val result = MacAppsList(
            status = content.requireBoundedString("status", 1, MAX_MAC_APP_STATUS_LENGTH),
            appCount = content.requireBoundedInt("appCount", 0, MAX_MAC_APP_COUNT),
            truncated = content.requireBoolean("truncated"),
            entries = entries,
        )
        if (!result.matchesToolContract()) {
            throw ProtocolException("app list result failed local policy")
        }
        return result
    }

    private fun decodeMacAppsOpen(content: JsonObject): MacAppOpened {
        content.requireKeys(MAC_APPS_OPEN_OUTPUT_KEYS)
        val result = MacAppOpened(
            status = content.requireBoundedString("status", 1, MAX_MAC_APP_STATUS_LENGTH),
            displayName = content.requireBoundedString(
                "displayName",
                1,
                MAX_MAC_APP_DISPLAY_NAME_LENGTH,
            ),
            bundleId = content.requireBoundedString(
                "bundleId",
                1,
                MAX_MAC_APP_BUNDLE_ID_LENGTH,
            ),
            verified = content.requireBoolean("verified"),
        )
        if (!result.matchesToolContract()) {
            throw ProtocolException("app open result failed local policy")
        }
        return result
    }

    private fun decodeMacProcessesList(content: JsonObject): MacProcessesList {
        content.requireKeys(MAC_PROCESSES_LIST_OUTPUT_KEYS)
        val entries = content.requireArray("entries").boundedObjects(
            maximum = MAX_MAC_PROCESS_ENTRIES,
            field = "entries",
        ) { entry ->
            entry.requireKeys(MAC_PROCESS_ENTRY_REQUIRED_KEYS, setOf("createTimeEpochSeconds"))
            MacProcessEntry(
                pid = entry.requireBoundedInt("pid", 0, MAX_MAC_PROCESS_PID),
                name = entry.requireBoundedString("name", 1, MAX_MAC_PROCESS_NAME_LENGTH),
                status = entry.requireBoundedString("status", 1, MAX_MAC_PROCESS_STATUS_LENGTH),
                rssBytes = entry.requireBoundedLong(
                    "rssBytes",
                    0,
                    MAX_MAC_PROCESS_RSS_BYTES,
                ),
                createTimeEpochSeconds = entry.requireNullableLong("createTimeEpochSeconds")
                    ?.also { created ->
                        if (created < 0L) {
                            throw ProtocolException("createTimeEpochSeconds cannot be negative")
                        }
                    },
            )
        }
        val result = MacProcessesList(
            status = content.requireBoundedString("status", 1, MAX_MAC_PROCESS_STATUS_TEXT_LENGTH),
            processCount = content.requireBoundedInt("processCount", 0, MAX_MAC_PROCESS_COUNT),
            skippedCount = content.requireBoundedInt("skippedCount", 0, MAX_MAC_PROCESS_COUNT),
            truncated = content.requireBoolean("truncated"),
            entries = entries,
        )
        if (!result.matchesToolContract()) {
            throw ProtocolException("process list result failed local policy")
        }
        return result
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

private fun JsonObject.requireNullableLong(key: String): Long? {
    val value = this[key] ?: return null
    if (value === JsonNull) return null
    return (value as? JsonPrimitive)?.longOrNull
        ?: throw ProtocolException("$key must be an integer or null")
}

private fun JsonObject.requireLong(key: String): Long = (this[key] as? JsonPrimitive)?.longOrNull
    ?: throw ProtocolException("$key must be an integer")

private fun JsonObject.requireNullableBoundedString(key: String, maximum: Int): String? {
    val value = requireNullableString(key) ?: return null
    requireBounded(key, value, 1, maximum)
    return value
}

private fun JsonObject.requireNullableNonNegativeInt(key: String): Int? =
    requireNullableInt(key)?.also { value ->
        if (value !in 0..MAX_GIT_STATUS_COUNT) {
            throw ProtocolException("$key is outside the supported range")
        }
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

private fun JsonObject.validateBoundedStringSchema(field: String, minimum: Int, maximum: Int) {
    requireKeys(STRING_BOUNDED_SCHEMA_KEYS)
    requireType("string")
    requireInt("minLength").requireExactValue(minimum, "$field minLength")
    requireInt("maxLength").requireExactValue(maximum, "$field maxLength")
}

private fun JsonObject.validateBoundedIntegerSchema(field: String, minimum: Int, exclusiveMaximum: Int) {
    requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "exclusiveMaximum")
    requireType("integer")
    requireInt("minimum").requireExactValue(minimum, "$field minimum")
    requireInt("exclusiveMaximum").requireExactValue(exclusiveMaximum, "$field maximum")
}

private fun JsonObject.validateNonNegativeIntegerSchema(field: String) {
    requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS)
    requireType("integer")
    requireInt("minimum").requireExactValue(0, "$field minimum")
}

private fun JsonObject.validateBoundedIntInclusiveSchema(field: String, minimum: Int, maximum: Int) {
    requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum")
    requireType("integer")
    requireInt("minimum").requireExactValue(minimum, "$field minimum")
    requireInt("maximum").requireExactValue(maximum, "$field maximum")
}

private fun JsonObject.validateBoundedLongSchema(field: String, minimum: Long, maximum: Long) {
    requireKeys(INTEGER_BOUNDED_SCHEMA_KEYS + "maximum")
    requireType("integer")
    requireLong("minimum").requireExactValue(minimum, "$field minimum")
    requireLong("maximum").requireExactValue(maximum, "$field maximum")
}

private fun JsonObject.validateNullableBoundedStringSchema(field: String, maximum: Int) {
    requireKeys(NULLABLE_SCHEMA_KEYS)
    if (this["default"] !== JsonNull) {
        throw ProtocolException("$field default must be null")
    }
    val anyOf = requireArray("anyOf")
    if (anyOf.size != 2) throw ProtocolException("$field nullable string schema is incompatible")
    val types = anyOf.map { element ->
        val schema = element as? JsonObject
            ?: throw ProtocolException("$field nullable string entries must be objects")
        val type = schema.requireString("type")
        when (type) {
            "string" -> {
                schema.requireKeys(STRING_MAX_SCHEMA_KEYS)
                schema.requireInt("maxLength").requireExactValue(maximum, "$field maxLength")
            }
            "null" -> schema.requireTypeOnly("null")
            else -> throw ProtocolException("$field nullable string schema is incompatible")
        }
        type
    }.toSet()
    if (types != setOf("string", "null")) {
        throw ProtocolException("$field nullable string schema is incompatible")
    }
}

private fun JsonObject.validateNullableNonNegativeIntegerSchema(field: String) {
    requireKeys(NULLABLE_SCHEMA_KEYS)
    if (this["default"] !== JsonNull) {
        throw ProtocolException("$field default must be null")
    }
    val anyOf = requireArray("anyOf")
    if (anyOf.size != 2) throw ProtocolException("$field nullable integer schema is incompatible")
    val types = anyOf.map { element ->
        val schema = element as? JsonObject
            ?: throw ProtocolException("$field nullable integer entries must be objects")
        val type = schema.requireString("type")
        when (type) {
            "integer" -> schema.validateNonNegativeIntegerSchema(field)
            "null" -> schema.requireTypeOnly("null")
            else -> throw ProtocolException("$field nullable integer schema is incompatible")
        }
        type
    }.toSet()
    if (types != setOf("integer", "null")) {
        throw ProtocolException("$field nullable integer schema is incompatible")
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

private fun Long.requireExactValue(expected: Long, field: String) {
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

private fun JsonObject.requireBoundedLong(key: String, minimum: Long, maximum: Long): Long {
    val value = requireLong(key)
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

private fun canonicalJson(value: JsonElement): String = when (value) {
    is JsonObject -> value.entries
        .sortedBy { it.key }
        .joinToString(separator = ",", prefix = "{", postfix = "}") { (key, element) ->
            "${quoteJsonString(key)}:${canonicalJson(element)}"
        }
    is JsonArray -> value.joinToString(separator = ",", prefix = "[", postfix = "]") { element ->
        canonicalJson(element)
    }
    JsonNull -> "null"
    else -> Json.encodeToString(JsonElement.serializer(), value)
}

private fun quoteJsonString(value: String): String =
    Json.encodeToString(JsonElement.serializer(), JsonPrimitive(value))

private fun sha256Hex(value: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(value.encodeToByteArray())
        .joinToString(separator = "") { byte -> "%02x".format(byte.toInt() and 0xff) }

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
private val SHA256_HEX = Regex("^[a-f0-9]{64}$")
private val BASE64 = Regex("^[A-Za-z0-9+/]+={0,2}$")
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
private val APPROVAL_REQUEST_KEYS = setOf(
    "schemaVersion",
    "approvalId",
    "taskId",
    "toolName",
    "argumentsSha256",
    "issuedAtEpochMillis",
    "expiresAtEpochMillis",
)
private val SYSTEM_INFO_KEYS = setOf("status", "operatingSystem", "architecture")
private val MAC_FILES_LIST_INPUT_KEYS = setOf(
    "rootIndex",
    "relativePath",
    "maxEntries",
    "includeHidden",
)
private val MAC_PROCESSES_LIST_INPUT_KEYS = setOf("maxEntries")
private val MAC_PROCESSES_LIST_OUTPUT_KEYS = setOf(
    "status",
    "processCount",
    "skippedCount",
    "truncated",
    "entries",
)
private val MAC_PROCESS_ENTRY_KEYS = setOf(
    "pid",
    "name",
    "status",
    "rssBytes",
    "createTimeEpochSeconds",
)
private val MAC_PROCESS_ENTRY_REQUIRED_KEYS = setOf(
    "pid",
    "name",
    "status",
    "rssBytes",
)
private val MAC_FILES_LARGEST_INPUT_KEYS = setOf(
    "rootIndex",
    "relativePath",
    "maxEntries",
    "maxDepth",
    "includeHidden",
)
private val MAC_FILES_LARGEST_OUTPUT_KEYS = setOf(
    "status",
    "rootIndex",
    "rootName",
    "relativePath",
    "maxDepth",
    "scannedEntries",
    "skippedEntries",
    "truncated",
    "approvedRoots",
    "entries",
)
private val MAC_FILES_LARGEST_DEFINITION_KEYS = setOf(
    "MacFilesApprovedRootOutput",
    "MacFilesLargestEntryOutput",
)
private val MAC_FILES_LARGEST_ENTRY_KEYS = setOf(
    "relativePath",
    "pathTruncated",
    "name",
    "nameTruncated",
    "sizeBytes",
    "modifiedEpochSeconds",
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
private val MAC_CLIPBOARD_READ_INPUT_KEYS = setOf("maxChars")
private val MAC_CLIPBOARD_READ_REQUIRED_KEYS = setOf(
    "status",
    "textTruncated",
    "characterCount",
    "characterCountTruncated",
)
private val MAC_CLIPBOARD_READ_OPTIONAL_KEYS = setOf("contentType", "text")
private val MAC_CLIPBOARD_READ_OUTPUT_KEYS =
    MAC_CLIPBOARD_READ_REQUIRED_KEYS + MAC_CLIPBOARD_READ_OPTIONAL_KEYS
private val MAC_APPS_LIST_INPUT_KEYS = setOf("maxEntries")
private val MAC_APPS_LIST_OUTPUT_KEYS = setOf(
    "status",
    "appCount",
    "truncated",
    "entries",
)
private val MAC_APPS_OPEN_INPUT_KEYS = setOf("displayName")
private val MAC_APPS_OPEN_OUTPUT_KEYS = setOf(
    "status",
    "displayName",
    "bundleId",
    "verified",
)
private val MAC_APP_CATALOG_ENTRY_KEYS = setOf(
    "appIndex",
    "displayName",
    "bundleId",
)
private val GIT_STATUS_INPUT_KEYS = setOf("repoIndex", "maxChanges", "includeUntracked")
private val GIT_STATUS_REQUIRED_KEYS = setOf(
    "status",
    "repoIndex",
    "repoName",
    "clean",
    "stagedCount",
    "unstagedCount",
    "untrackedCount",
    "conflictCount",
    "truncated",
    "approvedRepos",
    "changes",
)
private val GIT_STATUS_OPTIONAL_KEYS = setOf(
    "branch",
    "headOidShort",
    "upstream",
    "ahead",
    "behind",
)
private val GIT_STATUS_OUTPUT_KEYS = GIT_STATUS_REQUIRED_KEYS + GIT_STATUS_OPTIONAL_KEYS
private val GIT_STATUS_DEFINITION_KEYS = setOf(
    "GitStatusApprovedRepoOutput",
    "GitStatusChangeOutput",
)
private val GIT_STATUS_APPROVED_REPO_KEYS = setOf("repoIndex", "name")
private val GIT_STATUS_CHANGE_KEYS = setOf(
    "path",
    "pathTruncated",
    "indexStatus",
    "workingTreeStatus",
    "kind",
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
private val STRING_BOUNDED_SCHEMA_KEYS = setOf("type", "minLength", "maxLength")
private val STRING_MAX_SCHEMA_KEYS = setOf("type", "maxLength")
private val BOOLEAN_SCHEMA_KEYS = setOf("type")
private val INTEGER_BOUNDED_SCHEMA_KEYS = setOf("type", "minimum")
private val ARRAY_REF_SCHEMA_KEYS = setOf("type", "items")
private val OBJECT_DEFINITION_KEYS = setOf("type", "additionalProperties", "properties", "required")
private val ENUM_STRING_SCHEMA_KEYS = setOf("type", "enum")
private val NULLABLE_SCHEMA_KEYS = setOf("anyOf", "default")
