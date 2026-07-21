package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.audit.AuditApprovalOutcome
import dev.goffy.os.audit.AuditPermission
import dev.goffy.os.audit.AuditSourceSurface
import dev.goffy.os.audit.ClosedTerminalAuditLoadResult
import dev.goffy.os.audit.ClosedTerminalAuditRecord
import dev.goffy.os.audit.TerminalAuditPhase
import dev.goffy.os.audit.TerminalAuditStore
import dev.goffy.os.hub.HubConfig
import dev.goffy.os.hub.HubCredentialLoadResult
import dev.goffy.os.hub.HubCredentialStore
import dev.goffy.os.hub.HubEndpoint
import dev.goffy.os.hub.HubGateway
import dev.goffy.os.hub.HubIdentityPin
import dev.goffy.os.hub.HubOperatorAuditEvent
import dev.goffy.os.hub.HubOperatorAuditException
import dev.goffy.os.hub.HubOperatorAuditGateway
import dev.goffy.os.hub.HubOperatorAuditSnapshot
import dev.goffy.os.hub.HubPairingException
import dev.goffy.os.hub.HubPairingGateway
import dev.goffy.os.hub.IssuedHubCredential
import dev.goffy.os.hub.RotatedHubCredential
import dev.goffy.os.hub.SelfRevocationResult
import dev.goffy.os.hub.StoredHubCredential
import dev.goffy.os.hub.DEFAULT_HUB_OPERATOR_AUDIT_LIMIT
import dev.goffy.os.localmodel.LocalModelIntentCandidate
import dev.goffy.os.localmodel.LocalModelIntentFallback
import dev.goffy.os.localmodel.LocalModelIntentObservation
import dev.goffy.os.localmodel.LocalModelRuntimeGate
import dev.goffy.os.localmodel.LocalModelRuntimeGateConfig
import dev.goffy.os.localmodel.LocalModelRuntimePolicy
import dev.goffy.os.localmodel.LocalModelRuntimeProvider
import dev.goffy.os.localmodel.LocalModelRuntimeSettings
import dev.goffy.os.localmodel.LocalModelRuntimeSettingsLoadResult
import dev.goffy.os.localmodel.LocalModelRuntimeSettingsSaveResult
import dev.goffy.os.localmodel.LocalModelRuntimeSettingsStore
import dev.goffy.os.localmodel.LocalModelRuntimeState
import dev.goffy.os.localmodel.LocalModelRuntimeStatus
import dev.goffy.os.localmodel.MutableLocalModelRuntimeSettingsSource
import dev.goffy.os.phone.DefaultPhoneToolGateway
import dev.goffy.os.phone.FlashlightSource
import dev.goffy.os.phone.PhoneToolGateway
import dev.goffy.os.phone.NoteStore
import dev.goffy.os.phone.TimerSource
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.GitStatusApprovedRepo
import dev.goffy.os.protocol.GitStatusChange
import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.MacClipboardRead
import dev.goffy.os.protocol.MacFilesApprovedRoot
import dev.goffy.os.protocol.MacFilesList
import dev.goffy.os.protocol.MacFilesListEntry
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.GOFFY_PROTOCOL_VERSION
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.ANDROID_SET_TIMER_ACTION
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.ToolInvocationRequest
import dev.goffy.os.protocol.ToolProgress
import java.io.File
import java.nio.file.Files
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class GoffyViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val endpoint = "ws://127.0.0.1:8787/ws/v1"
    private val token = "test-token-that-is-long-enough"
    private val hubFingerprint =
        "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun verifiedMacStatusFlowIsVisibleOnlyAfterVerification() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf(*successfulEvents().toTypedArray()) }
        val viewModel = createViewModel(gateway)

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.submitCommand("Show my Mac status")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals("Darwin", (entry.result as MacSystemInfo).operatingSystem)
        assertEquals(listOf("output schema"), entry.verificationChecks)
        assertNull(viewModel.uiState.value.timeline.activeTaskId)
        assertEquals(1, gateway.requests.size)
        assertFalse(viewModel.uiState.value.toString().contains(token))
    }

    @Test
    fun macFilesCommandSendsTypedDefaultListingArguments() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf(*successfulMacFilesEvents().toTypedArray()) }
        val viewModel = createViewModel(gateway)

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.submitCommand("List my Mac files")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals("goffy", (entry.result as MacFilesList).rootName)
        assertEquals(1, gateway.requests.size)
        assertTrue(gateway.requests.single().encodedMessage.contains("\"toolName\":\"mac.files.list\""))
        assertTrue(gateway.requests.single().encodedMessage.contains("\"rootIndex\":0"))
        assertTrue(gateway.requests.single().encodedMessage.contains("\"maxEntries\":25"))
        assertFalse(gateway.requests.single().encodedMessage.contains("private-plan"))
    }

    @Test
    fun gitStatusCommandSendsTypedDefaultRepoArguments() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf(*successfulGitStatusEvents().toTypedArray()) }
        val viewModel = createViewModel(gateway)

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.submitCommand("Show my git status")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals("goffy", (entry.result as GitStatus).repoName)
        assertEquals(1, gateway.requests.size)
        assertTrue(gateway.requests.single().encodedMessage.contains("\"toolName\":\"git.status\""))
        assertTrue(gateway.requests.single().encodedMessage.contains("\"repoIndex\":0"))
        assertTrue(gateway.requests.single().encodedMessage.contains("\"maxChanges\":25"))
        assertFalse(gateway.requests.single().encodedMessage.contains("private-plan"))
    }

    @Test
    fun macClipboardCommandSendsSafeNoArgumentMacInvocation() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf(*successfulMacClipboardEvents().toTypedArray()) }
        val viewModel = createViewModel(gateway)

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.submitCommand("Read my Mac clipboard")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals("copied text", (entry.result as MacClipboardRead).text)
        assertEquals(1, gateway.requests.size)
        assertTrue(gateway.requests.single().encodedMessage.contains("\"toolName\":\"mac.clipboard.read\""))
        assertTrue(gateway.requests.single().encodedMessage.contains("\"arguments\":{}"))
        assertFalse(gateway.requests.single().encodedMessage.contains("copied text"))
    }

    @Test
    fun restoredPairedCredentialReactivatesMacFlowWithoutExposingBearer() = runTest(dispatcher) {
        val stored = storedCredential()
        val credentialStore = RecordingCredentialStore(HubCredentialLoadResult.Loaded(stored))
        val gateway = FakeHubGateway { flowOf(*successfulEvents().toTypedArray()) }
        val viewModel = createViewModel(gateway, credentialStore = credentialStore)

        advanceUntilIdle()
        viewModel.submitCommand("Show my Mac status")
        advanceUntilIdle()

        assertEquals(HubLinkState.PAIRED, viewModel.uiState.value.hubLinkState)
        assertEquals(hubFingerprint, viewModel.uiState.value.hubIdentityFingerprint)
        assertEquals(TaskPhase.VERIFIED, viewModel.uiState.value.timeline.entries.single().phase)
        assertEquals(1, gateway.requests.size)
        assertFalse(viewModel.uiState.value.toString().contains(token))
    }

    @Test
    fun pairedHubAuditRefreshShowsOnlyBoundedSelfAuditState() = runTest(dispatcher) {
        val auditGateway = RecordingHubOperatorAuditGateway()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            credentialStore = RecordingCredentialStore(HubCredentialLoadResult.Loaded(storedCredential())),
            operatorAuditGateway = auditGateway,
            nowMillis = { 1_720_000_000_000 },
        )
        advanceUntilIdle()

        viewModel.refreshHubOperatorAudit()
        advanceUntilIdle()

        val audit = viewModel.uiState.value.hubOperatorAudit
        assertEquals(HubOperatorAuditState.READY, audit.state)
        assertEquals("sqlite", audit.storageKind)
        assertEquals("verified", audit.integrity)
        assertEquals(1_720_000_000_000, audit.refreshedAtEpochMillis)
        assertEquals(1, audit.events.size)
        assertEquals("mcp", audit.events.single().source)
        assertEquals("http.get", audit.events.single().action)
        assertEquals(1, auditGateway.calls)
        assertEquals(DEFAULT_HUB_OPERATOR_AUDIT_LIMIT, auditGateway.limits.single())
        assertEquals(endpoint, auditGateway.configs.single().endpoint)
        assertFalse(viewModel.uiState.value.toString().contains(token))
    }

    @Test
    fun hubAuditRefreshRequiresAPairedCredential() = runTest(dispatcher) {
        val auditGateway = RecordingHubOperatorAuditGateway()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            operatorAuditGateway = auditGateway,
        )
        advanceUntilIdle()

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.refreshHubOperatorAudit()
        advanceUntilIdle()

        assertEquals(0, auditGateway.calls)
        assertEquals(HubOperatorAuditState.DEGRADED, viewModel.uiState.value.hubOperatorAudit.state)
        assertTrue(viewModel.uiState.value.hubOperatorAudit.message.orEmpty().contains("paired"))
        assertFalse(viewModel.uiState.value.toString().contains(token))
    }

    @Test
    fun hubAuditRefreshFailureIsVisibleWithoutChangingMacLinkState() = runTest(dispatcher) {
        val auditGateway = RecordingHubOperatorAuditGateway(
            failure = HubOperatorAuditException(
                "audit_forbidden",
                "The Hub refused paired audit retrieval.",
            ),
        )
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            credentialStore = RecordingCredentialStore(HubCredentialLoadResult.Loaded(storedCredential())),
            operatorAuditGateway = auditGateway,
        )
        advanceUntilIdle()

        viewModel.refreshHubOperatorAudit()
        advanceUntilIdle()

        assertEquals(1, auditGateway.calls)
        assertEquals(HubLinkState.PAIRED, viewModel.uiState.value.hubLinkState)
        assertEquals(HubOperatorAuditState.DEGRADED, viewModel.uiState.value.hubOperatorAudit.state)
        assertTrue(viewModel.uiState.value.hubOperatorAudit.message.orEmpty().contains("refused"))
        assertFalse(viewModel.uiState.value.toString().contains(token))
    }

    @Test
    fun pairingActivatesOnlyAfterCredentialPersistenceIsVerified() = runTest(dispatcher) {
        val pairingGateway = RecordingPairingGateway()
        val credentialStore = RecordingCredentialStore()
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        viewModel.pairHub(endpoint, "secret challenge payload")
        advanceUntilIdle()

        assertEquals(HubLinkState.PAIRED, viewModel.uiState.value.hubLinkState)
        assertEquals(endpoint, viewModel.uiState.value.hubEndpoint)
        assertEquals(hubFingerprint, viewModel.uiState.value.hubIdentityFingerprint)
        assertEquals(1, pairingGateway.calls)
        assertEquals(1, credentialStore.saves)
        assertFalse(viewModel.uiState.value.toString().contains(token))
        assertFalse(viewModel.uiState.value.toString().contains("secret challenge payload"))
    }

    @Test
    fun persistenceFailureLeavesPairingDisabledAndVisible() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(failSaves = true)
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = RecordingPairingGateway(),
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        viewModel.pairHub(endpoint, "secret challenge payload")
        advanceUntilIdle()

        assertEquals(HubLinkState.DEGRADED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("not activated"))
        assertFalse(viewModel.uiState.value.toString().contains(token))
    }

    @Test
    fun leavingForegroundCancelsPairingAndClearsAnyPartialLocalAuthority() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore()
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = BlockingPairingGateway(),
            credentialStore = credentialStore,
        )
        advanceUntilIdle()
        viewModel.pairHub(endpoint, "secret challenge payload")
        runCurrent()

        viewModel.cancelForegroundPairing()
        advanceUntilIdle()

        assertEquals(HubLinkState.UNPAIRED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertEquals(1, credentialStore.clears)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("left the foreground"))
    }

    @Test
    fun forgetRemovesPersistedAuthorityAndCancelsActiveMacTask() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(
            HubCredentialLoadResult.Loaded(storedCredential()),
        )
        val pairingGateway = RecordingPairingGateway()
        val gateway = FakeHubGateway {
            flow {
                emit(ExecutionEvent.Starting(1))
                awaitCancellation()
            }
        }
        val viewModel = createViewModel(
            gateway,
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()
        viewModel.submitCommand("Show my Mac status")
        runCurrent()

        viewModel.forgetHub()
        advanceUntilIdle()

        assertEquals(1, credentialStore.clears)
        assertEquals(1, pairingGateway.revocationCalls)
        assertEquals(storedCredential().credentialId, pairingGateway.revokedCredentialIds.single())
        assertEquals(HubLinkState.UNPAIRED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertEquals(false, viewModel.uiState.value.linkNotice?.warning)
        assertTrue(viewModel.uiState.value.linkNotice?.message.orEmpty().contains("verified"))
        assertEquals(TaskPhase.CANCELLED, viewModel.uiState.value.timeline.entries.single().phase)
    }

    @Test
    fun forgetRemovesLocalAuthorityWhenHubSelfRevocationIsUnverified() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(
            HubCredentialLoadResult.Loaded(storedCredential()),
        )
        val pairingGateway = RecordingPairingGateway(failRevocation = true)
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        viewModel.forgetHub()
        advanceUntilIdle()

        assertEquals(1, credentialStore.clears)
        assertEquals(1, pairingGateway.revocationCalls)
        assertEquals(HubLinkState.UNPAIRED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertEquals(true, viewModel.uiState.value.linkNotice?.warning)
        assertTrue(viewModel.uiState.value.linkNotice?.message.orEmpty().contains("not verified"))
    }

    @Test
    fun forgetReportsDegradedWhenLocalCredentialClearCannotBeVerified() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(
            initial = HubCredentialLoadResult.Loaded(storedCredential()),
            failClears = true,
        )
        val pairingGateway = RecordingPairingGateway()
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        viewModel.forgetHub()
        advanceUntilIdle()

        assertEquals(1, credentialStore.clears)
        assertEquals(1, pairingGateway.revocationCalls)
        assertEquals(HubLinkState.DEGRADED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("local credential deletion"))
        assertNull(viewModel.uiState.value.linkNotice)
    }

    @Test
    fun forgetDevelopmentLinkDoesNotAttemptPairedSelfRevocation() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore()
        val pairingGateway = RecordingPairingGateway()
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.forgetHub()
        advanceUntilIdle()

        assertEquals(1, credentialStore.clears)
        assertEquals(0, pairingGateway.revocationCalls)
        assertEquals(HubLinkState.UNPAIRED, viewModel.uiState.value.hubLinkState)
        assertEquals(false, viewModel.uiState.value.linkNotice?.warning)
        assertTrue(viewModel.uiState.value.linkNotice?.message.orEmpty().contains("Debug"))
    }

    @Test
    fun rotationCancelsActiveWorkAndPersistsTheNewBearer() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(
            HubCredentialLoadResult.Loaded(storedCredential()),
        )
        val pairingGateway = RecordingPairingGateway()
        val gateway = FakeHubGateway {
            flow {
                emit(ExecutionEvent.Starting(1))
                awaitCancellation()
            }
        }
        val viewModel = createViewModel(
            gateway,
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()
        viewModel.submitCommand("Show my Mac status")
        runCurrent()

        viewModel.rotateHubCredential()
        advanceUntilIdle()

        assertEquals(1, pairingGateway.rotationCalls)
        assertEquals(storedCredential().credentialId, pairingGateway.rotatedCredentialIds.single())
        assertEquals(1, credentialStore.saves)
        assertEquals(
            storedCredential().credentialId,
            credentialStore.savedCredentials.single().credentialId,
        )
        assertEquals("goffy-android-test", credentialStore.savedCredentials.single().deviceId)
        assertEquals(
            "rotated-token-that-is-long-enough-xx",
            credentialStore.savedCredentials.single().accessToken,
        )
        assertEquals(
            storedCredential().createdAt,
            credentialStore.savedCredentials.single().createdAt,
        )
        assertEquals(
            hubFingerprint,
            credentialStore.savedCredentials.single().hubIdentity.fingerprint,
        )
        assertEquals(HubLinkState.PAIRED, viewModel.uiState.value.hubLinkState)
        assertEquals(hubFingerprint, viewModel.uiState.value.hubIdentityFingerprint)
        assertTrue(viewModel.uiState.value.linkNotice?.message.orEmpty().contains("rotated"))
        assertEquals(TaskPhase.CANCELLED, viewModel.uiState.value.timeline.entries.single().phase)
        assertFalse(viewModel.uiState.value.toString().contains("rotated-token"))
    }

    @Test
    fun rotationFailureDisablesMacAccessAndClearsLocalAuthority() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(
            HubCredentialLoadResult.Loaded(storedCredential()),
        )
        val pairingGateway = RecordingPairingGateway(failRotation = true)
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        viewModel.rotateHubCredential()
        advanceUntilIdle()

        assertEquals(1, pairingGateway.rotationCalls)
        assertEquals(0, credentialStore.saves)
        assertEquals(1, credentialStore.clears)
        assertEquals(HubLinkState.DEGRADED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("disabled"))
    }

    @Test
    fun rotationPersistenceFailureDisablesMacAccessAndClearsLocalAuthority() = runTest(dispatcher) {
        val credentialStore = RecordingCredentialStore(
            initial = HubCredentialLoadResult.Loaded(storedCredential()),
            failSaves = true,
        )
        val pairingGateway = RecordingPairingGateway()
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        viewModel.rotateHubCredential()
        advanceUntilIdle()

        assertEquals(1, pairingGateway.rotationCalls)
        assertEquals(1, credentialStore.saves)
        assertEquals(1, credentialStore.clears)
        assertEquals(HubLinkState.DEGRADED, viewModel.uiState.value.hubLinkState)
        assertFalse(viewModel.uiState.value.hubConfigured)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("pair again"))
    }

    @Test
    fun rotationIsUnavailableForDevelopmentBearerLinks() = runTest(dispatcher) {
        val pairingGateway = RecordingPairingGateway()
        val credentialStore = RecordingCredentialStore()
        val viewModel = createViewModel(
            FakeHubGateway { flowOf() },
            pairingGateway = pairingGateway,
            credentialStore = credentialStore,
        )
        advanceUntilIdle()

        assertTrue(viewModel.configureHub(endpoint, token))
        viewModel.rotateHubCredential()
        advanceUntilIdle()

        assertEquals(0, pairingGateway.rotationCalls)
        assertEquals(0, credentialStore.saves)
        assertEquals(HubLinkState.DEVELOPMENT, viewModel.uiState.value.hubLinkState)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("paired"))
    }

    @Test
    fun corruptCredentialRestoreFailsClosedWithoutDevelopmentFallback() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val viewModel = createViewModel(
            gateway,
            credentialStore = RecordingCredentialStore(HubCredentialLoadResult.Corrupt),
        )

        advanceUntilIdle()
        viewModel.submitCommand("Show my Mac status")
        advanceUntilIdle()

        assertEquals(HubLinkState.DEGRADED, viewModel.uiState.value.hubLinkState)
        assertTrue(gateway.requests.isEmpty())
        assertEquals(TaskPhase.FAILED, viewModel.uiState.value.timeline.entries.single().phase)
    }

    @Test
    fun releasePolicyRejectsManualBearerConfiguration() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val viewModel = createViewModel(
            gateway,
            allowDevelopmentTokenConfiguration = false,
        )
        advanceUntilIdle()

        assertFalse(viewModel.configureHub("wss://hub.example/ws/v1", token))
        viewModel.submitCommand("Show my Mac status")
        advanceUntilIdle()

        assertTrue(gateway.requests.isEmpty())
        assertFalse(viewModel.uiState.value.developmentTokenAllowed)
        assertTrue(viewModel.uiState.value.linkError.orEmpty().contains("debug builds"))
    }

    @Test
    fun unsupportedCommandNeverInvokesTheHub() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val viewModel = createViewModel(gateway)

        viewModel.configureHub(endpoint, token)
        viewModel.submitCommand("Delete every file on my Mac")
        advanceUntilIdle()

        assertTrue(gateway.requests.isEmpty())
        assertEquals(TaskPhase.FAILED, viewModel.uiState.value.timeline.entries.single().phase)
    }

    @Test
    fun localModelObservationDoesNotBecomeExecutableRoute() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val fallback = RecordingLocalModelFallback(
            LocalModelIntentObservation.Candidate(
                LocalModelIntentCandidate(
                    intentLabel = "PHONE",
                    confidence = 0.91f,
                    normalizedCommand = "open settings",
                    rationale = "test observation",
                ),
            ),
        )
        val viewModel = createViewModel(
            gateway,
            localModelFallback = fallback,
            localModelStatus = LocalModelRuntimeStatus(
                state = LocalModelRuntimeState.READY,
                summary = "Local model ready for observe-only fallback.",
                enabledByUser = true,
                runtimeAvailable = true,
                modelAvailable = true,
            ),
        )

        viewModel.configureHub(endpoint, token)
        viewModel.submitCommand("open settings")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(1, fallback.calls)
        assertTrue(gateway.requests.isEmpty())
        assertEquals(TaskPhase.FAILED, entry.phase)
        assertTrue(entry.summary.contains("Local model suggested PHONE"))
        assertTrue(entry.summary.contains("deterministic route"))
        assertEquals(LocalModelRuntimeState.READY, viewModel.uiState.value.localModelStatus.state)
    }

    @Test
    fun localModelRuntimeProviderObservesUnsupportedCommandAsNonExecutableTimelineTask() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val provider = RecordingLocalModelRuntimeProvider(
            statusProvider = { readyLocalModelStatus() },
            observer = {
                LocalModelIntentObservation.Candidate(
                    LocalModelIntentCandidate(
                        intentLabel = "PHONE",
                        confidence = 0.91f,
                        normalizedCommand = it,
                        rationale = "strict routing JSON passed",
                    ),
                )
            },
        )
        val viewModel = createViewModel(
            gateway,
            localModelRuntimeProvider = provider,
            localModelControlsAvailable = true,
            localModelObservationExecutionAvailable = true,
        )
        advanceUntilIdle()

        viewModel.configureHub(endpoint, token)
        viewModel.submitCommand("open settings")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(listOf("open settings"), provider.commands)
        assertTrue(gateway.requests.isEmpty())
        assertEquals(ExecutionTarget.PHONE, entry.executionTarget)
        assertNull(entry.toolName)
        assertNull(entry.permission)
        assertNull(entry.result)
        assertEquals(TaskPhase.FAILED, entry.phase)
        assertTrue(entry.summary.contains("Local model suggested PHONE"))
        assertTrue(entry.summary.contains("deterministic route"))
        assertTrue(
            entry.events.any {
                it.kind == TaskEventKind.PLAN &&
                    it.message.contains("Local model suggested PHONE at 0.91 confidence")
            },
        )
        assertTrue(
            entry.events.any {
                it.kind == TaskEventKind.ERROR &&
                    it.message.contains("Deterministic route still required")
            },
        )
        assertEquals(LocalModelRuntimeState.READY, viewModel.uiState.value.localModelStatus.state)
    }

    @Test
    fun deterministicPhoneRouteDoesNotInvokeLocalModelRuntimeProvider() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val provider = RecordingLocalModelRuntimeProvider(
            statusProvider = { readyLocalModelStatus() },
            observer = {
                LocalModelIntentObservation.Rejected("provider should not run")
            },
        )
        val viewModel = createViewModel(
            gateway,
            localModelRuntimeProvider = provider,
            localModelControlsAvailable = true,
            localModelObservationExecutionAvailable = true,
        )
        advanceUntilIdle()

        viewModel.submitCommand("show my battery status")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertTrue(provider.commands.isEmpty())
        assertTrue(gateway.requests.isEmpty())
        assertEquals(ExecutionTarget.PHONE, entry.executionTarget)
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals(LocalModelRuntimeState.READY, viewModel.uiState.value.localModelStatus.state)
    }

    @Test
    fun localModelProviderNonReadyStateExplainsUnsupportedCommandRejection() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val provider = RecordingLocalModelRuntimeProvider(
            statusProvider = {
                LocalModelRuntimeStatus(
                    state = LocalModelRuntimeState.UNAVAILABLE,
                    summary = "Approved local model file is unavailable.",
                    enabledByUser = true,
                    runtimeAvailable = true,
                    modelAvailable = false,
                )
            },
            observer = {
                error("provider should not run when status is not ready")
            },
        )
        val viewModel = createViewModel(
            gateway,
            localModelRuntimeProvider = provider,
            localModelControlsAvailable = true,
            localModelObservationExecutionAvailable = true,
        )
        advanceUntilIdle()

        viewModel.submitCommand("open settings")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertTrue(provider.commands.isEmpty())
        assertTrue(gateway.requests.isEmpty())
        assertEquals(TaskPhase.FAILED, entry.phase)
        assertTrue(entry.summary.contains("Approved local model file is unavailable."))
        assertFalse(entry.summary.contains("Local model is off"))
        assertEquals(LocalModelRuntimeState.UNAVAILABLE, viewModel.uiState.value.localModelStatus.state)
    }

    @Test
    fun localModelObservationCanBeCancelledWithoutExecutingRoute() = runTest(dispatcher) {
        var providerCancelled = false
        val gateway = FakeHubGateway { flowOf() }
        val provider = RecordingLocalModelRuntimeProvider(
            statusProvider = { readyLocalModelStatus() },
            observer = {
                try {
                    awaitCancellation()
                } finally {
                    providerCancelled = true
                }
            },
        )
        val viewModel = createViewModel(
            gateway,
            localModelRuntimeProvider = provider,
            localModelControlsAvailable = true,
            localModelObservationExecutionAvailable = true,
        )
        advanceUntilIdle()

        viewModel.submitCommand("open settings")
        runCurrent()
        viewModel.cancelActiveTask()
        runCurrent()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(listOf("open settings"), provider.commands)
        assertTrue(providerCancelled)
        assertTrue(gateway.requests.isEmpty())
        assertNull(entry.toolName)
        assertNull(entry.permission)
        assertNull(entry.result)
        assertEquals(TaskPhase.CANCELLED, entry.phase)
    }

    @Test
    fun localModelRuntimeGateStatusIsShownAndRecheckedByDefault() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val modelRoot = Files.createTempDirectory("goffy-local-model").toFile()
        try {
            val modelFile = File(modelRoot, "tiny.litertlm").also {
                it.writeText("model", charset = Charsets.UTF_8)
            }
            val delegate = RecordingLocalModelFallback(
                LocalModelIntentObservation.Rejected("test observation"),
            )
            val gate = LocalModelRuntimeGate(
                config = LocalModelRuntimeGateConfig(
                    enabledByUser = true,
                    developerRuntimeAllowed = true,
                    runtimeAvailable = true,
                    modelRoot = modelRoot,
                    modelFile = modelFile,
                    policy = LocalModelRuntimePolicy(enabled = true),
                ),
                delegate = delegate,
            )

            val viewModel = createViewModel(gateway, localModelFallback = gate)

            assertEquals(LocalModelRuntimeState.READY, viewModel.uiState.value.localModelStatus.state)
            assertTrue(modelFile.delete())
            viewModel.submitCommand("open settings")
            advanceUntilIdle()

            assertEquals(LocalModelRuntimeState.UNAVAILABLE, viewModel.uiState.value.localModelStatus.state)
            assertEquals(0, delegate.calls)
        } finally {
            modelRoot.deleteRecursively()
        }
    }

    @Test
    fun localModelSettingsLoadDoesNotShowReadyBeforeObservationExecutionIsWired() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val settingsSource = MutableLocalModelRuntimeSettingsSource()
        val settingsStore = RecordingLocalModelSettingsStore(
            loadResult = LocalModelRuntimeSettingsLoadResult.Loaded(
                LocalModelRuntimeSettings(enabledByUser = true),
            ),
        )
        val viewModel = createViewModel(
            gateway,
            localModelSettingsStore = settingsStore,
            localModelSettingsSource = settingsSource,
            localModelRuntimeProvider = StatusOnlyLocalModelRuntimeProvider {
                statusFor(settingsSource.snapshot())
            },
            localModelControlsAvailable = true,
        )

        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.localModelControlsAvailable)
        assertEquals(LocalModelRuntimeState.UNAVAILABLE, viewModel.uiState.value.localModelStatus.state)
        assertEquals(true, viewModel.uiState.value.localModelStatus.enabledByUser)
        assertTrue(viewModel.uiState.value.localModelStatus.summary.contains("not wired"))
    }

    @Test
    fun localModelEnableIsStoredButDoesNotShowReadyBeforeObservationExecutionIsWired() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val settingsSource = MutableLocalModelRuntimeSettingsSource()
        val settingsStore = RecordingLocalModelSettingsStore()
        val viewModel = createViewModel(
            gateway,
            localModelSettingsStore = settingsStore,
            localModelSettingsSource = settingsSource,
            localModelRuntimeProvider = StatusOnlyLocalModelRuntimeProvider {
                statusFor(settingsSource.snapshot())
            },
            localModelControlsAvailable = true,
        )
        advanceUntilIdle()

        assertTrue(viewModel.setLocalModelEnabled(true))
        assertTrue(viewModel.uiState.value.localModelOperationInProgress)
        advanceUntilIdle()

        assertEquals(listOf(LocalModelRuntimeSettings(enabledByUser = true)), settingsStore.savedSettings)
        assertEquals(true, settingsSource.snapshot().enabledByUser)
        assertEquals(LocalModelRuntimeState.UNAVAILABLE, viewModel.uiState.value.localModelStatus.state)
        assertEquals(false, viewModel.uiState.value.localModelNotice?.warning)
    }

    @Test
    fun localModelEnableFailureLeavesRuntimeDisabled() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val settingsSource = MutableLocalModelRuntimeSettingsSource()
        val settingsStore = RecordingLocalModelSettingsStore(
            saveResult = { LocalModelRuntimeSettingsSaveResult.Failed },
        )
        val viewModel = createViewModel(
            gateway,
            localModelSettingsStore = settingsStore,
            localModelSettingsSource = settingsSource,
            localModelControlsAvailable = true,
            localModelStatusProvider = { statusFor(settingsSource.snapshot()) },
        )
        advanceUntilIdle()

        assertTrue(viewModel.setLocalModelEnabled(true))
        advanceUntilIdle()

        assertEquals(false, settingsSource.snapshot().enabledByUser)
        assertEquals(LocalModelRuntimeState.DISABLED, viewModel.uiState.value.localModelStatus.state)
        assertEquals(true, viewModel.uiState.value.localModelNotice?.warning)
    }

    @Test
    fun localModelDisableFailureForcesRuntimeDisabled() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val settingsSource = MutableLocalModelRuntimeSettingsSource()
        val settingsStore = RecordingLocalModelSettingsStore(
            loadResult = LocalModelRuntimeSettingsLoadResult.Loaded(
                LocalModelRuntimeSettings(enabledByUser = true),
            ),
            saveResult = { LocalModelRuntimeSettingsSaveResult.Failed },
        )
        val viewModel = createViewModel(
            gateway,
            localModelSettingsStore = settingsStore,
            localModelSettingsSource = settingsSource,
            localModelControlsAvailable = true,
            localModelStatusProvider = { statusFor(settingsSource.snapshot()) },
        )
        advanceUntilIdle()

        assertTrue(viewModel.setLocalModelEnabled(false))
        advanceUntilIdle()

        assertEquals(false, settingsSource.snapshot().enabledByUser)
        assertEquals(LocalModelRuntimeState.DISABLED, viewModel.uiState.value.localModelStatus.state)
        assertEquals(true, viewModel.uiState.value.localModelNotice?.warning)
    }

    @Test
    fun localModelToggleIsRejectedUntilSettingsLoadCompletes() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val settingsStore = RecordingLocalModelSettingsStore(
            loadResult = LocalModelRuntimeSettingsLoadResult.Loaded(
                LocalModelRuntimeSettings(enabledByUser = true),
            ),
        )
        val viewModel = createViewModel(
            gateway,
            localModelSettingsStore = settingsStore,
            localModelControlsAvailable = true,
        )

        assertFalse(viewModel.uiState.value.localModelSettingsLoaded)
        assertFalse(viewModel.setLocalModelEnabled(false))
        assertTrue(settingsStore.savedSettings.isEmpty())
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.localModelSettingsLoaded)
    }

    @Test
    fun localModelControlsFailClosedWhenRuntimeVariantIsUnavailable() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val viewModel = createViewModel(gateway)
        advanceUntilIdle()

        assertFalse(viewModel.setLocalModelEnabled(true))

        assertFalse(viewModel.uiState.value.localModelControlsAvailable)
        assertEquals(LocalModelRuntimeState.DISABLED, viewModel.uiState.value.localModelStatus.state)
        assertEquals(true, viewModel.uiState.value.localModelNotice?.warning)
    }

    @Test
    fun batteryStatusRunsAndVerifiesLocallyWithoutHubConfiguration() = runTest(dispatcher) {
        val hubGateway = FakeHubGateway { flowOf() }
        val phoneGateway = DefaultPhoneToolGateway(
            batteryStatusSource = {
                PhoneBatteryStatus(levelPercent = 64, charging = false)
            },
            deviceInfoSource = { validDeviceInfo() },
            noteStore = fakeNoteStore(),
            timerSource = fakeTimerSource(),
            flashlightSource = fakeFlashlightSource(),
            readDispatcher = dispatcher,
        )
        val viewModel = createViewModel(hubGateway, phoneGateway)

        viewModel.submitCommand("Show my battery status")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertTrue(hubGateway.requests.isEmpty())
        assertEquals(ExecutionTarget.PHONE, entry.executionTarget)
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals(PhoneBatteryStatus(64, false), entry.result)
        assertFalse(viewModel.uiState.value.hubConfigured)
    }

    @Test
    fun terminalTaskIsPersistedOnceAndMarkedVisible() = runTest(dispatcher) {
        val auditStore = RecordingAuditStore()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            auditStore = auditStore,
            nowMillis = { 4_242L },
        )

        viewModel.submitCommand("Show my battery status")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals(AuditPersistenceState.READY, viewModel.uiState.value.auditPersistence)
        assertEquals(1, auditStore.upserts.size)
        assertEquals(entry.id, auditStore.upserts.single().taskId)
        assertEquals(4_242L, auditStore.upserts.single().recordedAtEpochMillis)
        assertEquals(4_242L, entry.terminalAtEpochMillis)
        assertTrue(entry.auditRecordedAtEpochMillis != null)
    }

    @Test
    fun restoredAuditCannotResumeTaskOrApprovalAuthority() = runTest(dispatcher) {
        val restored = batteryAuditRecord()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            auditStore = RecordingAuditStore(initialRecords = listOf(restored)),
        )

        advanceUntilIdle()

        val state = viewModel.uiState.value
        val entry = state.timeline.entries.single()
        assertEquals(restored.taskId, entry.id)
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertNull(entry.result)
        assertNull(state.timeline.activeTaskId)
        assertNull(state.pendingApproval)
    }

    @Test
    fun deviceInfoRunsAndVerifiesLocallyWithoutHubConfiguration() = runTest(dispatcher) {
        val hubGateway = FakeHubGateway { flowOf() }
        val phoneGateway = DefaultPhoneToolGateway(
            batteryStatusSource = { PhoneBatteryStatus(50, false) },
            deviceInfoSource = { validDeviceInfo() },
            noteStore = fakeNoteStore(),
            timerSource = fakeTimerSource(),
            flashlightSource = fakeFlashlightSource(),
            readDispatcher = dispatcher,
        )
        val viewModel = createViewModel(hubGateway, phoneGateway)

        viewModel.submitCommand("Show my phone info")
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertTrue(hubGateway.requests.isEmpty())
        assertEquals(ExecutionTarget.PHONE, entry.executionTarget)
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals(validDeviceInfo(), entry.result)
        assertFalse(viewModel.uiState.value.hubConfigured)
    }

    @Test
    fun missingOrInvalidConfigurationFailsClosed() = runTest(dispatcher) {
        val gateway = FakeHubGateway { flowOf() }
        val auditStore = RecordingAuditStore()
        val viewModel = createViewModel(gateway, auditStore = auditStore)

        viewModel.submitCommand("Show my Mac status")
        assertTrue(gateway.requests.isEmpty())
        assertEquals(TaskPhase.FAILED, viewModel.uiState.value.timeline.entries.single().phase)
        assertEquals(ExecutionTarget.MAC, viewModel.uiState.value.timeline.entries.single().executionTarget)

        assertTrue(viewModel.configureHub(endpoint, token))
        assertFalse(viewModel.configureHub("ws://mac.example/ws/v1", token))
        viewModel.submitCommand("Show my Mac status")
        advanceUntilIdle()

        assertEquals(1, gateway.requests.size)
        assertTrue(viewModel.uiState.value.hubConfigured)
        assertEquals(2, auditStore.upserts.size)
        assertTrue(auditStore.upserts.all { it.executionTarget == ExecutionTarget.MAC })
        assertTrue(auditStore.upserts.all { it.toolName == "mac.system_info" })
    }

    @Test
    fun cancellationStopsCollectionAndRecordsItsLocalScope() = runTest(dispatcher) {
        var collectionCancelled = false
        val gateway = FakeHubGateway {
            flow {
                try {
                    emit(ExecutionEvent.Starting(1))
                    awaitCancellation()
                } finally {
                    collectionCancelled = true
                }
            }
        }
        val viewModel = createViewModel(gateway)

        viewModel.configureHub(endpoint, token)
        viewModel.submitCommand("Show my Mac status")
        runCurrent()
        viewModel.cancelActiveTask()
        runCurrent()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertTrue(collectionCancelled)
        assertEquals(TaskPhase.CANCELLED, entry.phase)
        assertTrue(entry.summary.contains("Hub completion is not guaranteed"))
    }

    @Test
    fun commandSubmittedWhileBusyGetsAVisibleRejection() = runTest(dispatcher) {
        val gateway = FakeHubGateway {
            flow {
                emit(ExecutionEvent.Starting(1))
                awaitCancellation()
            }
        }
        val viewModel = createViewModel(gateway)

        viewModel.configureHub(endpoint, token)
        viewModel.submitCommand("Show my Mac status")
        runCurrent()
        viewModel.submitCommand("Check my Mac status")

        val entries = viewModel.uiState.value.timeline.entries
        assertEquals(1, gateway.requests.size)
        assertEquals(2, entries.size)
        assertEquals(TaskPhase.FAILED, entries.last().phase)
        assertTrue(entries.last().summary.contains("already running"))
        assertTrue(viewModel.uiState.value.isBusy)

        viewModel.cancelActiveTask()
        runCurrent()
    }

    @Test
    fun noteStorageIsNotReachedUntilOneExactApproval() = runTest(dispatcher) {
        val noteStore = RecordingNoteStore()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(noteStore),
        )

        viewModel.submitCommand("Create a note saying Buy milk")
        runCurrent()

        val pending = viewModel.uiState.value.pendingApproval
        assertTrue(pending != null)
        assertEquals(TaskPhase.AWAITING_APPROVAL, viewModel.uiState.value.timeline.entries.single().phase)
        assertEquals(0, noteStore.creates)

        assertTrue(viewModel.approvePendingTask(pending!!.taskId))
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(1, noteStore.creates)
        assertEquals("Buy milk", noteStore.lastText)
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals(PhoneNoteCreated(1, "Buy milk", 1_720_000_000_000), entry.result)
        assertFalse(viewModel.approvePendingTask(pending.taskId))
        assertEquals(1, noteStore.creates)
    }

    @Test
    fun persistedNoteAuditNeverContainsPrivateNoteText() = runTest(dispatcher) {
        val auditStore = RecordingAuditStore()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(RecordingNoteStore()),
            auditStore = auditStore,
        )

        viewModel.submitCommand("Create a note saying Buy milk")
        runCurrent()
        assertTrue(viewModel.approvePendingTask(viewModel.uiState.value.pendingApproval!!.taskId))
        advanceUntilIdle()

        assertEquals(1, auditStore.upserts.size)
        assertFalse(auditStore.upserts.single().toString().contains("Buy milk"))
    }

    @Test
    fun auditWriteFailureIsVisibleWithoutRewritingVerifiedOutcome() = runTest(dispatcher) {
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            auditStore = RecordingAuditStore(failWrites = true),
        )

        viewModel.submitCommand("Show my battery status")
        advanceUntilIdle()

        assertEquals(TaskPhase.VERIFIED, viewModel.uiState.value.timeline.entries.single().phase)
        assertEquals(AuditPersistenceState.DEGRADED, viewModel.uiState.value.auditPersistence)
        assertNull(viewModel.uiState.value.timeline.entries.single().auditRecordedAtEpochMillis)
    }

    @Test
    fun auditLoadFailureIsVisibleAndDoesNotBlockNewCommands() = runTest(dispatcher) {
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            auditStore = RecordingAuditStore(failLoads = true),
        )

        runCurrent()
        assertEquals(AuditPersistenceState.DEGRADED, viewModel.uiState.value.auditPersistence)

        viewModel.submitCommand("Show my battery status")
        advanceUntilIdle()

        assertEquals(TaskPhase.VERIFIED, viewModel.uiState.value.timeline.entries.single().phase)
    }

    @Test
    fun deniedOrCancelledNoteApprovalNeverInvokesStorage() = runTest(dispatcher) {
        val deniedStore = RecordingNoteStore()
        val deniedViewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(deniedStore),
        )
        deniedViewModel.submitCommand("Create a note saying Buy milk")
        runCurrent()
        val deniedTask = deniedViewModel.uiState.value.pendingApproval!!.taskId
        assertTrue(deniedViewModel.denyPendingTask(deniedTask))
        runCurrent()

        assertEquals(0, deniedStore.creates)
        assertEquals(TaskPhase.CANCELLED, deniedViewModel.uiState.value.timeline.entries.single().phase)

        val cancelledStore = RecordingNoteStore()
        val cancelledViewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(cancelledStore),
        )
        cancelledViewModel.submitCommand("Create a note saying Call the dentist")
        runCurrent()
        cancelledViewModel.cancelActiveTask()
        runCurrent()

        assertEquals(0, cancelledStore.creates)
        assertEquals(TaskPhase.CANCELLED, cancelledViewModel.uiState.value.timeline.entries.single().phase)
        assertNull(cancelledViewModel.uiState.value.pendingApproval)
    }

    @Test
    fun expiredOrStaleApprovalFailsClosedWithoutStorage() = runTest(dispatcher) {
        val noteStore = RecordingNoteStore()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(noteStore),
            approvalTtlMillis = 1_000,
            nowMillis = { testScheduler.currentTime },
        )
        viewModel.submitCommand("Create a note saying Buy milk")
        runCurrent()
        val taskId = viewModel.uiState.value.pendingApproval!!.taskId

        assertFalse(viewModel.approvePendingTask(UUID.randomUUID()))
        advanceTimeBy(1_000)
        runCurrent()

        assertEquals(0, noteStore.creates)
        assertEquals(TaskPhase.FAILED, viewModel.uiState.value.timeline.entries.single().phase)
        assertNull(viewModel.uiState.value.pendingApproval)
        assertFalse(viewModel.approvePendingTask(taskId))
    }

    @Test
    fun systemTimerIsDispatchedOnlyAfterVisibleOneTimeApproval() = runTest(dispatcher) {
        val timerSource = RecordingTimerSource()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(timerSource = timerSource),
        )

        viewModel.submitCommand("Set a timer for 5 minutes")
        runCurrent()

        val pending = viewModel.uiState.value.pendingApproval
        assertTrue(pending != null)
        assertTrue(pending!!.description.contains("5 minutes"))
        assertEquals(TaskPhase.AWAITING_APPROVAL, viewModel.uiState.value.timeline.entries.single().phase)
        assertEquals(0, timerSource.dispatches)

        assertTrue(viewModel.approvePendingTask(pending.taskId))
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(1, timerSource.dispatches)
        assertEquals(300, timerSource.lastDurationSeconds)
        assertEquals(TaskPhase.UNVERIFIED, entry.phase)
        assertTrue(entry.summary.contains("not readable"))
        assertEquals(
            validTimerResult(300),
            entry.result,
        )
        assertFalse(viewModel.approvePendingTask(pending.taskId))
        assertEquals(1, timerSource.dispatches)
    }

    @Test
    fun flashlightChangesOnlyAfterVisibleOneTimeApprovalAndEndsVerified() = runTest(dispatcher) {
        val flashlightSource = RecordingFlashlightSource()
        val viewModel = createViewModel(
            gateway = FakeHubGateway { flowOf() },
            phoneGateway = phoneGateway(flashlightSource = flashlightSource),
        )

        viewModel.submitCommand("Turn on the flashlight")
        runCurrent()

        val pending = viewModel.uiState.value.pendingApproval
        assertTrue(pending != null)
        assertTrue(pending!!.description.contains("turning on"))
        assertTrue(pending.description.contains("will not open the camera"))
        assertEquals(TaskPhase.AWAITING_APPROVAL, viewModel.uiState.value.timeline.entries.single().phase)
        assertEquals(0, flashlightSource.calls)

        assertTrue(viewModel.approvePendingTask(pending.taskId))
        advanceUntilIdle()

        val entry = viewModel.uiState.value.timeline.entries.single()
        assertEquals(1, flashlightSource.calls)
        assertEquals(true, flashlightSource.lastEnabled)
        assertEquals(TaskPhase.VERIFIED, entry.phase)
        assertEquals(validFlashlightResult(true), entry.result)
        assertFalse(viewModel.approvePendingTask(pending.taskId))
        assertEquals(1, flashlightSource.calls)
    }

    private fun createViewModel(
        gateway: HubGateway,
        phoneGateway: PhoneToolGateway = DefaultPhoneToolGateway(
            batteryStatusSource = {
                PhoneBatteryStatus(levelPercent = 50, charging = false)
            },
            deviceInfoSource = { validDeviceInfo() },
            noteStore = fakeNoteStore(),
            timerSource = fakeTimerSource(),
            flashlightSource = fakeFlashlightSource(),
            readDispatcher = dispatcher,
        ),
        pairingGateway: HubPairingGateway = RecordingPairingGateway(),
        operatorAuditGateway: HubOperatorAuditGateway = RecordingHubOperatorAuditGateway(),
        credentialStore: HubCredentialStore = RecordingCredentialStore(),
        approvalTtlMillis: Long = 60_000,
        allowDevelopmentTokenConfiguration: Boolean = true,
        nowMillis: () -> Long = System::currentTimeMillis,
        auditStore: TerminalAuditStore = RecordingAuditStore(),
        localModelFallback: LocalModelIntentFallback = LocalModelIntentFallback {
            LocalModelIntentObservation.Disabled(
                "Local model is off; deterministic routing is authoritative.",
            )
        },
        localModelStatus: LocalModelRuntimeStatus =
            (localModelFallback as? LocalModelRuntimeGate)?.status ?: LocalModelRuntimeStatus.disabled(),
        localModelSettingsStore: LocalModelRuntimeSettingsStore = RecordingLocalModelSettingsStore(),
        localModelSettingsSource: MutableLocalModelRuntimeSettingsSource =
            MutableLocalModelRuntimeSettingsSource(),
        localModelRuntimeProvider: LocalModelRuntimeProvider? = null,
        localModelControlsAvailable: Boolean = false,
        localModelObservationExecutionAvailable: Boolean = false,
        localModelStatusProvider: (() -> LocalModelRuntimeStatus)? = null,
    ): GoffyViewModel {
        val protocolMessageIds = ArrayDeque(
            listOf(
                UUID.fromString("11111111-1111-4111-8111-111111111111"),
                UUID.fromString("33333333-3333-4333-8333-333333333333"),
            ),
        )
        return GoffyViewModel(
            gateway = gateway,
            pairingGateway = pairingGateway,
            operatorAuditGateway = operatorAuditGateway,
            credentialStore = credentialStore,
            phoneGateway = phoneGateway,
            codec = GoffyProtocolCodec(
                now = { Instant.parse("2026-07-13T16:00:00Z") },
                nextMessageId = { protocolMessageIds.removeFirst() },
            ),
            allowInsecureLoopback = true,
            allowDevelopmentTokenConfiguration = allowDevelopmentTokenConfiguration,
            defaultEndpoint = endpoint,
            deviceId = "goffy-android-test",
            deviceDisplayName = "Moto G",
            nextTaskId = { UUID.fromString("22222222-2222-4222-8222-222222222222") },
            approvalTtlMillis = approvalTtlMillis,
            nowMillis = nowMillis,
            auditStore = auditStore,
            auditDispatcher = dispatcher,
            credentialDispatcher = dispatcher,
            localModelSettingsStore = localModelSettingsStore,
            localModelSettingsSource = localModelSettingsSource,
            localModelRuntimeProvider = localModelRuntimeProvider,
            localModelSettingsDispatcher = dispatcher,
            localModelControlsAvailable = localModelControlsAvailable,
            localModelObservationExecutionAvailable = localModelObservationExecutionAvailable,
            localModelFallback = localModelFallback,
            localModelStatus = localModelStatus,
            localModelStatusProvider = localModelStatusProvider
                ?: localModelRuntimeProvider?.let { provider -> { provider.status } }
                ?: (localModelFallback as? LocalModelRuntimeGate)?.let { gate -> { gate.status } }
                ?: { localModelStatus },
        )
    }

    private fun statusFor(settings: LocalModelRuntimeSettings): LocalModelRuntimeStatus =
        if (settings.enabledByUser) {
            readyLocalModelStatus()
        } else {
            LocalModelRuntimeStatus.disabled()
        }

    private fun readyLocalModelStatus(): LocalModelRuntimeStatus = LocalModelRuntimeStatus(
        state = LocalModelRuntimeState.READY,
        summary = "Local model ready for observe-only fallback.",
        enabledByUser = true,
        runtimeAvailable = true,
        modelAvailable = true,
    )

    private fun storedCredential(): StoredHubCredential = StoredHubCredential.create(
        endpoint = endpoint,
        credentialId = UUID.fromString("55555555-5555-4555-8555-555555555555"),
        deviceId = "goffy-android-test",
        accessToken = "$token-xx",
        createdAt = Instant.parse("2026-07-13T16:00:00Z"),
        hubIdentity = hubIdentityPin(),
        allowInsecureLoopback = true,
    )

    private fun hubIdentityPin(): HubIdentityPin = HubIdentityPin.create(
        hubId = UUID.fromString("44444444-4444-4444-8444-444444444444"),
        fingerprint = hubFingerprint,
        createdAt = Instant.parse("2026-07-13T15:59:00Z"),
    )

    private fun batteryAuditRecord(): ClosedTerminalAuditRecord = ClosedTerminalAuditRecord(
        taskId = UUID.fromString("44444444-4444-4444-8444-444444444444"),
        recordedAtEpochMillis = 1_720_000_000_000,
        protocolVersion = GOFFY_PROTOCOL_VERSION,
        sourceSurface = AuditSourceSurface.TERMINAL_TIMELINE,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_BATTERY_STATUS_TOOL,
        permission = AuditPermission.SAFE,
        phase = TerminalAuditPhase.VERIFIED,
        approvalOutcome = AuditApprovalOutcome.NOT_REQUIRED,
        eventKinds = emptyList(),
    )

    private fun phoneGateway(
        noteStore: NoteStore = fakeNoteStore(),
        timerSource: TimerSource = fakeTimerSource(),
        flashlightSource: FlashlightSource = fakeFlashlightSource(),
    ): PhoneToolGateway = DefaultPhoneToolGateway(
        batteryStatusSource = { PhoneBatteryStatus(50, false) },
        deviceInfoSource = { validDeviceInfo() },
        noteStore = noteStore,
        timerSource = timerSource,
        flashlightSource = flashlightSource,
        readDispatcher = dispatcher,
    )

    private fun successfulEvents(): List<ExecutionEvent> = listOf(
        ExecutionEvent.Starting(1),
        ExecutionEvent.Ready,
        ExecutionEvent.Progress(
            ToolProgress("mac.system_info", ExecutionTarget.MAC, "accepted", 0, "Accepted"),
        ),
        ExecutionEvent.Progress(
            ToolProgress("mac.system_info", ExecutionTarget.MAC, "completed", 1, "Completed"),
        ),
        ExecutionEvent.Result(
            toolName = "mac.system_info",
            executionTarget = ExecutionTarget.MAC,
            content = MacSystemInfo("available", "Darwin", "arm64"),
        ),
        ExecutionEvent.Verification(
            succeeded = true,
            summary = "Verified",
            checks = listOf("output schema"),
        ),
    )

    private fun successfulMacFilesEvents(): List<ExecutionEvent> = listOf(
        ExecutionEvent.Starting(1),
        ExecutionEvent.Ready,
        ExecutionEvent.Progress(
            ToolProgress("mac.files.list", ExecutionTarget.MAC, "accepted", 0, "Accepted"),
        ),
        ExecutionEvent.Progress(
            ToolProgress("mac.files.list", ExecutionTarget.MAC, "completed", 1, "Completed"),
        ),
        ExecutionEvent.Result(
            toolName = "mac.files.list",
            executionTarget = ExecutionTarget.MAC,
            content = MacFilesList(
                status = "available",
                rootIndex = 0,
                rootName = "goffy",
                relativePath = "",
                truncated = false,
                approvedRoots = listOf(MacFilesApprovedRoot(0, "goffy")),
                entries = listOf(
                    MacFilesListEntry("README.md", false, "file", 1024, 1784610000),
                ),
            ),
        ),
        ExecutionEvent.Verification(
            succeeded = true,
            summary = "Verified",
            checks = listOf("output schema"),
        ),
    )

    private fun successfulGitStatusEvents(): List<ExecutionEvent> = listOf(
        ExecutionEvent.Starting(1),
        ExecutionEvent.Ready,
        ExecutionEvent.Progress(
            ToolProgress("git.status", ExecutionTarget.MAC, "accepted", 0, "Accepted"),
        ),
        ExecutionEvent.Progress(
            ToolProgress("git.status", ExecutionTarget.MAC, "completed", 1, "Completed"),
        ),
        ExecutionEvent.Result(
            toolName = "git.status",
            executionTarget = ExecutionTarget.MAC,
            content = GitStatus(
                status = "available",
                repoIndex = 0,
                repoName = "goffy",
                branch = "main",
                headOidShort = "0123456789abcdef",
                upstream = null,
                ahead = null,
                behind = null,
                clean = false,
                stagedCount = 1,
                unstagedCount = 0,
                untrackedCount = 1,
                conflictCount = 0,
                truncated = false,
                approvedRepos = listOf(GitStatusApprovedRepo(0, "goffy")),
                changes = listOf(
                    GitStatusChange("README.md", false, "M", ".", "tracked"),
                    GitStatusChange("TODO.md", false, "?", "?", "untracked"),
                ),
            ),
        ),
        ExecutionEvent.Verification(
            succeeded = true,
            summary = "Verified",
            checks = listOf("output schema"),
        ),
    )

    private fun successfulMacClipboardEvents(): List<ExecutionEvent> = listOf(
        ExecutionEvent.Starting(1),
        ExecutionEvent.Ready,
        ExecutionEvent.Progress(
            ToolProgress("mac.clipboard.read", ExecutionTarget.MAC, "accepted", 0, "Accepted"),
        ),
        ExecutionEvent.Progress(
            ToolProgress("mac.clipboard.read", ExecutionTarget.MAC, "completed", 1, "Completed"),
        ),
        ExecutionEvent.Result(
            toolName = "mac.clipboard.read",
            executionTarget = ExecutionTarget.MAC,
            content = MacClipboardRead(
                status = "available",
                contentType = "text",
                text = "copied text",
                textTruncated = false,
                characterCount = 11,
                characterCountTruncated = false,
            ),
        ),
        ExecutionEvent.Verification(
            succeeded = true,
            summary = "Verified",
            checks = listOf("output schema"),
        ),
    )

    private fun validDeviceInfo(): PhoneDeviceInfo = PhoneDeviceInfo(
        manufacturer = "motorola",
        model = "moto g",
        androidRelease = "15",
        sdkInt = 35,
    )

    private fun fakeNoteStore(): NoteStore = object : NoteStore {
        override suspend fun create(text: String): PhoneNoteCreated =
            PhoneNoteCreated(1, text, 1)

        override fun close() = Unit
    }

    private fun fakeTimerSource(): TimerSource = TimerSource { arguments ->
        validTimerResult(arguments.durationSeconds)
    }

    private fun fakeFlashlightSource(): FlashlightSource = FlashlightSource { arguments ->
        validFlashlightResult(arguments.enabled)
    }

    private fun validTimerResult(durationSeconds: Int): PhoneTimerDispatched = PhoneTimerDispatched(
        durationSeconds,
        "com.google.android.deskclock",
        "com.google.android.deskclock.TimerActivity",
        true,
        true,
        ANDROID_SET_TIMER_ACTION,
    )

    private fun validFlashlightResult(enabled: Boolean): PhoneFlashlightState = PhoneFlashlightState(
        enabled = enabled,
        stateChanged = true,
    )

    private class RecordingNoteStore : NoteStore {
        var creates = 0
        var lastText: String? = null

        override suspend fun create(text: String): PhoneNoteCreated {
            creates += 1
            lastText = text
            return PhoneNoteCreated(1, text, 1_720_000_000_000)
        }

        override fun close() = Unit
    }

    private class RecordingLocalModelFallback(
        private val observation: LocalModelIntentObservation,
    ) : LocalModelIntentFallback {
        var calls = 0
            private set

        override fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
            calls += 1
            return observation
        }
    }

    private class RecordingAuditStore(
        initialRecords: List<ClosedTerminalAuditRecord> = emptyList(),
        private val failLoads: Boolean = false,
        private val failWrites: Boolean = false,
    ) : TerminalAuditStore {
        private val records = initialRecords.associateByTo(linkedMapOf()) { it.taskId }
        val upserts = mutableListOf<ClosedTerminalAuditRecord>()

        override suspend fun load(): ClosedTerminalAuditLoadResult {
            if (failLoads) error("simulated audit load failure")
            return ClosedTerminalAuditLoadResult(records.values.toList(), 0)
        }

        override suspend fun upsert(record: ClosedTerminalAuditRecord): ClosedTerminalAuditRecord {
            if (failWrites) error("simulated audit write failure")
            upserts += record
            records[record.taskId] = record
            return record
        }

        override fun close() = Unit
    }

    private class RecordingTimerSource : TimerSource {
        var dispatches = 0
        var lastDurationSeconds: Int? = null

        override suspend fun create(arguments: PhoneTimerCreateArguments): PhoneTimerDispatched {
            dispatches += 1
            lastDurationSeconds = arguments.durationSeconds
            return PhoneTimerDispatched(
                arguments.durationSeconds,
                "com.google.android.deskclock",
                "com.google.android.deskclock.TimerActivity",
                true,
                arguments.skipClockUi,
                ANDROID_SET_TIMER_ACTION,
            )
        }
    }

    private class RecordingFlashlightSource : FlashlightSource {
        var calls = 0
        var lastEnabled: Boolean? = null

        override suspend fun set(arguments: PhoneFlashlightSetArguments): PhoneFlashlightState {
            calls += 1
            lastEnabled = arguments.enabled
            return PhoneFlashlightState(
                enabled = arguments.enabled,
                stateChanged = true,
            )
        }
    }

    private class FakeHubGateway(
        private val events: (ToolInvocationRequest) -> Flow<ExecutionEvent>,
    ) : HubGateway {
        val requests = mutableListOf<ToolInvocationRequest>()

        override fun invoke(config: HubConfig, request: ToolInvocationRequest): Flow<ExecutionEvent> {
            requests += request
            return events(request)
        }

        override fun close() = Unit
    }

    private inner class RecordingHubOperatorAuditGateway(
        private val failure: HubOperatorAuditException? = null,
    ) : HubOperatorAuditGateway {
        var calls = 0
        val configs = mutableListOf<HubConfig>()
        val limits = mutableListOf<Int>()

        override suspend fun listSelfEvents(
            config: HubConfig,
            limit: Int,
        ): HubOperatorAuditSnapshot {
            calls += 1
            configs += config
            limits += limit
            failure?.let { throw it }
            return HubOperatorAuditSnapshot(
                storageKind = "sqlite",
                integrity = "verified",
                events = listOf(
                    HubOperatorAuditEvent(
                        sequence = 7,
                        recordedAt = Instant.parse("2026-07-13T16:01:00Z"),
                        source = "mcp",
                        action = "http.get",
                        outcome = "succeeded",
                        principalKind = "paired",
                        credentialId = storedCredential().credentialId,
                        detailCode = null,
                        previousHash = null,
                        eventHash = null,
                    ),
                ),
            )
        }

        override fun close() = Unit
    }

    private inner class RecordingPairingGateway(
        private val failRevocation: Boolean = false,
        private val failRotation: Boolean = false,
    ) : HubPairingGateway {
        var calls = 0
        var revocationCalls = 0
        var rotationCalls = 0
        val revokedCredentialIds = mutableListOf<UUID>()
        val rotatedCredentialIds = mutableListOf<UUID>()

        override suspend fun redeem(
            endpoint: HubEndpoint,
            challengeJson: String,
            deviceId: String,
            displayName: String,
        ): IssuedHubCredential {
            calls += 1
            return IssuedHubCredential(
                UUID.fromString("55555555-5555-4555-8555-555555555555"),
                "test-token-that-is-long-enough-xx",
                Instant.parse("2026-07-13T16:00:00Z"),
                hubIdentityPin(),
            )
        }

        override suspend fun revokeSelf(
            config: HubConfig,
            expectedCredentialId: UUID,
        ): SelfRevocationResult {
            revocationCalls += 1
            revokedCredentialIds += expectedCredentialId
            if (failRevocation) {
                throw HubPairingException(
                    "simulated_revocation_failure",
                    "Simulated revocation failure.",
                )
            }
            return SelfRevocationResult(expectedCredentialId, revoked = true)
        }

        override suspend fun rotateSelf(
            config: HubConfig,
            expectedCredentialId: UUID,
        ): RotatedHubCredential {
            rotationCalls += 1
            rotatedCredentialIds += expectedCredentialId
            if (failRotation) {
                throw HubPairingException(
                    "simulated_rotation_failure",
                    "Simulated rotation failure.",
                )
            }
            return RotatedHubCredential(
                expectedCredentialId,
                "rotated-token-that-is-long-enough-xx",
                Instant.parse("2026-07-13T16:05:00Z"),
            )
        }

        override fun close() = Unit
    }

    private class BlockingPairingGateway : HubPairingGateway {
        override suspend fun redeem(
            endpoint: HubEndpoint,
            challengeJson: String,
            deviceId: String,
            displayName: String,
        ): IssuedHubCredential = awaitCancellation()

        override suspend fun revokeSelf(
            config: HubConfig,
            expectedCredentialId: UUID,
        ): SelfRevocationResult = error("self-revocation should not run while pairing is blocked")

        override suspend fun rotateSelf(
            config: HubConfig,
            expectedCredentialId: UUID,
        ): RotatedHubCredential = error("rotation should not run while pairing is blocked")

        override fun close() = Unit
    }

    private class RecordingLocalModelSettingsStore(
        private val loadResult: LocalModelRuntimeSettingsLoadResult =
            LocalModelRuntimeSettingsLoadResult.Loaded(LocalModelRuntimeSettings()),
        private val saveResult: (LocalModelRuntimeSettings) -> LocalModelRuntimeSettingsSaveResult =
            { LocalModelRuntimeSettingsSaveResult.Saved(it) },
    ) : LocalModelRuntimeSettingsStore {
        val savedSettings = mutableListOf<LocalModelRuntimeSettings>()

        override fun load(): LocalModelRuntimeSettingsLoadResult = loadResult

        override fun save(settings: LocalModelRuntimeSettings): LocalModelRuntimeSettingsSaveResult {
            savedSettings += settings
            return saveResult(settings)
        }
    }

    private class StatusOnlyLocalModelRuntimeProvider(
        private val statusProvider: () -> LocalModelRuntimeStatus,
    ) : LocalModelRuntimeProvider {
        override val status: LocalModelRuntimeStatus
            get() = statusProvider()

        override suspend fun observeUnsupportedCommand(command: String): LocalModelIntentObservation =
            error("local model observation execution is not wired in this test")
    }

    private class RecordingLocalModelRuntimeProvider(
        private val statusProvider: () -> LocalModelRuntimeStatus,
        private val observer: suspend (String) -> LocalModelIntentObservation,
    ) : LocalModelRuntimeProvider {
        val commands = mutableListOf<String>()

        override val status: LocalModelRuntimeStatus
            get() = statusProvider()

        override suspend fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
            commands += command
            return observer(command)
        }
    }

    private class RecordingCredentialStore(
        initial: HubCredentialLoadResult = HubCredentialLoadResult.Empty,
        private val failSaves: Boolean = false,
        private val failClears: Boolean = false,
    ) : HubCredentialStore {
        private var loaded = initial
        var saves = 0
        var clears = 0
        val savedCredentials = mutableListOf<StoredHubCredential>()

        override fun load(): HubCredentialLoadResult = loaded

        override fun save(credential: StoredHubCredential): StoredHubCredential {
            saves += 1
            if (failSaves) error("simulated credential persistence failure")
            savedCredentials += credential
            loaded = HubCredentialLoadResult.Loaded(credential)
            return credential
        }

        override fun clear() {
            clears += 1
            if (failClears) error("simulated credential clear failure")
            loaded = HubCredentialLoadResult.Empty
        }
    }
}
