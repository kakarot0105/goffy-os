package dev.goffy.os.capability

import dev.goffy.os.protocol.ANDROID_SET_TIMER_ACTION
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MAX_NOTE_TEXT_LENGTH
import dev.goffy.os.protocol.MAX_OCR_CHARACTER_COUNT
import dev.goffy.os.protocol.MAX_OCR_LINE_COUNT
import dev.goffy.os.protocol.MAX_OCR_PREVIEW_LENGTH
import dev.goffy.os.protocol.MAX_MEMORY_TEXT_LENGTH
import dev.goffy.os.protocol.MAX_PHONE_MEMORY_LIST_ENTRIES
import dev.goffy.os.protocol.MAX_PHONE_MEMORY_ROWS
import dev.goffy.os.protocol.MAX_QR_PAYLOAD_CHARACTER_COUNT
import dev.goffy.os.protocol.MAX_QR_PREVIEW_LENGTH
import dev.goffy.os.protocol.MAX_TIMER_SECONDS
import dev.goffy.os.protocol.MIN_TIMER_SECONDS
import dev.goffy.os.protocol.NoToolArguments
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_FORGET_ALL_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_LIST_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_PROVENANCE_USER_APPROVED
import dev.goffy.os.protocol.PHONE_MEMORY_REMEMBER_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_STATUS_AVAILABLE
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PHONE_OCR_READ_TOOL
import dev.goffy.os.protocol.PHONE_OCR_SCRIPTS
import dev.goffy.os.protocol.PHONE_OCR_STATUS_AVAILABLE
import dev.goffy.os.protocol.PHONE_QR_CONTENT_TYPES
import dev.goffy.os.protocol.PHONE_QR_READ_TOOL
import dev.goffy.os.protocol.PHONE_QR_STATUS_AVAILABLE
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneMemoryRememberArguments
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.ToolArguments
import dev.goffy.os.protocol.matchesMemoryTextContract
import dev.goffy.os.protocol.matchesNoteTextContract
import dev.goffy.os.protocol.matchesToolContract
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

private const val JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
private const val PHONE_TOOL_VERSION = "1.0.0"
private const val MAX_CAPABILITY_BYTES = 8_192
private const val MAX_REGISTRY_BYTES = 32_768
private const val MAX_TOOL_TIMEOUT_MILLIS = 30_000L
private val TOOL_NAME = Regex("^[a-z][a-z0-9_.]{0,127}$")

data class GoffyToolAnnotations(
    val readOnlyHint: Boolean,
    val destructiveHint: Boolean,
    val idempotentHint: Boolean,
    val openWorldHint: Boolean,
)

data class GoffyToolMetadata(
    val toolVersion: String,
    val executionTarget: ExecutionTarget,
    val permission: PermissionLevel,
    val timeoutMillis: Long,
)

data class GoffyToolCapability(
    val name: String,
    val title: String,
    val description: String,
    val inputSchema: JsonObject,
    val outputSchema: JsonObject,
    val annotations: GoffyToolAnnotations,
    val metadata: GoffyToolMetadata,
) {
    fun toMcpJson(): JsonObject = buildJsonObject {
        put("name", name)
        put("title", title)
        put("description", description)
        put("inputSchema", inputSchema)
        put("outputSchema", outputSchema)
        put(
            "annotations",
            buildJsonObject {
                put("readOnlyHint", annotations.readOnlyHint)
                put("destructiveHint", annotations.destructiveHint)
                put("idempotentHint", annotations.idempotentHint)
                put("openWorldHint", annotations.openWorldHint)
            },
        )
        put(
            "_meta",
            buildJsonObject {
                put("dev.goffy/toolVersion", metadata.toolVersion)
                put("dev.goffy/executionTarget", metadata.executionTarget.name)
                put("dev.goffy/permission", metadata.permission.name)
                put("dev.goffy/timeoutMs", metadata.timeoutMillis)
            },
        )
    }
}

