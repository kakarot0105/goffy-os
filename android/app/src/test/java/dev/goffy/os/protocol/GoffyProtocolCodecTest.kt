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
    fun createsVersionedMacFilesListInvocationWithTypedArguments() {
        val request = codec.createToolInvocation(
            "android-test",
            "mac.files.list",
            MacFilesListArguments(rootIndex = 0, maxEntries = 25, includeHidden = false),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("mac.files.list", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.files.list\"," +
                "\"arguments\":{\"rootIndex\":0,\"relativePath\":\"\",\"maxEntries\":25," +
                "\"includeHidden\":false}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsVersionedGitStatusInvocationWithTypedArguments() {
        val request = codec.createToolInvocation(
            "android-test",
            "git.status",
            GitStatusArguments(repoIndex = 0, maxChanges = 25, includeUntracked = true),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("git.status", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"git.status\"," +
                "\"arguments\":{\"repoIndex\":0,\"maxChanges\":25," +
                "\"includeUntracked\":true}},\"correlationId\":null}",
            request.encodedMessage,
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
    fun decodesCompatibleMacFilesListCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(macFilesCapabilityTool()),
            discoveryMessageId,
            "mac.files.list",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.files.list",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun decodesCompatibleGitStatusCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(gitStatusCapabilityTool()),
            discoveryMessageId,
            "git.status",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "git.status",
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
    fun decodesStructuredMacFilesListResult() {
        val event = codec.decodeEvent(
            macFilesResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.files.list",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacFilesList
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("goffy", content.rootName)
        assertEquals(listOf("README.md", "docs"), content.entries.map { it.name })
        assertFalse(content.truncated)
    }

    @Test
    fun decodesStructuredGitStatusResult() {
        val event = codec.decodeEvent(
            gitStatusResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "git.status",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as GitStatus
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("goffy", content.repoName)
        assertEquals("main", content.branch)
        assertEquals(1, content.stagedCount)
        assertEquals(1, content.untrackedCount)
        assertEquals(listOf("README.md", "TODO.md"), content.changes.map { it.path })
        assertFalse(content.truncated)
    }

    @Test
    fun rejectsContradictoryGitStatusResultAtReducerContractBoundary() {
        val event = codec.decodeEvent(
            gitStatusResultEnvelope()
                .replace("\"clean\":false", "\"clean\":true")
                .replace("\"stagedCount\":1", "\"stagedCount\":0")
                .replace("\"untrackedCount\":1", "\"untrackedCount\":0"),
            expectedCorrelationId = messageId,
            expectedToolName = "git.status",
        )

        val result = event as ExecutionEvent.Result
        val content = result.content as GitStatus

        assertFalse(content.matchesToolContract())
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

    private fun macFilesResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.files.list","executionTarget":"MAC","structuredContent":{"status":"available","rootIndex":0,"rootName":"goffy","relativePath":"","truncated":false,"approvedRoots":[{"rootIndex":0,"name":"goffy"}],"entries":[{"name":"README.md","nameTruncated":false,"kind":"file","sizeBytes":1024,"modifiedEpochSeconds":1784610000},{"name":"docs","nameTruncated":false,"kind":"directory","sizeBytes":null,"modifiedEpochSeconds":1784610001}]}},"correlationId":"$messageId"}"""

    private fun gitStatusResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"git.status","executionTarget":"MAC","structuredContent":{"status":"available","repoIndex":0,"repoName":"goffy","branch":"main","headOidShort":"0123456789abcdef","upstream":null,"ahead":null,"behind":null,"clean":false,"stagedCount":1,"unstagedCount":0,"untrackedCount":1,"conflictCount":0,"truncated":false,"approvedRepos":[{"repoIndex":0,"name":"goffy"}],"changes":[{"path":"README.md","pathTruncated":false,"indexStatus":"M","workingTreeStatus":".","kind":"tracked"},{"path":"TODO.md","pathTruncated":false,"indexStatus":"?","workingTreeStatus":"?","kind":"untracked"}]}},"correlationId":"$messageId"}"""

    private fun capabilityEnvelope(tool: String = capabilityTool()): String =
        """{"protocolVersion":"0.2.0","messageId":"99999999-9999-4999-8999-999999999999","timestamp":"2026-07-13T16:00:00Z","deviceId":"goffy-hub","messageType":"CapabilityDiscoveryResponse","payload":{"mcpProtocolVersion":"2025-11-25","listChanged":false,"tools":[$tool]},"correlationId":"$discoveryMessageId"}"""

    private fun capabilityTool(): String =
        """{"name":"mac.system_info","title":"Mac system information","description":"Read a minimal, non-sensitive snapshot of the Hub host.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{},"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"architecture":{"type":"string"},"operatingSystem":{"type":"string"},"status":{"type":"string"}},"required":["status","operatingSystem","architecture"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun macFilesCapabilityTool(): String =
        """{"name":"mac.files.list","title":"Mac approved-root file listing","description":"List entries inside explicitly approved Mac directories without following symlink targets or exposing absolute root paths.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"includeHidden":{"default":false,"type":"boolean"},"maxEntries":{"default":25,"maximum":32,"minimum":1,"type":"integer"},"relativePath":{"default":"","maxLength":512,"type":"string"},"rootIndex":{"default":0,"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"MacFilesApprovedRootOutput":{"additionalProperties":false,"properties":{"name":{"type":"string"},"rootIndex":{"type":"integer"}},"required":["rootIndex","name"],"type":"object"},"MacFilesListEntryOutput":{"additionalProperties":false,"properties":{"kind":{"enum":["file","directory","symlink","other"],"type":"string"},"modifiedEpochSeconds":{"anyOf":[{"type":"integer"},{"type":"null"}]},"name":{"type":"string"},"nameTruncated":{"type":"boolean"},"sizeBytes":{"anyOf":[{"type":"integer"},{"type":"null"}]}},"required":["name","nameTruncated","kind","sizeBytes","modifiedEpochSeconds"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"approvedRoots":{"items":{"${'$'}ref":"#/${'$'}defs/MacFilesApprovedRootOutput"},"maxItems":8,"type":"array"},"entries":{"items":{"${'$'}ref":"#/${'$'}defs/MacFilesListEntryOutput"},"maxItems":32,"type":"array"},"relativePath":{"type":"string"},"rootIndex":{"type":"integer"},"rootName":{"type":"string"},"status":{"type":"string"},"truncated":{"type":"boolean"}},"required":["status","rootIndex","rootName","relativePath","truncated","approvedRoots","entries"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun gitStatusCapabilityTool(): String =
        """{"name":"git.status","title":"Approved Git repository status","description":"Read bounded status metadata for explicitly approved local Git repositories without running arbitrary commands or exposing repository root paths.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"includeUntracked":{"default":true,"type":"boolean"},"maxChanges":{"default":25,"maximum":32,"minimum":1,"type":"integer"},"repoIndex":{"default":0,"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"GitStatusApprovedRepoOutput":{"additionalProperties":false,"properties":{"name":{"maxLength":64,"minLength":1,"type":"string"},"repoIndex":{"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"required":["repoIndex","name"],"type":"object"},"GitStatusChangeOutput":{"additionalProperties":false,"properties":{"indexStatus":{"maxLength":1,"minLength":1,"type":"string"},"kind":{"enum":["tracked","untracked","conflict"],"type":"string"},"path":{"maxLength":160,"minLength":1,"type":"string"},"pathTruncated":{"type":"boolean"},"workingTreeStatus":{"maxLength":1,"minLength":1,"type":"string"}},"required":["path","pathTruncated","indexStatus","workingTreeStatus","kind"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"ahead":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null},"approvedRepos":{"items":{"${'$'}ref":"#/${'$'}defs/GitStatusApprovedRepoOutput"},"maxItems":8,"type":"array"},"behind":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null},"branch":{"anyOf":[{"maxLength":96,"type":"string"},{"type":"null"}],"default":null},"changes":{"items":{"${'$'}ref":"#/${'$'}defs/GitStatusChangeOutput"},"maxItems":32,"type":"array"},"clean":{"type":"boolean"},"conflictCount":{"minimum":0,"type":"integer"},"headOidShort":{"anyOf":[{"maxLength":16,"type":"string"},{"type":"null"}],"default":null},"repoIndex":{"exclusiveMaximum":8,"minimum":0,"type":"integer"},"repoName":{"maxLength":64,"minLength":1,"type":"string"},"stagedCount":{"minimum":0,"type":"integer"},"status":{"maxLength":64,"minLength":1,"type":"string"},"truncated":{"type":"boolean"},"unstagedCount":{"minimum":0,"type":"integer"},"untrackedCount":{"minimum":0,"type":"integer"},"upstream":{"anyOf":[{"maxLength":128,"type":"string"},{"type":"null"}],"default":null}},"required":["status","repoIndex","repoName","clean","stagedCount","unstagedCount","untrackedCount","conflictCount","truncated","approvedRepos","changes"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""
}
