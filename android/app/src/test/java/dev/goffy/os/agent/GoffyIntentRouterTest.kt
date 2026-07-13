package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
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
}