internal data class PhoneCapabilityDefinition(
    val capability: GoffyToolCapability,
    val acceptsArguments: (ToolArguments) -> Boolean,
)

class PhoneCapabilityRegistry internal constructor(
    definitions: List<PhoneCapabilityDefinition>,
) {
    private val definitionsByName: Map<String, PhoneCapabilityDefinition>
    val capabilities: List<GoffyToolCapability>

    init {
        require(definitions.isNotEmpty()) { "PHONE capability registry must not be empty" }
        require(definitions.size <= MAX_PHONE_CAPABILITIES) { "Too many PHONE capabilities" }
        require(definitions.map { it.capability.name }.distinct().size == definitions.size) {
            "PHONE capability names must be unique"
        }
        definitions.forEach { validateDefinition(it) }
        val ordered = definitions.sortedBy { it.capability.name }
        require(
            ordered.sumOf { it.capability.toMcpJson().toString().encodeToByteArray().size } <=
                MAX_REGISTRY_BYTES,
        ) { "PHONE capability registry exceeds its size budget" }
        definitionsByName = ordered.associateBy { it.capability.name }
        capabilities = ordered.map { it.capability }
    }

    fun find(toolName: String): GoffyToolCapability? = definitionsByName[toolName]?.capability

    fun match(
        toolName: String,
        executionTarget: ExecutionTarget,
        permission: PermissionLevel,
        arguments: ToolArguments,
    ): GoffyToolCapability? {
        val definition = definitionsByName[toolName] ?: return null
        val metadata = definition.capability.metadata
        return definition.capability.takeIf {
            executionTarget == metadata.executionTarget &&
                permission == metadata.permission &&
                definition.acceptsArguments(arguments)
        }
    }

    companion object {
        const val MAX_PHONE_CAPABILITIES = 16
        const val DEFAULT_TIMEOUT_MILLIS = 2_000L
        const val DEFAULT_FLASHLIGHT_TIMEOUT_MILLIS = 3_000L

        val default: PhoneCapabilityRegistry by lazy(LazyThreadSafetyMode.PUBLICATION) { create() }

        fun create(
            defaultTimeoutMillis: Long = DEFAULT_TIMEOUT_MILLIS,
            flashlightTimeoutMillis: Long = DEFAULT_FLASHLIGHT_TIMEOUT_MILLIS,
        ): PhoneCapabilityRegistry {
            require(defaultTimeoutMillis in 1..MAX_TOOL_TIMEOUT_MILLIS)
            require(flashlightTimeoutMillis in 1..MAX_TOOL_TIMEOUT_MILLIS)
            return PhoneCapabilityRegistry(
                listOf(
                    batteryCapability(defaultTimeoutMillis),
                    deviceCapability(defaultTimeoutMillis),
                    flashlightCapability(flashlightTimeoutMillis),
                    memoryForgetAllCapability(defaultTimeoutMillis),
                    memoryListCapability(defaultTimeoutMillis),
                    memoryRememberCapability(defaultTimeoutMillis),
                    noteCapability(defaultTimeoutMillis),
                    ocrReadCapability(defaultTimeoutMillis),
                    qrReadCapability(defaultTimeoutMillis),
                    timerCapability(defaultTimeoutMillis),
                ),
            )
        }
    }
}

