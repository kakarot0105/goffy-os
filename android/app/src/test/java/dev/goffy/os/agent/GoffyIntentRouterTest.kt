package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PHONE_NOTE_CREATE_TOOL
import dev.goffy.os.protocol.PhoneNoteCreateArguments
import dev.goffy.os.protocol.PHONE_TIMER_CREATE_TOOL
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoffyIntentRouterTest {
    @Test
    fun routesSupportedMacStatusCommandToOneSafeMacTool() {
        val decision = GoffyIntentRouter.route("  Show   my Mac status. ")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals("mac.system_info", plan.toolName)
        assertEquals(2, plan.successCriteria.size)
    }

    @Test
    fun acceptsCheckVariantWithoutModelReasoning() {
        assertTrue(GoffyIntentRouter.route("check my mac status?") is RoutingDecision.Routed)
    }

    @Test
    fun routesBatteryStatusLocallyWithoutHubAuthority() {
        val decision = GoffyIntentRouter.route("What's my phone battery level?")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(PHONE_BATTERY_STATUS_TOOL, plan.toolName)
    }

    @Test
    fun routesPrivacyMinimizedDeviceInfoLocally() {
        val decision = GoffyIntentRouter.route("What phone is this?")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(PHONE_DEVICE_INFO_TOOL, plan.toolName)
        assertTrue(GoffyIntentRouter.route("show my device details") is RoutingDecision.Routed)
    }

    @Test
    fun rejectsAdditionalInstructionsInsteadOfTurningThemIntoAuthority() {
        val decision = GoffyIntentRouter.route("show my mac status; then delete files")

        assertTrue(decision is RoutingDecision.Unsupported)
        assertTrue(
            GoffyIntentRouter.route("show my battery status and open settings") is RoutingDecision.Unsupported,
        )
        assertTrue(
            GoffyIntentRouter.route("show my phone info and include its serial") is RoutingDecision.Unsupported,
        )
    }

    @Test
    fun rejectsBlankAndUnrelatedCommandsLocally() {
        assertTrue(GoffyIntentRouter.route("   ") is RoutingDecision.Unsupported)
        assertTrue(GoffyIntentRouter.route("open Terminal") is RoutingDecision.Unsupported)
    }

    @Test
    fun routesExactNoteTextToOneConfirmPhoneTool() {
        val decision = GoffyIntentRouter.route("Create a note saying Buy milk; then delete files")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
        assertEquals(PermissionLevel.CONFIRM, plan.permission)
        assertEquals(PHONE_NOTE_CREATE_TOOL, plan.toolName)
        assertEquals(
            PhoneNoteCreateArguments("Buy milk; then delete files"),
            plan.arguments,
        )
    }

    @Test
    fun rejectsEmptyOversizedOrSpoofableNoteText() {
        assertTrue(GoffyIntentRouter.route("Create a note saying   ") is RoutingDecision.Unsupported)
        assertTrue(
            GoffyIntentRouter.route("Create a note saying ${"x".repeat(2_001)}") is
                RoutingDecision.Unsupported,
        )
        assertTrue(
            GoffyIntentRouter.route("Create a note saying safe\u202Eevil") is
                RoutingDecision.Unsupported,
        )
        assertTrue(
            GoffyIntentRouter.route("Create a note saying first\nsecond") is
                RoutingDecision.Unsupported,
        )
    }

    @Test
    fun routesBoundedTimerDurationsToOneConfirmPhoneTool() {
        val cases = mapOf(
            "Set a timer for 1 second" to 1,
            "start me a timer for 5 minutes!" to 300,
            "Create a timer for 24 hours" to 86_400,
        )

        cases.forEach { (command, expectedSeconds) ->
            val decision = GoffyIntentRouter.route(command)
            assertTrue(decision is RoutingDecision.Routed)
            val plan = (decision as RoutingDecision.Routed).plan
            assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
            assertEquals(PermissionLevel.CONFIRM, plan.permission)
            assertEquals(PHONE_TIMER_CREATE_TOOL, plan.toolName)
            assertEquals(PhoneTimerCreateArguments(expectedSeconds, skipClockUi = true), plan.arguments)
        }
    }

    @Test
    fun rejectsInvalidCompoundOverflowingOrExpandedTimerAuthority() {
        val rejected = listOf(
            "Set a timer for 0 seconds",
            "Set a timer for 25 hours",
            "Set a timer for 1441 minutes",
            "Set a timer for 5 minutes and turn on the camera",
            "Set a timer for 1 hour 30 minutes",
            "Set a timer for 999999999999999999999999 minutes",
        )

        rejected.forEach { command ->
            assertTrue(GoffyIntentRouter.route(command) is RoutingDecision.Unsupported)
        }
    }

    @Test
    fun routesExactFlashlightStateToOneConfirmPhoneTool() {
        val cases = mapOf(
            "Turn on the flashlight" to true,
            "turn the torch off." to false,
            "Switch flashlight on!" to true,
            "switch off the torch?" to false,
        )

        cases.forEach { (command, enabled) ->
            val decision = GoffyIntentRouter.route(command)
            assertTrue(decision is RoutingDecision.Routed)
            val plan = (decision as RoutingDecision.Routed).plan
            assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
            assertEquals(PermissionLevel.CONFIRM, plan.permission)
            assertEquals(PHONE_FLASHLIGHT_SET_TOOL, plan.toolName)
            assertEquals(PhoneFlashlightSetArguments(enabled), plan.arguments)
        }
    }

    @Test
    fun rejectsAmbiguousOrExpandedFlashlightAuthority() {
        val rejected = listOf(
            "Turn on the flashlight and take a picture",
            "Toggle the flashlight",
            "Turn the flashlight maybe on",
            "Turn on every camera light",
        )

        rejected.forEach { command ->
            assertTrue(GoffyIntentRouter.route(command) is RoutingDecision.Unsupported)
        }
    }
}
