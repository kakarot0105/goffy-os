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
    private val codec = GoffyProtocolCodec(
        now = { Instant.parse("2026-07-13T16:00:00Z") },
        nextMessageId = { messageId },
    )

    @Test
    fun createsVersionedTypedInvocationWithoutUserControlledToolName() {
        val request = codec.createToolInvocation("android-test", "mac.system_info")

        assertEquals(messageId, request.messageId)
        assertEquals("mac.system_info", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.1.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.system_info\"," +
                "\"arguments\":{}},\"correlationId\":null}",
            request.encodedMessage,
        )
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
        val raw = resultEnvelope().replace("\"0.1.0\"", "\"9.0.0\"")

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
        """{"protocolVersion":"0.1.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.system_info","executionTarget":"MAC","structuredContent":{"status":"available","operatingSystem":"Darwin","architecture":"arm64"}},"correlationId":"$messageId"}"""
}