private fun validateDefinition(definition: PhoneCapabilityDefinition) {
    val capability = definition.capability
    require(TOOL_NAME.matches(capability.name)) { "Invalid PHONE capability name" }
    require(capability.title.isNotBlank() && capability.title.length <= 128)
    require(capability.description.isNotBlank() && capability.description.length <= 512)
    require(capability.metadata.toolVersion == PHONE_TOOL_VERSION)
    require(capability.metadata.executionTarget == ExecutionTarget.PHONE)
    require(capability.metadata.permission in setOf(PermissionLevel.SAFE, PermissionLevel.CONFIRM))
    require(capability.metadata.timeoutMillis in 1..MAX_TOOL_TIMEOUT_MILLIS)
    require(!capability.annotations.openWorldHint)
    if (capability.annotations.destructiveHint) {
        require(
            capability.name == PHONE_MEMORY_FORGET_ALL_TOOL &&
                capability.metadata.permission == PermissionLevel.CONFIRM,
        )
    }
    when (capability.metadata.permission) {
        PermissionLevel.SAFE -> require(
            capability.annotations.readOnlyHint &&
                capability.annotations.idempotentHint &&
                !capability.annotations.destructiveHint,
        )
        PermissionLevel.CONFIRM -> require(!capability.annotations.readOnlyHint)
        PermissionLevel.SENSITIVE,
        PermissionLevel.BLOCKED,
        -> error("Unsupported PHONE permission")
    }
    validateSchema(capability.inputSchema)
    validateSchema(capability.outputSchema)
    require(capability.toMcpJson().toString().encodeToByteArray().size <= MAX_CAPABILITY_BYTES) {
        "PHONE capability exceeds its size budget"
    }
}

private fun validateSchema(schema: JsonObject) {
    require(schema["\$schema"] == JsonPrimitive(JSON_SCHEMA_DIALECT))
    require(schema["type"] == JsonPrimitive("object"))
    require(schema["additionalProperties"] == JsonPrimitive(false))
    require(schema["properties"] is JsonObject)
}

private fun batteryCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_BATTERY_STATUS_TOOL,
        title = "Phone battery status",
        description = "Read the current battery percentage and charging state from this phone.",
        permission = PermissionLevel.SAFE,
        timeoutMillis = timeoutMillis,
        readOnly = true,
        idempotent = true,
        inputSchema = objectSchema(emptyMap()),
        outputSchema = objectSchema(
            properties = mapOf(
                "levelPercent" to integerSchema(minimum = 0, maximum = 100),
                "charging" to booleanSchema(),
            ),
            required = listOf("levelPercent", "charging"),
        ),
        acceptsArguments = { it == NoToolArguments },
    )

private fun deviceCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_DEVICE_INFO_TOOL,
        title = "Phone device information",
        description = "Read privacy-minimized Android device and operating-system information.",
        permission = PermissionLevel.SAFE,
        timeoutMillis = timeoutMillis,
        readOnly = true,
        idempotent = true,
        inputSchema = objectSchema(emptyMap()),
        outputSchema = objectSchema(
            properties = mapOf(
                "manufacturer" to stringSchema(maxLength = 128),
                "model" to stringSchema(maxLength = 128),
                "androidRelease" to stringSchema(maxLength = 64),
                "sdkInt" to integerSchema(minimum = 26, maximum = 10_000),
                "goffySystemApp" to booleanSchema(),
                "goffyHomeCandidate" to booleanSchema(),
                "goffyDefaultHome" to booleanSchema(),
            ),
            required = listOf(
                "manufacturer",
                "model",
                "androidRelease",
                "sdkInt",
                "goffySystemApp",
                "goffyHomeCandidate",
                "goffyDefaultHome",
            ),
        ),
        acceptsArguments = { it == NoToolArguments },
    )

private fun flashlightCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_FLASHLIGHT_SET_TOOL,
        title = "Phone flashlight",
        description = "Set and callback-verify the back-camera flashlight on this phone.",
        permission = PermissionLevel.CONFIRM,
        timeoutMillis = timeoutMillis,
        readOnly = false,
        idempotent = true,
        inputSchema = objectSchema(
            properties = mapOf("enabled" to booleanSchema()),
            required = listOf("enabled"),
        ),
        outputSchema = objectSchema(
            properties = mapOf(
                "enabled" to booleanSchema(),
                "stateChanged" to booleanSchema(),
            ),
            required = listOf("enabled", "stateChanged"),
        ),
        acceptsArguments = { it is PhoneFlashlightSetArguments },
    )

