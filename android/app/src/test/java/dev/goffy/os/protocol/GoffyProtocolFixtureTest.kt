package dev.goffy.os.protocol

import java.time.Instant
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyProtocolFixtureTest {
    @Test
    fun sharedFixtureMatchesOutboundBytesAndTypedInboundEvents() {
        val lines = checkNotNull(javaClass.classLoader?.getResource("mac-system-info-flow.jsonl"))
            .readText()
            .lineSequence()
            .filter(String::isNotBlank)
            .toList()
        val invocationId = UUID.fromString("11111111-1111-4111-8111-111111111111")
        val codec = GoffyProtocolCodec(
            now = { Instant.parse("2026-07-13T16:00:00Z") },
            nextMessageId = { invocationId },
        )

        val request = codec.createToolInvocation("android-test", "mac.system_info")
        assertEquals(lines.first(), request.encodedMessage)

        val events = lines.drop(1).map { raw ->
            codec.decodeEvent(raw, invocationId, "mac.system_info")
        }
        assertTrue(events[0] is HubStreamEvent.Progress)
        assertTrue(events[1] is HubStreamEvent.Progress)
        assertTrue(events[2] is HubStreamEvent.Result)
        assertTrue(events[3] is HubStreamEvent.Verification)
        assertEquals("Darwin", (events[2] as HubStreamEvent.Result).content.operatingSystem)
        assertTrue((events[3] as HubStreamEvent.Verification).succeeded)
    }
}
