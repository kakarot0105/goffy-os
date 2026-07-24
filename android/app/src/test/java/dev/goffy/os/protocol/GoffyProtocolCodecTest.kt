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
    fun createsVersionedMacProcessesListInvocationWithTypedArguments() {
        val request = codec.createToolInvocation(
            "android-test",
            "mac.processes.list",
            MacProcessesListArguments(maxEntries = 10),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("mac.processes.list", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.processes.list\"," +
                "\"arguments\":{\"maxEntries\":10}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsVersionedMacAppsListInvocationWithTypedArguments() {
        val request = codec.createToolInvocation(
            "android-test",
            "mac.apps.list",
            MacAppsListArguments(maxEntries = 10),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("mac.apps.list", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.apps.list\"," +
                "\"arguments\":{\"maxEntries\":10}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsVersionedMacAppsOpenInvocationWithTypedArguments() {
        val request = codec.createToolInvocation(
            "android-test",
            "mac.apps.open",
            MacAppsOpenArguments(displayName = "Safari"),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("mac.apps.open", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.apps.open\"," +
                "\"arguments\":{\"displayName\":\"Safari\"}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsConfirmMacAppsOpenInvocationWithTaskBoundApprovalState() {
        val taskId = UUID.fromString("33333333-3333-4333-8333-333333333333")
        val credentialId = UUID.fromString("55555555-5555-4555-8555-555555555555")
        val request = codec.createToolInvocation(
            "android-test",
            "mac.apps.open",
            MacAppsOpenArguments(displayName = "Safari"),
            approvalGrant = ToolApprovalGrant(
                taskId = taskId,
                credentialId = credentialId,
                issuedAtEpochMillis = 1_784_300_400_000,
                expiresAtEpochMillis = 1_784_300_460_000,
            ),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("mac.apps.open", request.toolName)
        assertEquals(1_784_300_460_000, request.expiresAtEpochMillis)
        assertEquals(taskId, request.approvedTaskId)
        assertEquals(credentialId, request.approvedCredentialId)
        assertEquals(
            "48bcd955f3fdbcaddfc3844e3a9bdc8a9a3791bab296bec333e8e7231244793e",
            request.approvedArgumentsSha256,
        )
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.apps.open\"," +
                "\"arguments\":{\"displayName\":\"Safari\"}," +
                "\"taskId\":\"33333333-3333-4333-8333-333333333333\"},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun decodesHubApprovalRequestAndCreatesApprovalResponse() {
        val taskId = UUID.fromString("33333333-3333-4333-8333-333333333333")
        val responseMessageId = UUID.fromString("44444444-4444-4444-8444-444444444444")
        val approvalId = UUID.fromString("55555555-5555-4555-8555-555555555555")
        val credentialId = UUID.fromString("77777777-7777-4777-8777-777777777777")
        val ids = ArrayDeque(listOf(messageId, discoveryMessageId, responseMessageId))
        val localCodec = GoffyProtocolCodec(
            now = { Instant.parse("2026-07-13T16:00:00Z") },
            nextMessageId = { ids.removeFirst() },
        )
        val request = localCodec.createToolInvocation(
            "android-test",
            "mac.apps.open",
            MacAppsOpenArguments(displayName = "Safari"),
            approvalGrant = ToolApprovalGrant(
                taskId = taskId,
                credentialId = credentialId,
                issuedAtEpochMillis = 1_784_300_400_000,
                expiresAtEpochMillis = 1_784_300_460_000,
            ),
        )
        val rawApprovalRequest =
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"66666666-6666-4666-8666-666666666666\"," +
                "\"timestamp\":\"2026-07-13T16:00:01Z\",\"deviceId\":\"goffy-hub\"," +
                "\"messageType\":\"ApprovalRequest\",\"payload\":{\"schemaVersion\":\"goffy.approval.v1\"," +
                "\"approvalId\":\"55555555-5555-4555-8555-555555555555\"," +
                "\"taskId\":\"33333333-3333-4333-8333-333333333333\"," +
                "\"toolName\":\"mac.apps.open\"," +
                "\"argumentsSha256\":\"48bcd955f3fdbcaddfc3844e3a9bdc8a9a3791bab296bec333e8e7231244793e\"," +
                "\"issuedAtEpochMillis\":1784300401000," +
                "\"expiresAtEpochMillis\":1784300461000}," +
                "\"correlationId\":\"11111111-1111-4111-8111-111111111111\"}"

        val approval = checkNotNull(
            localCodec.decodeApprovalRequestOrNull(
                rawMessage = rawApprovalRequest,
                expectedCorrelationId = request.messageId,
                expectedToolName = request.toolName,
                expectedTaskId = request.approvedTaskId,
                expectedArgumentsSha256 = request.approvedArgumentsSha256,
            ),
        )

        assertEquals(approvalId, approval.approvalId)
        assertEquals(taskId, approval.taskId)
        assertEquals(1_784_300_401_000, approval.issuedAtEpochMillis)
        assertEquals(1_784_300_461_000, approval.expiresAtEpochMillis)
        assertEquals(
            "{\"approvalId\":\"55555555-5555-4555-8555-555555555555\"," +
                "\"approved\":true,\"argumentsSha256\":\"48bcd955f3fdbcaddfc3844e3a9bdc8a9a3791bab296bec333e8e7231244793e\"," +
                "\"credentialId\":\"77777777-7777-4777-8777-777777777777\"," +
                "\"expiresAtEpochMillis\":1784300461000,\"issuedAtEpochMillis\":1784300401000," +
                "\"schemaVersion\":\"goffy.approval.signed-payload.v1\"," +
                "\"taskId\":\"33333333-3333-4333-8333-333333333333\"," +
                "\"toolName\":\"mac.apps.open\"}",
            localCodec.approvalSigningPayload(approval, credentialId).decodeToString(),
        )
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"44444444-4444-4444-8444-444444444444\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ApprovalResponse\",\"payload\":{\"schemaVersion\":\"goffy.approval.v1\"," +
                "\"approvalId\":\"55555555-5555-4555-8555-555555555555\"," +
                "\"taskId\":\"33333333-3333-4333-8333-333333333333\"," +
                "\"approved\":true,\"proof\":{\"schemaVersion\":\"goffy.approval.proof.v1\"," +
                "\"algorithm\":\"ECDSA_P256_SHA256\"," +
                "\"publicKeySha256\":\"0000000000000000000000000000000000000000000000000000000000000000\"," +
                "\"signatureBase64\":\"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\"}},\"correlationId\":\"11111111-1111-4111-8111-111111111111\"}",
            localCodec.createApprovalResponse(
                "android-test",
                request.messageId,
                approval,
                proof = ApprovalResponseProof(
                    algorithm = "ECDSA_P256_SHA256",
                    publicKeySha256 = "0".repeat(64),
                    signatureBase64 = "A".repeat(96),
                ),
            ),
        )
    }

    @Test
    fun createsVersionedMacFilesLargestInvocationWithTypedArguments() {
        val request = codec.createToolInvocation(
            "android-test",
            "mac.files.largest",
            MacFilesLargestArguments(rootIndex = 0, maxEntries = 10, maxDepth = 4, includeHidden = false),
        )

        assertEquals(messageId, request.messageId)
        assertEquals("mac.files.largest", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.files.largest\"," +
                "\"arguments\":{\"rootIndex\":0,\"relativePath\":\"\",\"maxEntries\":10," +
                "\"maxDepth\":4,\"includeHidden\":false}},\"correlationId\":null}",
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
    fun createsVersionedMacClipboardReadInvocationWithoutArguments() {
        val request = codec.createToolInvocation("android-test", "mac.clipboard.read")

        assertEquals(messageId, request.messageId)
        assertEquals("mac.clipboard.read", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"mac.clipboard.read\"," +
                "\"arguments\":{}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsVersionedGoffyRomStatusInvocationWithoutArguments() {
        val request = codec.createToolInvocation("android-test", "goffy.rom.status")

        assertEquals(messageId, request.messageId)
        assertEquals("goffy.rom.status", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"goffy.rom.status\"," +
                "\"arguments\":{}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsVersionedGoffyRomChecklistInvocationWithoutArguments() {
        val request = codec.createToolInvocation("android-test", "goffy.rom.checklist")

        assertEquals(messageId, request.messageId)
        assertEquals("goffy.rom.checklist", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"goffy.rom.checklist\"," +
                "\"arguments\":{}},\"correlationId\":null}",
            request.encodedMessage,
        )
    }

    @Test
    fun createsVersionedGoffyRomFeaturesInvocationWithoutArguments() {
        val request = codec.createToolInvocation("android-test", "goffy.rom.features")

        assertEquals(messageId, request.messageId)
        assertEquals("goffy.rom.features", request.toolName)
        assertEquals(
            "{\"protocolVersion\":\"0.2.0\",\"messageId\":\"11111111-1111-4111-8111-111111111111\"," +
                "\"timestamp\":\"2026-07-13T16:00:00Z\",\"deviceId\":\"android-test\"," +
                "\"messageType\":\"ToolInvocation\",\"payload\":{\"toolName\":\"goffy.rom.features\"," +
                "\"arguments\":{}},\"correlationId\":null}",
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
    fun decodesCompatibleGoffyRomStatusCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(goffyRomStatusCapabilityTool()),
            discoveryMessageId,
            "goffy.rom.status",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "goffy.rom.status",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun decodesCompatibleGoffyRomChecklistCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(goffyRomChecklistCapabilityTool()),
            discoveryMessageId,
            "goffy.rom.checklist",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "goffy.rom.checklist",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun decodesCompatibleGoffyRomFeaturesCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(goffyRomFeaturesCapabilityTool()),
            discoveryMessageId,
            "goffy.rom.features",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "goffy.rom.features",
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
    fun decodesCompatibleMacFilesLargestCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(macFilesLargestCapabilityTool()),
            discoveryMessageId,
            "mac.files.largest",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.files.largest",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun decodesCompatibleMacProcessesListCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(macProcessesCapabilityTool()),
            discoveryMessageId,
            "mac.processes.list",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.processes.list",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun decodesCompatibleMacAppsListCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(macAppsCapabilityTool()),
            discoveryMessageId,
            "mac.apps.list",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.apps.list",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun decodesCompatibleMacAppsOpenCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(macAppsOpenCapabilityTool()),
            discoveryMessageId,
            "mac.apps.open",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.apps.open",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "CONFIRM",
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
    fun decodesCompatibleMacClipboardReadCapability() {
        val response = codec.decodeCapabilityDiscovery(
            capabilityEnvelope(macClipboardCapabilityTool()),
            discoveryMessageId,
            "mac.clipboard.read",
        ) as CapabilityDiscoveryMessage.Response

        assertEquals(
            DiscoveredToolCapability(
                name = "mac.clipboard.read",
                toolVersion = "1.0.0",
                executionTarget = ExecutionTarget.MAC,
                permission = "SAFE",
                timeoutMillis = 3_000,
            ),
            response.capability,
        )
    }

    @Test
    fun rejectsMacClipboardReadCapabilityWithChangedDefault() {
        val raw = capabilityEnvelope(
            macClipboardCapabilityTool().replace("\"default\":1000", "\"default\":2000"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "mac.clipboard.read")
        }
    }

    @Test
    fun rejectsMacProcessesListCapabilityWithExpandedResultLimit() {
        val raw = capabilityEnvelope(
            macProcessesCapabilityTool().replace("\"maxItems\":25", "\"maxItems\":100"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "mac.processes.list")
        }
    }

    @Test
    fun rejectsGoffyRomStatusCapabilityWithExpandedBlockerLimit() {
        val raw = capabilityEnvelope(
            goffyRomStatusCapabilityTool().replace("\"maxItems\":8", "\"maxItems\":64"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "goffy.rom.status")
        }
    }

    @Test
    fun rejectsGoffyRomChecklistCapabilityWithExpandedStepLimit() {
        val raw = capabilityEnvelope(
            goffyRomChecklistCapabilityTool().replace("\"maxItems\": 6", "\"maxItems\": 64"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "goffy.rom.checklist")
        }
    }

    @Test
    fun rejectsGoffyRomChecklistCapabilityWithUnknownStepKindEnum() {
        val raw = capabilityEnvelope(
            goffyRomChecklistCapabilityTool()
                .replace("\"HUMAN_DECISION\"]", "\"HUMAN_DECISION\", \"ROOT_SHELL\"]"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "goffy.rom.checklist")
        }
    }

    @Test
    fun rejectsMacAppsListCapabilityWithExpandedResultLimit() {
        val raw = capabilityEnvelope(
            macAppsCapabilityTool().replace("\"maxItems\":25", "\"maxItems\":100"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "mac.apps.list")
        }
    }

    @Test
    fun rejectsMacAppsOpenCapabilityIfItClaimsSafeReadOnlyAuthority() {
        val raw = capabilityEnvelope(
            macAppsOpenCapabilityTool()
                .replace("\"dev.goffy/permission\":\"CONFIRM\"", "\"dev.goffy/permission\":\"SAFE\"")
                .replace("\"readOnlyHint\":false", "\"readOnlyHint\":true")
                .replace("\"idempotentHint\":false", "\"idempotentHint\":true"),
        )

        assertThrows(ProtocolException::class.java) {
            codec.decodeCapabilityDiscovery(raw, discoveryMessageId, "mac.apps.open")
        }
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
    fun decodesStructuredGoffyRomStatusResult() {
        val event = codec.decodeEvent(
            goffyRomStatusResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "goffy.rom.status",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as GoffyRomStatus
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("ROM-0", content.milestone)
        assertEquals("BLOCKED", content.refreshStatus)
        assertEquals("BLOCKED", content.installDecision)
        assertEquals("MISSING", content.unlockGateStatus)
        assertEquals("MISSING", content.stockRestoreGateStatus)
        assertEquals("MISSING", content.gsiCandidateGateStatus)
        assertEquals("MISSING", content.dsuPreflightGateStatus)
        assertEquals("MISSING", content.fastbootGateStatus)
        assertEquals("WITHHELD", content.destructiveApprovalStatus)
        assertEquals(1, content.blockerCount)
        assertEquals(listOf("exact stock restore evidence is missing"), content.blockers)
        assertFalse(content.romReady)
    }

    @Test
    fun decodesStructuredGoffyRomChecklistResult() {
        val event = codec.decodeEvent(
            goffyRomChecklistResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "goffy.rom.checklist",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as GoffyRomChecklist
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("ROM-0", content.milestone)
        assertEquals("BLOCKED_EVIDENCE", content.checklistStatus)
        assertEquals("withheld", content.destructiveActions)
        assertEquals(3, content.totalStepCount)
        assertEquals(1, content.doneStepCount)
        assertEquals(2, content.remainingStepCount)
        assertEquals("Record exact stock restore evidence", content.nextStepTitle)
        assertEquals("READY", content.nextStepStatus)
        assertEquals(2, content.nextSteps.size)
        assertEquals("Record read-only DSU preflight", content.nextSteps[1].title)
        assertEquals(1, content.blockerCount)
        assertEquals(listOf("exact stock restore evidence is missing"), content.blockers)
    }

    @Test
    fun decodesStructuredGoffyRomFeaturesResult() {
        val event = codec.decodeEvent(
            goffyRomFeaturesResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "goffy.rom.features",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as GoffyRomFeatures
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("GOFFY ROM-0 Jarvis Payload", content.payloadName)
        assertEquals("ROM-0", content.targetStage)
        assertEquals("GOFFY LITE", content.defaultPerformanceMode)
        assertFalse(content.rom0Flashable)
        assertFalse(content.privileged)
        assertFalse(content.platformSigned)
        assertFalse(content.romDestructiveActionsIncluded)
        assertEquals(2, content.featureCount)
        assertEquals("GOFFY Home Surface", content.features[0].title)
        assertEquals(listOf("unlock_bootloader", "flash_image"), content.blockedRomActions)
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
    fun decodesStructuredMacFilesLargestResult() {
        val event = codec.decodeEvent(
            macFilesLargestResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.files.largest",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacFilesLargest
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("goffy", content.rootName)
        assertEquals(listOf("build/output.apk", "README.md"), content.entries.map { it.relativePath })
        assertEquals(listOf(12_345_678L, 1_024L), content.entries.map { it.sizeBytes })
        assertEquals(4_102_444_800L, content.entries.first().modifiedEpochSeconds)
        assertFalse(content.truncated)
    }

    @Test
    fun decodesStructuredMacProcessesListResult() {
        val event = codec.decodeEvent(
            macProcessesResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.processes.list",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacProcessesList
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals(3, content.processCount)
        assertEquals(listOf("WindowServer", "loginwindow"), content.entries.map { it.name })
        assertEquals(listOf(512_000_000L, 128_000_000L), content.entries.map { it.rssBytes })
        assertEquals(1_784_620_000L, content.entries.first().createTimeEpochSeconds)
        assertTrue(content.truncated)
    }

    @Test
    fun decodesStructuredMacAppsListResult() {
        val event = codec.decodeEvent(
            macAppsResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.apps.list",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacAppsList
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals(3, content.appCount)
        assertEquals(listOf("Safari", "Terminal"), content.entries.map { it.displayName })
        assertEquals(listOf("com.apple.Safari", "com.apple.Terminal"), content.entries.map { it.bundleId })
        assertTrue(content.truncated)
    }

    @Test
    fun decodesStructuredMacAppsOpenResult() {
        val event = codec.decodeEvent(
            macAppsOpenResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.apps.open",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacAppOpened
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("running", content.status)
        assertEquals("Safari", content.displayName)
        assertEquals("com.apple.Safari", content.bundleId)
        assertTrue(content.verified)
    }

    @Test
    fun rejectsMacAppsOpenResultWithoutVerifiedState() {
        val raw = macAppsOpenResultEnvelope().replace("\"verified\":true", "\"verified\":false")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.apps.open")
        }
    }

    @Test
    fun rejectsMacProcessesListPathLikeNames() {
        val raw = macProcessesResultEnvelope().replace("WindowServer", "/Users/example/private")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.processes.list")
        }
    }

    @Test
    fun rejectsContradictoryGoffyRomReadyResult() {
        val raw = goffyRomStatusResultEnvelope().replace("\"romReady\":false", "\"romReady\":true")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "goffy.rom.status")
        }
    }

    @Test
    fun rejectsGoffyRomChecklistPathLikeStepText() {
        val raw = goffyRomChecklistResultEnvelope()
            .replace("Record exact stock restore evidence", "/Users/example/private")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "goffy.rom.checklist")
        }
    }

    @Test
    fun rejectsGoffyRomChecklistCommandLikeStepText() {
        val raw = goffyRomChecklistResultEnvelope()
            .replace("Record exact stock restore evidence", "adb reboot bootloader now")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "goffy.rom.checklist")
        }
    }

    @Test
    fun rejectsGoffyRomChecklistUnknownStepEnums() {
        val raw = goffyRomChecklistResultEnvelope()
            .replace("\"kind\":\"HUMAN_ONLY\"", "\"kind\":\"ROOT_SHELL\"")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "goffy.rom.checklist")
        }
    }

    @Test
    fun rejectsGoffyRomFeaturesPathLikeTitle() {
        val raw = goffyRomFeaturesResultEnvelope().replace("GOFFY Home Surface", "/Users/example/private")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "goffy.rom.features")
        }
    }

    @Test
    fun rejectsGoffyRomFeaturesPrivilegedClaim() {
        val raw = goffyRomFeaturesResultEnvelope().replace("\"privileged\":false", "\"privileged\":true")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "goffy.rom.features")
        }
    }

    @Test
    fun rejectsMacAppsListPathLikeNames() {
        val raw = macAppsResultEnvelope().replace("Safari", "/Applications/Safari")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.apps.list")
        }
    }

    @Test
    fun rejectsNegativeMacFilesLargestModifiedTime() {
        val raw = macFilesLargestResultEnvelope()
            .replace("\"modifiedEpochSeconds\":4102444800", "\"modifiedEpochSeconds\":-1")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.files.largest")
        }
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
    fun decodesStructuredMacClipboardReadResult() {
        val event = codec.decodeEvent(
            macClipboardResultEnvelope(),
            expectedCorrelationId = messageId,
            expectedToolName = "mac.clipboard.read",
        )

        assertTrue(event is ExecutionEvent.Result)
        val result = event as ExecutionEvent.Result
        val content = result.content as MacClipboardRead
        assertEquals(ExecutionTarget.MAC, result.executionTarget)
        assertEquals("available", content.status)
        assertEquals("copied text", content.text)
        assertFalse(content.textTruncated)
    }

    @Test
    fun rejectsMacClipboardReadFileUrlText() {
        val raw = macClipboardResultEnvelope()
            .replace("copied text", "file:///Users/example/private.txt")
            .replace("\"characterCount\":11", "\"characterCount\":33")

        assertThrows(ProtocolException::class.java) {
            codec.decodeEvent(raw, messageId, "mac.clipboard.read")
        }
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

    private fun goffyRomStatusResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"goffy.rom.status","executionTarget":"MAC","structuredContent":{"status":"available","milestone":"ROM-0","summary":"ROM-0 is BLOCKED; 1 blocker remains","generatedAt":"2026-07-22T15:00:00Z","refreshSchemaVersion":"goffy.rom0-refresh-report.v4","refreshStatus":"BLOCKED","packetStatus":"BLOCKED_MANUAL_EVIDENCE","bootloaderVisibilityStatus":"READY_FOR_MANUAL_BOOTLOADER_CHECK","operatorChecklistStatus":"BLOCKED_EVIDENCE","installDecision":"BLOCKED","unlockGateStatus":"MISSING","stockRestoreGateStatus":"MISSING","gsiCandidateGateStatus":"MISSING","dsuPreflightGateStatus":"MISSING","fastbootGateStatus":"MISSING","destructiveApprovalStatus":"WITHHELD","romReady":false,"destructiveActions":"withheld","blockerCount":1,"blockers":["exact stock restore evidence is missing"],"blockersTruncated":false,"nextAction":"exact stock restore evidence is missing","staleReport":false,"checkedRefreshReport":true,"checkedOperatorChecklist":true}},"correlationId":"$messageId"}"""

    private fun goffyRomChecklistResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"goffy.rom.checklist","executionTarget":"MAC","structuredContent":{"status":"available","milestone":"ROM-0","generatedAt":"2026-07-22T15:00:01Z","checklistStatus":"BLOCKED_EVIDENCE","destructiveActions":"withheld","totalStepCount":3,"doneStepCount":1,"remainingStepCount":2,"nextSteps":[{"stepIndex":2,"title":"Record exact stock restore evidence","kind":"HUMAN_ONLY","status":"READY","summary":"Record the official Motorola restore archive name and checksum.","blocked":false,"blockerCount":0},{"stepIndex":3,"title":"Record read-only DSU preflight","kind":"LOCAL_READ_ONLY","status":"BLOCKED","summary":"Check DSU prerequisites from local evidence only.","blocked":true,"blockerCount":1}],"nextStepsTruncated":false,"blockerCount":1,"blockers":["exact stock restore evidence is missing"],"blockersTruncated":false,"nextStepTitle":"Record exact stock restore evidence","nextStepStatus":"READY","nextAction":"Complete Record exact stock restore evidence","checkedOperatorChecklist":true}},"correlationId":"$messageId"}"""

    private fun goffyRomFeaturesResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"goffy.rom.features","executionTarget":"MAC","structuredContent":{"status":"available","payloadName":"GOFFY ROM-0 Jarvis Payload","targetStage":"ROM-0","defaultPerformanceMode":"GOFFY LITE","rom0Flashable":false,"privileged":false,"platformSigned":false,"romDestructiveActionsIncluded":false,"appPrivateDestructiveToolsIncluded":false,"requiresUserSelectedHome":true,"localModelPolicy":"disabled_by_default_observe_only","featureCount":2,"features":[{"featureIndex":1,"title":"GOFFY Home Surface","executionTargets":["PHONE"],"mcpTools":["phone.device.info"],"mcpToolCount":1,"androidPermissionCount":0,"runtimePolicy":"user selected home with no privileged authority","foregroundOnly":true,"backgroundAccess":false,"privilegedRequired":false,"romDestructiveAction":false,"appPrivateDestructiveToolCount":0},{"featureIndex":2,"title":"GOFFY ROM Status","executionTargets":["MAC"],"mcpTools":["goffy.rom.status","goffy.rom.features"],"mcpToolCount":2,"androidPermissionCount":0,"runtimePolicy":"read only fixed validation artifacts","foregroundOnly":true,"backgroundAccess":false,"privilegedRequired":false,"romDestructiveAction":false,"appPrivateDestructiveToolCount":0}],"featuresTruncated":false,"mcpToolCount":3,"androidPermissionCount":0,"blockedRomActionCount":2,"blockedRomActions":["unlock_bootloader","flash_image"],"blockedRomActionsTruncated":false,"notes":["ROM-0 inserts GOFFY as a safe home payload."],"notesTruncated":false,"destructiveActions":"withheld","checkedFeaturePayload":true}},"correlationId":"$messageId"}"""

    private fun macFilesResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.files.list","executionTarget":"MAC","structuredContent":{"status":"available","rootIndex":0,"rootName":"goffy","relativePath":"","truncated":false,"approvedRoots":[{"rootIndex":0,"name":"goffy"}],"entries":[{"name":"README.md","nameTruncated":false,"kind":"file","sizeBytes":1024,"modifiedEpochSeconds":1784610000},{"name":"docs","nameTruncated":false,"kind":"directory","sizeBytes":null,"modifiedEpochSeconds":1784610001}]}},"correlationId":"$messageId"}"""

    private fun macFilesLargestResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.files.largest","executionTarget":"MAC","structuredContent":{"status":"available","rootIndex":0,"rootName":"goffy","relativePath":"","maxDepth":4,"scannedEntries":7,"skippedEntries":1,"truncated":false,"approvedRoots":[{"rootIndex":0,"name":"goffy"}],"entries":[{"relativePath":"build/output.apk","pathTruncated":false,"name":"output.apk","nameTruncated":false,"sizeBytes":12345678,"modifiedEpochSeconds":4102444800},{"relativePath":"README.md","pathTruncated":false,"name":"README.md","nameTruncated":false,"sizeBytes":1024,"modifiedEpochSeconds":1784610001}]}},"correlationId":"$messageId"}"""

    private fun macProcessesResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.processes.list","executionTarget":"MAC","structuredContent":{"status":"available","processCount":3,"skippedCount":0,"truncated":true,"entries":[{"pid":88,"name":"WindowServer","status":"running","rssBytes":512000000,"createTimeEpochSeconds":1784620000},{"pid":99,"name":"loginwindow","status":"sleeping","rssBytes":128000000,"createTimeEpochSeconds":null}]}},"correlationId":"$messageId"}"""

    private fun macAppsResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.apps.list","executionTarget":"MAC","structuredContent":{"status":"available","appCount":3,"truncated":true,"entries":[{"appIndex":0,"displayName":"Safari","bundleId":"com.apple.Safari"},{"appIndex":1,"displayName":"Terminal","bundleId":"com.apple.Terminal"}]}},"correlationId":"$messageId"}"""

    private fun macAppsOpenResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.apps.open","executionTarget":"MAC","structuredContent":{"status":"running","displayName":"Safari","bundleId":"com.apple.Safari","verified":true}},"correlationId":"$messageId"}"""

    private fun gitStatusResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"git.status","executionTarget":"MAC","structuredContent":{"status":"available","repoIndex":0,"repoName":"goffy","branch":"main","headOidShort":"0123456789abcdef","upstream":null,"ahead":null,"behind":null,"clean":false,"stagedCount":1,"unstagedCount":0,"untrackedCount":1,"conflictCount":0,"truncated":false,"approvedRepos":[{"repoIndex":0,"name":"goffy"}],"changes":[{"path":"README.md","pathTruncated":false,"indexStatus":"M","workingTreeStatus":".","kind":"tracked"},{"path":"TODO.md","pathTruncated":false,"indexStatus":"?","workingTreeStatus":"?","kind":"untracked"}]}},"correlationId":"$messageId"}"""

    private fun macClipboardResultEnvelope(): String =
        """{"protocolVersion":"0.2.0","messageId":"33333333-3333-4333-8333-333333333333","timestamp":"2026-07-13T16:00:01Z","deviceId":"goffy-hub","messageType":"ToolResult","payload":{"toolName":"mac.clipboard.read","executionTarget":"MAC","structuredContent":{"status":"available","contentType":"text","text":"copied text","textTruncated":false,"characterCount":11,"characterCountTruncated":false}},"correlationId":"$messageId"}"""

    private fun capabilityEnvelope(tool: String = capabilityTool()): String =
        """{"protocolVersion":"0.2.0","messageId":"99999999-9999-4999-8999-999999999999","timestamp":"2026-07-13T16:00:00Z","deviceId":"goffy-hub","messageType":"CapabilityDiscoveryResponse","payload":{"mcpProtocolVersion":"2025-11-25","listChanged":false,"tools":[$tool]},"correlationId":"$discoveryMessageId"}"""

    private fun capabilityTool(): String =
        """{"name":"mac.system_info","title":"Mac system information","description":"Read a minimal, non-sensitive snapshot of the Hub host.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{},"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"architecture":{"type":"string"},"operatingSystem":{"type":"string"},"status":{"type":"string"}},"required":["status","operatingSystem","architecture"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun goffyRomStatusCapabilityTool(): String =
        """{"name":"goffy.rom.status","title":"GOFFY ROM status","description":"Read the local GOFFY ROM-0 readiness packet summary without flashing, unlocking, rebooting, or exposing raw artifact paths.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{},"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"blockerCount":{"maximum":10000,"minimum":0,"type":"integer"},"blockers":{"items":{"maxLength":160,"minLength":1,"type":"string"},"maxItems":8,"type":"array"},"blockersTruncated":{"type":"boolean"},"bootloaderVisibilityStatus":{"maxLength":96,"minLength":1,"type":"string"},"checkedOperatorChecklist":{"type":"boolean"},"checkedRefreshReport":{"type":"boolean"},"destructiveActions":{"const":"withheld","type":"string"},"destructiveApprovalStatus":{"const":"WITHHELD","type":"string"},"dsuPreflightGateStatus":{"maxLength":96,"minLength":1,"type":"string"},"fastbootGateStatus":{"maxLength":96,"minLength":1,"type":"string"},"generatedAt":{"maxLength":64,"minLength":1,"type":"string"},"gsiCandidateGateStatus":{"maxLength":96,"minLength":1,"type":"string"},"installDecision":{"enum":["BLOCKED","READY_FOR_MANUAL_REVIEW"],"type":"string"},"milestone":{"const":"ROM-0","type":"string"},"nextAction":{"maxLength":192,"minLength":1,"type":"string"},"operatorChecklistStatus":{"maxLength":96,"minLength":1,"type":"string"},"packetStatus":{"maxLength":96,"minLength":1,"type":"string"},"refreshSchemaVersion":{"maxLength":64,"minLength":1,"type":"string"},"refreshStatus":{"maxLength":96,"minLength":1,"type":"string"},"romReady":{"type":"boolean"},"staleReport":{"type":"boolean"},"status":{"enum":["available","missing","invalid"],"type":"string"},"stockRestoreGateStatus":{"maxLength":96,"minLength":1,"type":"string"},"summary":{"maxLength":192,"minLength":1,"type":"string"},"unlockGateStatus":{"maxLength":96,"minLength":1,"type":"string"}},"required":["status","milestone","summary","generatedAt","refreshSchemaVersion","refreshStatus","packetStatus","bootloaderVisibilityStatus","operatorChecklistStatus","installDecision","unlockGateStatus","stockRestoreGateStatus","gsiCandidateGateStatus","dsuPreflightGateStatus","fastbootGateStatus","destructiveApprovalStatus","romReady","destructiveActions","blockerCount","blockers","blockersTruncated","nextAction","staleReport","checkedRefreshReport","checkedOperatorChecklist"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun goffyRomFeaturesCapabilityTool(): String =
        """{"name":"goffy.rom.features","title":"GOFFY ROM feature payload","description":"Read the bounded GOFFY ROM-0 feature payload without exposing source paths, commands, signing material, privileged authority, or flash/install controls.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{},"type":"object"},"outputSchema":{"${'$'}defs":{"GoffyRomFeatureOutput":{"additionalProperties":false,"properties":{"androidPermissionCount":{"maximum":100,"minimum":0,"type":"integer"},"appPrivateDestructiveToolCount":{"maximum":100,"minimum":0,"type":"integer"},"backgroundAccess":{"const":false,"type":"boolean"},"executionTargets":{"items":{"enum":["PHONE","MAC","CLOUD"],"type":"string"},"maxItems":3,"type":"array"},"featureIndex":{"maximum":100,"minimum":1,"type":"integer"},"foregroundOnly":{"const":true,"type":"boolean"},"mcpToolCount":{"maximum":100,"minimum":0,"type":"integer"},"mcpTools":{"items":{"maxLength":64,"minLength":1,"type":"string"},"maxItems":12,"type":"array"},"privilegedRequired":{"const":false,"type":"boolean"},"romDestructiveAction":{"const":false,"type":"boolean"},"runtimePolicy":{"maxLength":128,"minLength":1,"type":"string"},"title":{"maxLength":96,"minLength":1,"type":"string"}},"required":["featureIndex","title","executionTargets","mcpTools","mcpToolCount","androidPermissionCount","runtimePolicy","foregroundOnly","backgroundAccess","privilegedRequired","romDestructiveAction","appPrivateDestructiveToolCount"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"androidPermissionCount":{"maximum":100,"minimum":0,"type":"integer"},"appPrivateDestructiveToolsIncluded":{"type":"boolean"},"blockedRomActionCount":{"maximum":100,"minimum":0,"type":"integer"},"blockedRomActions":{"items":{"maxLength":64,"minLength":1,"type":"string"},"maxItems":12,"type":"array"},"blockedRomActionsTruncated":{"type":"boolean"},"checkedFeaturePayload":{"type":"boolean"},"defaultPerformanceMode":{"const":"GOFFY LITE","type":"string"},"destructiveActions":{"const":"withheld","type":"string"},"featureCount":{"maximum":100,"minimum":0,"type":"integer"},"features":{"items":{"${'$'}ref":"#/${'$'}defs/GoffyRomFeatureOutput"},"maxItems":8,"type":"array"},"featuresTruncated":{"type":"boolean"},"localModelPolicy":{"const":"disabled_by_default_observe_only","type":"string"},"mcpToolCount":{"maximum":100,"minimum":0,"type":"integer"},"notes":{"items":{"maxLength":160,"minLength":1,"type":"string"},"maxItems":4,"type":"array"},"notesTruncated":{"type":"boolean"},"payloadName":{"maxLength":96,"minLength":1,"type":"string"},"platformSigned":{"const":false,"type":"boolean"},"privileged":{"const":false,"type":"boolean"},"requiresUserSelectedHome":{"const":true,"type":"boolean"},"rom0Flashable":{"const":false,"type":"boolean"},"romDestructiveActionsIncluded":{"const":false,"type":"boolean"},"status":{"enum":["available","missing","invalid"],"type":"string"},"targetStage":{"const":"ROM-0","type":"string"}},"required":["status","payloadName","targetStage","defaultPerformanceMode","rom0Flashable","privileged","platformSigned","romDestructiveActionsIncluded","appPrivateDestructiveToolsIncluded","requiresUserSelectedHome","localModelPolicy","featureCount","features","featuresTruncated","mcpToolCount","androidPermissionCount","blockedRomActionCount","blockedRomActions","blockedRomActionsTruncated","notes","notesTruncated","destructiveActions","checkedFeaturePayload"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun goffyRomChecklistCapabilityTool(): String =
        """
        {
          "name": "goffy.rom.checklist",
          "title": "GOFFY ROM operator checklist",
          "description": "Read the bounded GOFFY ROM-0 operator checklist without exposing raw artifact paths or command strings, and without granting unlock, reboot, flash, erase, wipe, boot, or shell authority.",
          "inputSchema": {
            "${'$'}schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": false,
            "properties": {},
            "type": "object"
          },
          "outputSchema": {
            "${'$'}defs": {
              "GoffyRomChecklistStepOutput": {
                "additionalProperties": false,
                "properties": {
                  "blocked": {"type": "boolean"},
                  "blockerCount": {"maximum": 100, "minimum": 0, "type": "integer"},
                  "kind": {
                    "enum": ["LOCAL_READ_ONLY", "HUMAN_ONLY", "TEMPLATE_ONLY", "HUMAN_DECISION"],
                    "type": "string"
                  },
                  "status": {"enum": ["DONE", "READY", "BLOCKED"], "type": "string"},
                  "stepIndex": {"maximum": 100, "minimum": 1, "type": "integer"},
                  "summary": {"maxLength": 192, "minLength": 1, "type": "string"},
                  "title": {"maxLength": 96, "minLength": 1, "type": "string"}
                },
                "required": [
                  "stepIndex",
                  "title",
                  "kind",
                  "status",
                  "summary",
                  "blocked",
                  "blockerCount"
                ],
                "type": "object"
              }
            },
            "${'$'}schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": false,
            "properties": {
              "blockerCount": {"maximum": 10000, "minimum": 0, "type": "integer"},
              "blockers": {
                "items": {"maxLength": 160, "minLength": 1, "type": "string"},
                "maxItems": 8,
                "type": "array"
              },
              "blockersTruncated": {"type": "boolean"},
              "checkedOperatorChecklist": {"type": "boolean"},
              "checklistStatus": {
                "enum": ["BLOCKED_EVIDENCE", "READY_FOR_ROM0_READINESS_REVIEW", "MISSING", "INVALID"],
                "type": "string"
              },
              "destructiveActions": {"const": "withheld", "type": "string"},
              "doneStepCount": {"maximum": 100, "minimum": 0, "type": "integer"},
              "generatedAt": {"maxLength": 64, "minLength": 1, "type": "string"},
              "milestone": {"const": "ROM-0", "type": "string"},
              "nextAction": {"maxLength": 192, "minLength": 1, "type": "string"},
              "nextStepStatus": {
                "enum": ["DONE", "READY", "BLOCKED", "MISSING", "INVALID"],
                "type": "string"
              },
              "nextStepTitle": {"maxLength": 96, "minLength": 1, "type": "string"},
              "nextSteps": {
                "items": {"${'$'}ref": "#/${'$'}defs/GoffyRomChecklistStepOutput"},
                "maxItems": 6,
                "type": "array"
              },
              "nextStepsTruncated": {"type": "boolean"},
              "remainingStepCount": {"maximum": 100, "minimum": 0, "type": "integer"},
              "status": {"enum": ["available", "missing", "invalid"], "type": "string"},
              "totalStepCount": {"maximum": 100, "minimum": 0, "type": "integer"}
            },
            "required": [
              "status",
              "milestone",
              "generatedAt",
              "checklistStatus",
              "destructiveActions",
              "totalStepCount",
              "doneStepCount",
              "remainingStepCount",
              "nextSteps",
              "nextStepsTruncated",
              "blockerCount",
              "blockers",
              "blockersTruncated",
              "nextStepTitle",
              "nextStepStatus",
              "nextAction",
              "checkedOperatorChecklist"
            ],
            "type": "object"
          },
          "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false,
            "idempotentHint": true,
            "openWorldHint": false
          },
          "_meta": {
            "dev.goffy/toolVersion": "1.0.0",
            "dev.goffy/executionTarget": "MAC",
            "dev.goffy/permission": "SAFE",
            "dev.goffy/timeoutMs": 3000
          }
        }
        """.trimIndent()

    private fun macFilesCapabilityTool(): String =
        """{"name":"mac.files.list","title":"Mac approved-root file listing","description":"List entries inside explicitly approved Mac directories without following symlink targets or exposing absolute root paths.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"includeHidden":{"default":false,"type":"boolean"},"maxEntries":{"default":25,"maximum":32,"minimum":1,"type":"integer"},"relativePath":{"default":"","maxLength":512,"type":"string"},"rootIndex":{"default":0,"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"MacFilesApprovedRootOutput":{"additionalProperties":false,"properties":{"name":{"type":"string"},"rootIndex":{"type":"integer"}},"required":["rootIndex","name"],"type":"object"},"MacFilesListEntryOutput":{"additionalProperties":false,"properties":{"kind":{"enum":["file","directory","symlink","other"],"type":"string"},"modifiedEpochSeconds":{"anyOf":[{"type":"integer"},{"type":"null"}]},"name":{"type":"string"},"nameTruncated":{"type":"boolean"},"sizeBytes":{"anyOf":[{"type":"integer"},{"type":"null"}]}},"required":["name","nameTruncated","kind","sizeBytes","modifiedEpochSeconds"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"approvedRoots":{"items":{"${'$'}ref":"#/${'$'}defs/MacFilesApprovedRootOutput"},"maxItems":8,"type":"array"},"entries":{"items":{"${'$'}ref":"#/${'$'}defs/MacFilesListEntryOutput"},"maxItems":32,"type":"array"},"relativePath":{"type":"string"},"rootIndex":{"type":"integer"},"rootName":{"type":"string"},"status":{"type":"string"},"truncated":{"type":"boolean"}},"required":["status","rootIndex","rootName","relativePath","truncated","approvedRoots","entries"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun macFilesLargestCapabilityTool(): String =
        """{"name":"mac.files.largest","title":"Mac largest approved-root files","description":"Find the largest regular files under an explicitly approved Mac directory with bounded traversal, no file-content reads, and no symlink following.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"includeHidden":{"default":false,"type":"boolean"},"maxDepth":{"default":4,"maximum":8,"minimum":0,"type":"integer"},"maxEntries":{"default":10,"maximum":25,"minimum":1,"type":"integer"},"relativePath":{"default":"","maxLength":512,"type":"string"},"rootIndex":{"default":0,"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"MacFilesApprovedRootOutput":{"additionalProperties":false,"properties":{"name":{"type":"string"},"rootIndex":{"type":"integer"}},"required":["rootIndex","name"],"type":"object"},"MacFilesLargestEntryOutput":{"additionalProperties":false,"properties":{"modifiedEpochSeconds":{"anyOf":[{"type":"integer"},{"type":"null"}]},"name":{"type":"string"},"nameTruncated":{"type":"boolean"},"pathTruncated":{"type":"boolean"},"relativePath":{"type":"string"},"sizeBytes":{"minimum":0,"type":"integer"}},"required":["relativePath","pathTruncated","name","nameTruncated","sizeBytes","modifiedEpochSeconds"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"approvedRoots":{"items":{"${'$'}ref":"#/${'$'}defs/MacFilesApprovedRootOutput"},"maxItems":8,"type":"array"},"entries":{"items":{"${'$'}ref":"#/${'$'}defs/MacFilesLargestEntryOutput"},"maxItems":25,"type":"array"},"maxDepth":{"type":"integer"},"relativePath":{"type":"string"},"rootIndex":{"type":"integer"},"rootName":{"type":"string"},"scannedEntries":{"minimum":0,"type":"integer"},"skippedEntries":{"minimum":0,"type":"integer"},"status":{"type":"string"},"truncated":{"type":"boolean"}},"required":["status","rootIndex","rootName","relativePath","maxDepth","scannedEntries","skippedEntries","truncated","approvedRoots","entries"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun macProcessesCapabilityTool(): String =
        """{"name":"mac.processes.list","title":"Mac running process summary","description":"List bounded read-only metadata for running Mac processes without exposing command lines, executable paths, environment variables, open files, or network data.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"maxEntries":{"default":10,"maximum":25,"minimum":1,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"MacProcessEntryOutput":{"additionalProperties":false,"properties":{"createTimeEpochSeconds":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null},"name":{"maxLength":96,"minLength":1,"type":"string"},"pid":{"maximum":2147483647,"minimum":0,"type":"integer"},"rssBytes":{"maximum":9223372036854775807,"minimum":0,"type":"integer"},"status":{"maxLength":32,"minLength":1,"type":"string"}},"required":["pid","name","status","rssBytes"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"entries":{"items":{"${'$'}ref":"#/${'$'}defs/MacProcessEntryOutput"},"maxItems":25,"type":"array"},"processCount":{"maximum":100000,"minimum":0,"type":"integer"},"skippedCount":{"maximum":100000,"minimum":0,"type":"integer"},"status":{"maxLength":64,"minLength":1,"type":"string"},"truncated":{"type":"boolean"}},"required":["status","processCount","skippedCount","truncated","entries"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun macAppsCapabilityTool(): String =
        """{"name":"mac.apps.list","title":"Mac approved app catalog","description":"List explicitly approved Mac applications by display name and bundle identifier without launching apps, reading installed app folders, or exposing file paths.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"maxEntries":{"default":10,"maximum":25,"minimum":1,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"MacAppCatalogEntryOutput":{"additionalProperties":false,"properties":{"appIndex":{"exclusiveMaximum":25,"minimum":0,"type":"integer"},"bundleId":{"maxLength":160,"minLength":1,"type":"string"},"displayName":{"maxLength":80,"minLength":1,"type":"string"}},"required":["appIndex","displayName","bundleId"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"appCount":{"maximum":25,"minimum":0,"type":"integer"},"entries":{"items":{"${'$'}ref":"#/${'$'}defs/MacAppCatalogEntryOutput"},"maxItems":25,"type":"array"},"status":{"maxLength":64,"minLength":1,"type":"string"},"truncated":{"type":"boolean"}},"required":["status","appCount","truncated","entries"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun macAppsOpenCapabilityTool(): String =
        """{"name":"mac.apps.open","title":"Open approved Mac app","description":"Open one explicitly approved Mac application by display name using its fixed bundle identifier. The tool cannot open files, scan installed app folders, or run shell commands.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"displayName":{"maxLength":80,"minLength":1,"type":"string"}},"required":["displayName"],"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"bundleId":{"maxLength":160,"minLength":1,"type":"string"},"displayName":{"maxLength":80,"minLength":1,"type":"string"},"status":{"maxLength":64,"minLength":1,"type":"string"},"verified":{"type":"boolean"}},"required":["status","displayName","bundleId","verified"],"type":"object"},"annotations":{"readOnlyHint":false,"destructiveHint":false,"idempotentHint":false,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"CONFIRM","dev.goffy/timeoutMs":3000}}"""

    private fun gitStatusCapabilityTool(): String =
        """{"name":"git.status","title":"Approved Git repository status","description":"Read bounded status metadata for explicitly approved local Git repositories without running arbitrary commands or exposing repository root paths.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"includeUntracked":{"default":true,"type":"boolean"},"maxChanges":{"default":25,"maximum":32,"minimum":1,"type":"integer"},"repoIndex":{"default":0,"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}defs":{"GitStatusApprovedRepoOutput":{"additionalProperties":false,"properties":{"name":{"maxLength":64,"minLength":1,"type":"string"},"repoIndex":{"exclusiveMaximum":8,"minimum":0,"type":"integer"}},"required":["repoIndex","name"],"type":"object"},"GitStatusChangeOutput":{"additionalProperties":false,"properties":{"indexStatus":{"maxLength":1,"minLength":1,"type":"string"},"kind":{"enum":["tracked","untracked","conflict"],"type":"string"},"path":{"maxLength":160,"minLength":1,"type":"string"},"pathTruncated":{"type":"boolean"},"workingTreeStatus":{"maxLength":1,"minLength":1,"type":"string"}},"required":["path","pathTruncated","indexStatus","workingTreeStatus","kind"],"type":"object"}},"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"ahead":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null},"approvedRepos":{"items":{"${'$'}ref":"#/${'$'}defs/GitStatusApprovedRepoOutput"},"maxItems":8,"type":"array"},"behind":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null},"branch":{"anyOf":[{"maxLength":96,"type":"string"},{"type":"null"}],"default":null},"changes":{"items":{"${'$'}ref":"#/${'$'}defs/GitStatusChangeOutput"},"maxItems":32,"type":"array"},"clean":{"type":"boolean"},"conflictCount":{"minimum":0,"type":"integer"},"headOidShort":{"anyOf":[{"maxLength":16,"type":"string"},{"type":"null"}],"default":null},"repoIndex":{"exclusiveMaximum":8,"minimum":0,"type":"integer"},"repoName":{"maxLength":64,"minLength":1,"type":"string"},"stagedCount":{"minimum":0,"type":"integer"},"status":{"maxLength":64,"minLength":1,"type":"string"},"truncated":{"type":"boolean"},"unstagedCount":{"minimum":0,"type":"integer"},"untrackedCount":{"minimum":0,"type":"integer"},"upstream":{"anyOf":[{"maxLength":128,"type":"string"},{"type":"null"}],"default":null}},"required":["status","repoIndex","repoName","clean","stagedCount","unstagedCount","untrackedCount","conflictCount","truncated","approvedRepos","changes"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""

    private fun macClipboardCapabilityTool(): String =
        """{"name":"mac.clipboard.read","title":"Mac clipboard text read","description":"Read bounded plaintext from the active Mac clipboard when this opt-in tool is enabled.","inputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"maxChars":{"default":1000,"maximum":2000,"minimum":1,"type":"integer"}},"type":"object"},"outputSchema":{"${'$'}schema":"https://json-schema.org/draft/2020-12/schema","additionalProperties":false,"properties":{"characterCount":{"maximum":100000,"minimum":0,"type":"integer"},"characterCountTruncated":{"type":"boolean"},"contentType":{"const":"text","default":"text","type":"string"},"status":{"enum":["available","empty","unsupported"],"type":"string"},"text":{"anyOf":[{"maxLength":2000,"type":"string"},{"type":"null"}],"default":null},"textTruncated":{"type":"boolean"}},"required":["status","textTruncated","characterCount","characterCountTruncated"],"type":"object"},"annotations":{"readOnlyHint":true,"destructiveHint":false,"idempotentHint":true,"openWorldHint":false},"_meta":{"dev.goffy/toolVersion":"1.0.0","dev.goffy/executionTarget":"MAC","dev.goffy/permission":"SAFE","dev.goffy/timeoutMs":3000}}"""
}