private fun noteCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_NOTE_CREATE_TOOL,
        title = "Create private phone note",
        description = "Create and re-read a note in GOFFY app-private storage.",
        permission = PermissionLevel.CONFIRM,
        timeoutMillis = timeoutMillis,
        readOnly = false,
        idempotent = false,
        inputSchema = objectSchema(
            properties = mapOf("text" to stringSchema(maxLength = MAX_NOTE_TEXT_LENGTH)),
            required = listOf("text"),
        ),
        outputSchema = objectSchema(
            properties = mapOf(
                "noteId" to integerSchema(minimum = 1),
                "text" to stringSchema(maxLength = MAX_NOTE_TEXT_LENGTH),
                "createdAtEpochMillis" to integerSchema(minimum = 1),
            ),
            required = listOf("noteId", "text", "createdAtEpochMillis"),
        ),
        acceptsArguments = { arguments ->
            arguments is PhoneNoteCreateArguments && arguments.text.matchesNoteTextContract()
        },
    )

private fun memoryRememberCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_MEMORY_REMEMBER_TOOL,
        title = "Remember approved phone memory",
        description = "Store one user-approved memory in GOFFY app-private storage.",
        permission = PermissionLevel.CONFIRM,
        timeoutMillis = timeoutMillis,
        readOnly = false,
        idempotent = false,
        inputSchema = objectSchema(
            properties = mapOf("text" to stringSchema(maxLength = MAX_MEMORY_TEXT_LENGTH)),
            required = listOf("text"),
        ),
        outputSchema = memoryEntrySchema(
            required = listOf("memoryId", "text", "createdAtEpochMillis", "provenance"),
        ),
        acceptsArguments = { arguments ->
            arguments is PhoneMemoryRememberArguments && arguments.text.matchesMemoryTextContract()
        },
    )

private fun memoryListCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_MEMORY_LIST_TOOL,
        title = "List approved phone memories",
        description = "Read bounded user-approved memories stored locally on this phone.",
        permission = PermissionLevel.SAFE,
        timeoutMillis = timeoutMillis,
        readOnly = true,
        idempotent = true,
        inputSchema = objectSchema(emptyMap()),
        outputSchema = objectSchema(
            properties = mapOf(
                "status" to stringSchema(constant = PHONE_MEMORY_STATUS_AVAILABLE),
                "count" to integerSchema(minimum = 0, maximum = MAX_PHONE_MEMORY_ROWS.toLong()),
                "truncated" to booleanSchema(),
                "entries" to arraySchema(
                    itemSchema = memoryEntrySchema(
                        required = listOf(
                            "memoryId",
                            "text",
                            "createdAtEpochMillis",
                            "provenance",
                        ),
                    ),
                    maxItems = MAX_PHONE_MEMORY_LIST_ENTRIES,
                ),
            ),
            required = listOf("status", "count", "truncated", "entries"),
        ),
        acceptsArguments = { it == NoToolArguments },
    )

private fun memoryForgetAllCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_MEMORY_FORGET_ALL_TOOL,
        title = "Forget all phone memories",
        description = "Delete all GOFFY user-approved phone memories after explicit approval.",
        permission = PermissionLevel.CONFIRM,
        timeoutMillis = timeoutMillis,
        readOnly = false,
        idempotent = false,
        destructive = true,
        inputSchema = objectSchema(emptyMap()),
        outputSchema = objectSchema(
            properties = mapOf(
                "deletedCount" to integerSchema(
                    minimum = 0,
                    maximum = MAX_PHONE_MEMORY_ROWS.toLong(),
                ),
                "remainingCount" to integerSchema(minimum = 0, maximum = 0),
            ),
            required = listOf("deletedCount", "remainingCount"),
        ),
        acceptsArguments = { it == NoToolArguments },
    )

