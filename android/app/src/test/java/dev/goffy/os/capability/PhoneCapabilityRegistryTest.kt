package dev.goffy.os.capability

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.NoToolArguments
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PHONE_QR_READ_TOOL
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneCapabilityRegistryTest {
    private val registry = PhoneCapabilityRegistry.create()

    @Test
    fun registryIsDeterministicBoundedAndPermissionPreserving() {
        assertEquals(
            listOf(
                PHONE_BATTERY_STATUS_TOOL,
                PHONE_DEVICE_INFO_TOOL,
                PHONE_FLASHLIGHT_SET_TOOL,
                PHONE_NOTE_CREATE_TOOL,
                PHONE_QR_READ_TOOL,
                PHONE_TIMER_CREATE_TOOL,
            ),
            registry.capabilities.map { it.name },
        )
        assertTrue(registry.capabilities.size <= PhoneCapabilityRegistry.MAX_PHONE_CAPABILITIES)

        registry.capabilities.forEach { capability ->
            assertEquals(ExecutionTarget.PHONE, capability.metadata.executionTarget)
            assertEquals("1.0.0", capability.metadata.toolVersion)
            assertTrue(capability.metadata.timeoutMillis in 1..30_000)
            assertFalse(capability.annotations.destructiveHint)
            assertFalse(capability.annotations.openWorldHint)
            assertClosedObjectSchema(capability.inputSchema)
            assertClosedObjectSchema(capability.outputSchema)
        }
        assertEquals(PermissionLevel.SAFE, registry.find(PHONE_BATTERY_STATUS_TOOL)?.metadata?.permission)
        assertEquals(PermissionLevel.SAFE, registry.find(PHONE_DEVICE_INFO_TOOL)?.metadata?.permission)
        assertEquals(PermissionLevel.CONFIRM, registry.find(PHONE_FLASHLIGHT_SET_TOOL)?.metadata?.permission)
        assertEquals(PermissionLevel.CONFIRM, registry.find(PHONE_NOTE_CREATE_TOOL)?.metadata?.permission)
        assertEquals(PermissionLevel.SAFE, registry.find(PHONE_QR_READ_TOOL)?.metadata?.permission)
        assertEquals(PermissionLevel.CONFIRM, registry.find(PHONE_TIMER_CREATE_TOOL)?.metadata?.permission)
    }

    @Test
    fun matchingFailsClosedForUnknownTargetPermissionAndArguments() {
        assertNull(registry.find("phone.unknown"))
        assertNull(
            registry.match(
                PHONE_BATTERY_STATUS_TOOL,
                ExecutionTarget.MAC,
                PermissionLevel.SAFE,
                NoToolArguments,
            ),
        )
        assertNull(
            registry.match(
                PHONE_NOTE_CREATE_TOOL,
                ExecutionTarget.PHONE,
                PermissionLevel.SAFE,
                PhoneNoteCreateArguments("approved text"),
            ),
        )
        assertNull(
            registry.match(
                PHONE_NOTE_CREATE_TOOL,
                ExecutionTarget.PHONE,
                PermissionLevel.CONFIRM,
                PhoneNoteCreateArguments("\u0000"),
            ),
        )
        assertNull(
            registry.match(
                PHONE_TIMER_CREATE_TOOL,
                ExecutionTarget.PHONE,
                PermissionLevel.CONFIRM,
                PhoneTimerCreateArguments(durationSeconds = 30, skipClockUi = false),
            ),
        )
        assertTrue(
            registry.match(
                PHONE_TIMER_CREATE_TOOL,
                ExecutionTarget.PHONE,
                PermissionLevel.CONFIRM,
                PhoneTimerCreateArguments(durationSeconds = 30, skipClockUi = true),
            ) != null,
        )
    }

    @Test
    fun duplicateAndUnsafeDefinitionsAreRejected() {
        val battery = checkNotNull(registry.find(PHONE_BATTERY_STATUS_TOOL))
        val definition = PhoneCapabilityDefinition(battery) { it == NoToolArguments }
        assertThrows(IllegalArgumentException::class.java) {
            PhoneCapabilityRegistry(listOf(definition, definition))
        }
        assertThrows(IllegalArgumentException::class.java) {
            PhoneCapabilityRegistry(
                listOf(
                    definition.copy(
                        capability = battery.copy(
                            metadata = battery.metadata.copy(permission = PermissionLevel.CONFIRM),
                        ),
                    ),
                ),
            )
        }
    }

    @Test
    fun sharedFixtureMatchesEveryMcpDescriptor() {
        val fixture = checkNotNull(
            javaClass.classLoader?.getResource("phone-tool-capabilities.json"),
        ).readText()
        val expected = Json.parseToJsonElement(fixture)
        val actual = JsonArray(registry.capabilities.map { it.toMcpJson() })

        assertEquals(expected, actual)
    }

    private fun assertClosedObjectSchema(schema: JsonObject) {
        assertEquals(
            JsonPrimitive("https://json-schema.org/draft/2020-12/schema"),
            schema["\$schema"],
        )
        assertEquals(JsonPrimitive("object"), schema["type"])
        assertEquals(JsonPrimitive(false), schema["additionalProperties"])
        assertTrue(schema["properties"] is JsonObject)
    }
}
