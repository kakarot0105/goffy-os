package dev.goffy.os.agent

import dev.goffy.os.protocol.ExecutionTarget
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
    fun rejectsAdditionalInstructionsInsteadOfTurningThemIntoAuthority() {
        val decision = GoffyIntentRouter.route("show my mac status; then delete files")

        assertTrue(decision is RoutingDecision.Unsupported)
    }

    @Test
    fun rejectsBlankAndUnrelatedCommandsLocally() {
        assertTrue(GoffyIntentRouter.route("   ") is RoutingDecision.Unsupported)
        assertTrue(GoffyIntentRouter.route("open Terminal") is RoutingDecision.Unsupported)
    }
}