private fun ocrReadCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_OCR_READ_TOOL,
        title = "Read foreground OCR text",
        description = "Read Latin-script text from a visible foreground camera scanner without storing images.",
        permission = PermissionLevel.SAFE,
        timeoutMillis = timeoutMillis,
        readOnly = true,
        idempotent = true,
        inputSchema = objectSchema(emptyMap()),
        outputSchema = objectSchema(
            properties = mapOf(
                "status" to stringSchema(constant = PHONE_OCR_STATUS_AVAILABLE),
                "script" to stringSchema(enumValues = PHONE_OCR_SCRIPTS.sorted()),
                "characterCount" to integerSchema(
                    minimum = 1,
                    maximum = MAX_OCR_CHARACTER_COUNT.toLong(),
                ),
                "characterCountTruncated" to booleanSchema(),
                "lineCount" to integerSchema(
                    minimum = 1,
                    maximum = MAX_OCR_LINE_COUNT.toLong(),
                ),
                "lineCountTruncated" to booleanSchema(),
                "preview" to nullableStringSchema(maxLength = MAX_OCR_PREVIEW_LENGTH),
                "previewTruncated" to booleanSchema(),
                "redacted" to booleanSchema(),
            ),
            required = listOf(
                "status",
                "script",
                "characterCount",
                "characterCountTruncated",
                "lineCount",
                "lineCountTruncated",
                "preview",
                "previewTruncated",
                "redacted",
            ),
        ),
        acceptsArguments = { it == NoToolArguments },
    )

private fun qrReadCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_QR_READ_TOOL,
        title = "Read foreground QR code",
        description = "Read one foreground camera QR code without storing images or raw sensitive payloads.",
        permission = PermissionLevel.SAFE,
        timeoutMillis = timeoutMillis,
        readOnly = true,
        idempotent = true,
        inputSchema = objectSchema(emptyMap()),
        outputSchema = objectSchema(
            properties = mapOf(
                "status" to stringSchema(constant = PHONE_QR_STATUS_AVAILABLE),
                "contentType" to stringSchema(enumValues = PHONE_QR_CONTENT_TYPES.sorted()),
                "characterCount" to integerSchema(
                    minimum = 1,
                    maximum = MAX_QR_PAYLOAD_CHARACTER_COUNT.toLong(),
                ),
                "characterCountTruncated" to booleanSchema(),
                "preview" to nullableStringSchema(maxLength = MAX_QR_PREVIEW_LENGTH),
                "previewTruncated" to booleanSchema(),
                "redacted" to booleanSchema(),
            ),
            required = listOf(
                "status",
                "contentType",
                "characterCount",
                "characterCountTruncated",
                "preview",
                "previewTruncated",
                "redacted",
            ),
        ),
        acceptsArguments = { it == NoToolArguments },
    )

private fun timerCapability(timeoutMillis: Long): PhoneCapabilityDefinition =
    definition(
        name = PHONE_TIMER_CREATE_TOOL,
        title = "Create system timer",
        description = "Dispatch an approved timer to an allowlisted Android system Clock.",
        permission = PermissionLevel.CONFIRM,
        timeoutMillis = timeoutMillis,
        readOnly = false,
        idempotent = false,
        inputSchema = objectSchema(
            properties = mapOf(
                "durationSeconds" to integerSchema(
                    minimum = MIN_TIMER_SECONDS.toLong(),
                    maximum = MAX_TIMER_SECONDS.toLong(),
                ),
                "skipClockUi" to booleanSchema(constant = true),
            ),
            required = listOf("durationSeconds", "skipClockUi"),
        ),
        outputSchema = objectSchema(
            properties = mapOf(
                "durationSeconds" to integerSchema(
                    minimum = MIN_TIMER_SECONDS.toLong(),
                    maximum = MAX_TIMER_SECONDS.toLong(),
                ),
                "clockPackage" to stringSchema(
                    enumValues = listOf("com.android.deskclock", "com.google.android.deskclock"),
                ),
                "clockActivity" to stringSchema(maxLength = 256),
                "systemApplication" to booleanSchema(constant = true),
                "skipClockUiRequested" to booleanSchema(constant = true),
                "systemAction" to stringSchema(constant = ANDROID_SET_TIMER_ACTION),
            ),
            required = listOf(
                "durationSeconds",
                "clockPackage",
                "clockActivity",
                "systemApplication",
                "skipClockUiRequested",
                "systemAction",
            ),
        ),
        acceptsArguments = { arguments ->
            arguments is PhoneTimerCreateArguments && arguments.matchesToolContract()
        },
    )

