package dev.goffy.os.protocol

import java.time.Instant
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyProtocolCodecTest {
    private val messageId = UUID.fromString("11111111-1111-4111-8111-111111111111")
    private val discoveryMessageId = UUID.fromString("22222222-2222-4222-8222-222222222222")
    private val messageIds = ArrayDeque(listOf(messageId, discoveryMessageId))
    private val codec = GoffyProtocolCodec(
        now = { Instant.parse("2026-07-13T16:00:00Z") },
        nextMessageId = { messageIds.removeFirst() },
    )

    @Test
    fun createsVersionedTypedInvocationWithoutUserControlledToolName() {
        val request = codec.createToolInvocation("android-test", "mac.system_info")

        assertEquals(messageId, request.messageId)
        assertEquals(discoveryMessageId, request.discoveryMessageId)
        assertEquals("mac.system_info", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.system_info\"," +
                "\"arguments\":{}},\"correlationId\":null}",
            request.encodedMessage,
        )
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"22222222-2222-4222-8222-222222222222\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"CapabilityDiscoveryRequest\",\"payload\":{\"toolName\":" +
                "\"mac.system_info\"},\"correlationId\":null}",
            request.encodedDiscoveryMessage,
        )
    }

    @Test
    fun decodesOnlyTheCompatibleLocallyKnownCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(),
            discoveryMessageId,
            "mac.system_info",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.system_info",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun acceptsAnEmptyDiscoveryWithoutGrantingCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope().replace("\"tools\":[${capabilityTool()}]", "\"tools\":[]"),
            discoveryMessageId,
            "mac.system_info",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(null, response.capability)
    }

    @Test
    fun rejectsDiscoveryThatExpandsOrChangesLocalAuthority() {
        val incompatible = listOf(
            capabilityEnvelope().replace(
                "\"dev.goffy/permission\":\"SAFE\"",
                "\"dev.goffy/permission\":\"CONFIRM\"",
            ),
            capabilityEnvelope().replace(
                "\"dev.goffy/toolVersion\":\"1.0.0\"",
                "\"dev.goffy/toolVersion\":\"2.0.0\"",
            ),
            capabilityEnvelope().replace(
                "\"dev.goffy/executionTarget\":\"MAC\"",
                "\"dev.goffy/executionTarget\":\"CLOUD\"",
            ),
            capabilityEnvelope().replace("\"readOnlyHint\":true", "\"readOnlyHint\":false"),
            capabilityEnvelope().replace("\"additionalProperties\":false", "\"additionalProperties\":true"),
            capabilityEnvelope().replace(
                "\"tools\":[${capabilityTool()}]",
                "\"tools\":[${capabilityTool()},${capabilityTool()}]",
            ),
        )

        incompatible.forEach { raw ->
            assertThrows(ProtocolException::class.java) {
                codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "mac.system_info")
            }
        }
    }

    @Test
    fun rejectsDuplicateDiscoveryAndInvocationIds() {
        val invalidCodec = GoffyProtocolCodec(
            now = { Instant.parse("2026-07-13T16:00:00Z") },
            nextMessageId = { messageId },
        )

        assertThrows(ProtocolException::class.java) {
            invalidCodec.createToolInvocation("android-test", "mac.system_info")
        }
    }

    @Test
    fun decodesStructuredMacResult() {
        val event = codec.decodeEvent(
            resultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.system_info",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacSystemInfo
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("Darwin", content.operatingSystem)
        assertEquals("arm64", content.architecture)
    }

    @Test
    fun rejectsUnsupportedStructuredResultToolEvenWithGenericResultContent() {
        val raw = resultEnvelope()
            .replace("\"mac.system_info\"", "\"phone.battery.status\"")
            .replace("\"MAC\"", "\"PHONE\"")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "phone.battery.status")
        }
    }

    @Test
    fun rejectsUnknownEnvelopeFields() {
        val raw = resultEnvelope().replace("\"payload\":", "\"unexpected\":true,\"payload\":")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.system_info")
        }
    }

    @Test
    fun rejectsMismatchedCorrelationId() {
        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(
                resultEnvelope(),
                UUID.fromString("22222222-2222-4222-8222-222222222222"),
                "mac.system_info",
            )
        }
    }

    @Test
    fun rejectsUnsupportedProtocolVersion() {
        val raw = resultEnvelope().replace("\"0.2.0\"", "\"9.0.0\"")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.system_info")
        }
    }

    @Test
    fun rejectsOversizedMessagesBeforeParsing() {
        val raw = "x".repeat(MAX_PROTOCOL_MESSAGE_BYTES + 1)

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.system_info")
        }
    }

    @Test
    fun phoneBatteryStatusRemainsRangeNeutralAtTheDomainBoundary() {
        val status = PhoneBatteryStatus(levelPercent = 135, charging = false)

        assertEquals(135, status.levelPercent)
        assertFalse(status.charging)
    }

    private fun resultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.system_info","executionTarget":"MAC","structuredContent":{"status":"available","operatingSystem":"Darwin","architecture":"arm64"}},"correlationId":"$messageId"}"""

    private fun capabilityEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"99999999-9999-4999-8999-999999999999","timestamp":"2026-07-13T16:00:00Z","deviceId":"goffy-hub","messageType":"CapabilityDiscoveryResponse","payload":{"mcpProtocolVersion":"2025-11-25","listChanged":false,"tools":[${capabilityTool()}]},"correlationId":"$discoveryMessageId"}"""

    private fun capabilityTool(): String =
        """{"name":"mac.system_info","title":"Mac system information","description":"Read a minimal, non-sensitive snapshot of the Hub host.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{},"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"architecture":{"type":"string"},"operatingSystem":{"type":"string"},"status":{"type":"string"}},"required":["status","operatingSystem","architecture"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""
}
