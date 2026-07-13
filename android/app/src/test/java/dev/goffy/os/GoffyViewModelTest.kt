package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.hub.HubConfig
import dev.goffy.os.hub.HubGateway
import dev.goffy.os.phone.DefaultPhoneToolGateway
import dev.goffy.os.phone.FlashlightSource
import dev.goffy.os.phone.PhoneToolGateway
import dev.goffy.os.phone.NoteStore
import dev.goffy.os.phone.TimerSource
import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GoffyProtocolCodec
import dev.goffy.os.protocol.MacSystemInfo
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
        val viewModel = createViewModel(gateway)

        viewModel.submitCommand("Show my Mac status")
        assertTrue(gateway.requests.isEmpty())
        assertEquals(TaskPhase.FAILED, viewModel.uiState.value.timeline.entries.single().phase)

        assertTrue(viewModel.configureHub(endpoint, token))
        assertFalse(viewModel.configureHub("ws://mac.example/ws/v1", token))
        viewModel.submitCommand("Show my Mac status")
        advanceUntilIdle()

        assertTrue(gateway.requests.isEmpty())
        assertFalse(viewModel.uiState.value.hubConfigured)
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
        approvalTtlMillis: Long = 60_000,
        nowMillis: () -> Long = System::currentTimeMillis,
    ): GoffyViewModel {
        val protocolMessageIds = ArrayDeque(
            listOf(
                UUID.fromString("11111111-1111-4111-8111-111111111111"),
                UUID.fromString("33333333-3333-4333-8333-333333333333"),
            ),
        )
        return GoffyViewModel(
            gateway = gateway,
            phoneGateway = phoneGateway,
            codec = GoffyProtocolCodec(
                now = { Instant.parse("2026-07-13T16:00:00Z") },
                nextMessageId = { protocolMessageIds.removeFirst() },
            ),
            allowInsecureLoopback = true,
            defaultEndpoint = endpoint,
            deviceId = "goffy-android-test",
            nextTaskId = { UUID.fromString("22222222-2222-4222-8222-222222222222") },
            approvalTtlMillis = approvalTtlMillis,
            nowMillis = nowMillis,
        )
    }

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
}