private fun definition(
    name: String,
    title: String,
    description: String,
    permission: PermissionLevel,
    timeoutMillis: Long,
    readOnly: Boolean,
    idempotent: Boolean,
    inputSchema: JsonObject,
    outputSchema: JsonObject,
    acceptsArguments: (ToolArguments) -> Boolean,
    destructive: Boolean = false,
): PhoneCapabilityDefinition = PhoneCapabilityDefinition(
    capability = GoffyToolCapability(
        name = name,
        title = title,
        description = description,
        inputSchema = inputSchema,
        outputSchema = outputSchema,
        annotations = GoffyToolAnnotations(
            readOnlyHint = readOnly,
            destructiveHint = destructive,
            idempotentHint = idempotent,
            openWorldHint = false,
        ),
        metadata = GoffyToolMetadata(
            toolVersion = PHONE_TOOL_VERSION,
            executionTarget = ExecutionTarget.PHONE,
            permission = permission,
            timeoutMillis = timeoutMillis,
        ),
    ),
    acceptsArguments = acceptsArguments,
)

private fun objectSchema(
    properties: Map<String, JsonObject>,
    required: List<String> = emptyList(),
): JsonObject = buildJsonObject {
    put("\$schema", JSON_SCHEMA_DIALECT)
    put("additionalProperties", false)
    put("properties", JsonObject(properties))
    if (required.isNotEmpty()) {
        put("required", JsonArray(required.map { JsonPrimitive(it) }))
    }
    put("type", "object")
}

private fun memoryEntrySchema(required: List<String>): JsonObject = objectSchema(
    properties = mapOf(
        "memoryId" to integerSchema(minimum = 1),
        "text" to stringSchema(maxLength = MAX_MEMORY_TEXT_LENGTH),
        "createdAtEpochMillis" to integerSchema(minimum = 1),
        "provenance" to stringSchema(constant = PHONE_MEMORY_PROVENANCE_USER_APPROVED),
    ),
    required = required,
)

private fun booleanSchema(constant: Boolean? = null): JsonObject = buildJsonObject {
    put("type", "boolean")
    constant?.let { put("const", it) }
}

private fun integerSchema(minimum: Long, maximum: Long? = null): JsonObject = buildJsonObject {
    put("type", "integer")
    put("minimum", minimum)
    maximum?.let { put("maximum", it) }
}

private fun stringSchema(
    maxLength: Int? = null,
    constant: String? = null,
    enumValues: List<String> = emptyList(),
): JsonObject = buildJsonObject {
    put("type", "string")
    put("minLength", 1)
    maxLength?.let { put("maxLength", it) }
    constant?.let { put("const", it) }
    if (enumValues.isNotEmpty()) {
        put("enum", JsonArray(enumValues.map { JsonPrimitive(it) }))
    }
}

private fun arraySchema(itemSchema: JsonObject, maxItems: Int): JsonObject = buildJsonObject {
    put("type", "array")
    put("items", itemSchema)
    put("maxItems", maxItems)
}

private fun nullableStringSchema(maxLength: Int): JsonObject = buildJsonObject {
    put("type", JsonArray(listOf(JsonPrimitive("string"), JsonPrimitive("null"))))
    put("minLength", 1)
    put("maxLength", maxLength)
}
