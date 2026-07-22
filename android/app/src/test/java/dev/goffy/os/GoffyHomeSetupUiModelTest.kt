package dev.goffy.os

import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.agent.TaskTimelineEvent
import dev.goffy.os.agent.TaskTimelineState
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PhoneDeviceInfo
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyHomeSetupUiModelTest {
    @Test
    fun reportsUnknownUntilVerifiedPhoneInfoExists() {
        val model = GoffyUiState(hubEndpoint = "ws://127.0.0.1:8787/ws/v1")
            .toGoffyHomeSetupUiModel()

        assertEquals(GoffyHomeSetupStatus.UNKNOWN, model.status)
        assertTrue(model.canOpenHomeSettings)
        assertTrue(model.canCheckHomeStatus)
    }

    @Test
    fun ignoresUnverifiedPhoneInfo() {
        val state = stateWithDeviceInfo(
            deviceInfo = deviceInfo(defaultHome = true, homeCandidate = true),
            phase = TaskPhase.COMPLETED_UNVERIFIED,
        )

        val model = state.toGoffyHomeSetupUiModel()

        assertEquals(GoffyHomeSetupStatus.UNKNOWN, model.status)
    }

    @Test
    fun reportsDefaultHomeWhenVerified() {
        val state = stateWithDeviceInfo(
            deviceInfo = deviceInfo(defaultHome = true, homeCandidate = true),
        )

        val model = state.toGoffyHomeSetupUiModel()

        assertEquals(GoffyHomeSetupStatus.DEFAULT_HOME, model.status)
        assertTrue(model.canOpenHomeSettings)
    }

    @Test
    fun reportsAvailableWhenGoffyIsAHomeCandidate() {
        val state = stateWithDeviceInfo(
            deviceInfo = deviceInfo(defaultHome = false, homeCandidate = true),
        )

        val model = state.toGoffyHomeSetupUiModel()

        assertEquals(GoffyHomeSetupStatus.AVAILABLE, model.status)
        assertTrue(model.canOpenHomeSettings)
    }

    @Test
    fun reportsUnavailableWhenHomeIntentIsMissing() {
        val state = stateWithDeviceInfo(
            deviceInfo = deviceInfo(defaultHome = false, homeCandidate = false),
        )

        val model = state.toGoffyHomeSetupUiModel()

        assertEquals(GoffyHomeSetupStatus.UNAVAILABLE, model.status)
        assertFalse(model.canOpenHomeSettings)
    }

    @Test
    fun disablesStatusCheckWhileAnotherTaskIsActive() {
        val activeId = UUID.randomUUID()
        val state = GoffyUiState(
            hubEndpoint = "ws://127.0.0.1:8787/ws/v1",
            timeline = TaskTimelineState(
                activeTaskId = activeId,
                entries = listOf(
                    deviceInfoEntry(
                        deviceInfo = deviceInfo(defaultHome = false, homeCandidate = true),
                        phase = TaskPhase.ROUTING,
                        id = activeId,
                    ),
                ),
            ),
        )

        val model = state.toGoffyHomeSetupUiModel()

        assertFalse(model.canCheckHomeStatus)
    }

    private fun stateWithDeviceInfo(
        deviceInfo: PhoneDeviceInfo,
        phase: TaskPhase = TaskPhase.VERIFIED,
    ): GoffyUiState = GoffyUiState(
        hubEndpoint = "ws://127.0.0.1:8787/ws/v1",
        timeline = TaskTimelineState(entries = listOf(deviceInfoEntry(deviceInfo, phase))),
    )

    private fun deviceInfoEntry(
        deviceInfo: PhoneDeviceInfo,
        phase: TaskPhase,
        id: UUID = UUID.randomUUID(),
    ): TaskTimelineEntry = TaskTimelineEntry(
        id = id,
        command = "Show my phone info",
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_DEVICE_INFO_TOOL,
        phase = phase,
        summary = "Phone info read",
        events = listOf(TaskTimelineEvent(TaskEventKind.VERIFY, "verified")),
        result = deviceInfo,
        permission = PermissionLevel.SAFE,
    )

    private fun deviceInfo(defaultHome: Boolean, homeCandidate: Boolean): PhoneDeviceInfo =
        PhoneDeviceInfo(
            manufacturer = "motorola",
            model = "moto g",
            androidRelease = "15",
            sdkInt = 35,
            goffySystemApp = false,
            goffyHomeCandidate = homeCandidate,
            goffyDefaultHome = defaultHome,
        )
}
