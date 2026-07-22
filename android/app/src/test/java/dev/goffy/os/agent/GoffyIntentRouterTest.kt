package dev.goffy.os.agent

import dev.goffy.os.localmodel.LocalModelIntentCandidate
import dev.goffy.os.localmodel.LocalModelIntentFallback
import dev.goffy.os.localmodel.LocalModelIntentObservation
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GIT_STATUS_TOOL
import dev.goffy.os.protocol.GitStatusArguments
import dev.goffy.os.protocol.GOFFY_ROM_STATUS_TOOL
import dev.goffy.os.protocol.MAC_APPS_LIST_TOOL
import dev.goffy.os.protocol.MAC_APPS_OPEN_TOOL
import dev.goffy.os.protocol.MAC_CLIPBOARD_READ_TOOL
import dev.goffy.os.protocol.MAC_FILES_LARGEST_TOOL
import dev.goffy.os.protocol.MAC_FILES_LIST_TOOL
import dev.goffy.os.protocol.MAC_PROCESSES_LIST_TOOL
import dev.goffy.os.protocol.MacAppsListArguments
import dev.goffy.os.protocol.MacAppsOpenArguments
import dev.goffy.os.protocol.MacFilesLargestArguments
import dev.goffy.os.protocol.MacFilesListArguments
import dev.goffy.os.protocol.MacProcessesListArguments
import dev.goffy.os.protocol.PermissionLevel
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_DEVICE_INFO_TOOL
import dev.goffy.os.protocol.PHONE_FLASHLIGHT_SET_TOOL
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PHONE_MEMORY_FORGET_TOOL
import dev.goffy.os.protocol.PhoneMemoryForgetArguments
import dev.goffy.os.protocol.PHONE_MEMORY_LIST_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_REMEMBER_TOOL
import dev.goffy.os.protocol.PhoneMemoryRememberArguments
import dev.goffy.os.protocol.PHONE_MEMORY_UPDATE_TOOL
import dev.goffy.os.protocol.PhoneMemoryUpdateArguments
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
    fun routesGoffyRomStatusToSafeMacTool() {
        val decision = GoffyIntentRouter.route("What are we building now can you explain?")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(GOFFY_ROM_STATUS_TOOL, plan.toolName)
        assertEquals(3, plan.successCriteria.size)
        assertTrue(GoffyIntentRouter.route("Show GOFFY ROM status") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("Is the ROM ready?") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("Explain GOFFY OS status") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("Show OS status") is RoutingDecision.Unsupported)
    }

    @Test
    fun acceptsCheckVariantWithoutModelReasoning() {
        assertTrue(GoffyIntentRouter.route("check my mac status?") is RoutingDecision.Routed)
    }

    @Test
    fun routesMacFileListingToSafeMacTool() {
        val decision = GoffyIntentRouter.route("List my Mac files")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(MAC_FILES_LIST_TOOL, plan.toolName)
        assertEquals(MacFilesListArguments(rootIndex = 0), plan.arguments)
        assertEquals(3, plan.successCriteria.size)
    }

    @Test
    fun routesLargestMacFilesToSafeMacTool() {
        val decision = GoffyIntentRouter.route("Find the largest files on my Mac")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(MAC_FILES_LARGEST_TOOL, plan.toolName)
        assertEquals(MacFilesLargestArguments(rootIndex = 0), plan.arguments)
        assertEquals(3, plan.successCriteria.size)
        assertTrue(GoffyIntentRouter.route("Show me largest files on my Mac") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("list the largest files on my mac?") is RoutingDecision.Routed)
    }

    @Test
    fun routesMacProcessListToSafeMacTool() {
        val decision = GoffyIntentRouter.route("What's running on my Mac")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(MAC_PROCESSES_LIST_TOOL, plan.toolName)
        assertEquals(MacProcessesListArguments(), plan.arguments)
        assertEquals(3, plan.successCriteria.size)
        assertTrue(GoffyIntentRouter.route("what is running on my mac?") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("Show my Mac processes") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("check me my mac processes") is RoutingDecision.Routed)
    }

    @Test
    fun routesMacAppCatalogToSafeMacTool() {
        val decision = GoffyIntentRouter.route("List my Mac apps")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(MAC_APPS_LIST_TOOL, plan.toolName)
        assertEquals(MacAppsListArguments(), plan.arguments)
        assertEquals(3, plan.successCriteria.size)
        assertTrue(GoffyIntentRouter.route("show my mac applications") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("what apps are approved on my mac?") is RoutingDecision.Routed)
    }

    @Test
    fun routesMacAppOpenToConfirmMacTool() {
        val decision = GoffyIntentRouter.route("Open Safari on my Mac")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.CONFIRM, plan.permission)
        assertEquals(MAC_APPS_OPEN_TOOL, plan.toolName)
        assertEquals(MacAppsOpenArguments("Safari"), plan.arguments)
        assertEquals(4, plan.successCriteria.size)
        assertTrue(GoffyIntentRouter.route("launch Terminal on my mac?") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("open Safari and delete files on my mac") is RoutingDecision.Unsupported)
    }

    @Test
    fun routesGitStatusToSafeMacTool() {
        val decision = GoffyIntentRouter.route("Check my git status")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(GIT_STATUS_TOOL, plan.toolName)
        assertEquals(GitStatusArguments(repoIndex = 0), plan.arguments)
        assertEquals(3, plan.successCriteria.size)
    }

    @Test
    fun routesMacClipboardReadToSafeMacTool() {
        val decision = GoffyIntentRouter.route("Read my Mac clipboard")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.MAC, plan.executionTarget)
        assertEquals(PermissionLevel.SAFE, plan.permission)
        assertEquals(MAC_CLIPBOARD_READ_TOOL, plan.toolName)
        assertEquals(3, plan.successCriteria.size)
        assertTrue(GoffyIntentRouter.route("Show my Mac clipboard") is RoutingDecision.Routed)
        assertTrue(GoffyIntentRouter.route("show me my mac clipboard") is RoutingDecision.Unsupported)
        assertTrue(GoffyIntentRouter.route("read my mac clipboard?") is RoutingDecision.Unsupported)
    }

    @Test
    fun deterministicRoutesDoNotConsultLocalModelFallback() {
        val throwingFallback = LocalModelIntentFallback {
            error("deterministic routes must not consult the local model")
        }

        assertTrue(
            GoffyIntentRouter.route(
                "show my battery status",
                localModelFallback = throwingFallback,
            ) is RoutingDecision.Routed,
        )
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
    fun unsafeCommandsNeverReachLocalModelFallback() {
        val throwingFallback = LocalModelIntentFallback {
            error("unsafe commands must not become model prompts")
        }

        val rejected = listOf(
            "   ",
            "open settings\u202E",
            "open settings\u2066",
            "open\u200Bsettings",
            "explain ${"x".repeat(600)}",
            "update memory #7 to first\nsecond",
        )

        rejected.forEach { command ->
            val decision = GoffyIntentRouter.route(command, localModelFallback = throwingFallback)
            assertTrue(decision is RoutingDecision.Unsupported)
            val observation = (decision as RoutingDecision.Unsupported).localModelObservation
            assertTrue(observation is LocalModelIntentObservation.Rejected)
        }
    }

    @Test
    fun localModelCandidateRemainsNonExecutable() {
        val fallback = LocalModelIntentFallback { command ->
            LocalModelIntentObservation.Candidate(
                LocalModelIntentCandidate(
                    intentLabel = "open_settings",
                    confidence = 0.91f,
                    normalizedCommand = command,
                    rationale = "The user appears to want settings.",
                ),
            )
        }

        val decision = GoffyIntentRouter.route("open settings", localModelFallback = fallback)

        assertTrue(decision is RoutingDecision.Unsupported)
        val unsupported = decision as RoutingDecision.Unsupported
        assertEquals("open settings", unsupported.normalizedCommand)
        assertTrue(unsupported.localModelObservation is LocalModelIntentObservation.Candidate)
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
    fun routesMemoryListPhrasesToOneSafePhoneTool() {
        val cases = listOf(
            "what do you remember",
            "Show my memories",
            "list my memories",
        )

        cases.forEach { command ->
            val decision = GoffyIntentRouter.route(command)
            assertTrue(decision is RoutingDecision.Routed)
            val plan = (decision as RoutingDecision.Routed).plan
            assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
            assertEquals(PermissionLevel.SAFE, plan.permission)
            assertEquals(PHONE_MEMORY_LIST_TOOL, plan.toolName)
        }
    }

    @Test
    fun routesBoundedMemoryRememberToOneConfirmPhoneTool() {
        val decision = GoffyIntentRouter.route("remember that goffy memory smoke test")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
        assertEquals(PermissionLevel.CONFIRM, plan.permission)
        assertEquals(PHONE_MEMORY_REMEMBER_TOOL, plan.toolName)
        assertEquals(PhoneMemoryRememberArguments("goffy memory smoke test"), plan.arguments)
    }

    @Test
    fun routesExactMemoryDeleteToOneConfirmPhoneTool() {
        val cases = listOf("delete memory #7", "Forget local memory 7.")

        cases.forEach { command ->
            val decision = GoffyIntentRouter.route(command)
            assertTrue(decision is RoutingDecision.Routed)
            val plan = (decision as RoutingDecision.Routed).plan
            assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
            assertEquals(PermissionLevel.CONFIRM, plan.permission)
            assertEquals(PHONE_MEMORY_FORGET_TOOL, plan.toolName)
            assertEquals(PhoneMemoryForgetArguments(7), plan.arguments)
        }
    }

    @Test
    fun routesExactMemoryUpdateToOneConfirmPhoneTool() {
        val decision = GoffyIntentRouter.route("update memory #7 to favorite project is GOFFY")

        assertTrue(decision is RoutingDecision.Routed)
        val plan = (decision as RoutingDecision.Routed).plan
        assertEquals(ExecutionTarget.PHONE, plan.executionTarget)
        assertEquals(PermissionLevel.CONFIRM, plan.permission)
        assertEquals(PHONE_MEMORY_UPDATE_TOOL, plan.toolName)
        assertEquals(PhoneMemoryUpdateArguments(7, "favorite project is GOFFY"), plan.arguments)
    }

    @Test
    fun rejectsInvalidMemoryMutationAuthority() {
        val rejected = listOf(
            "delete memory #0",
            "delete memory #7 and clear all memories",
            "update memory #0 to safe text",
            "update memory #7 to ",
            "update memory #7 to safe\u202Eevil",
            "update memory #7 to first\nsecond",
        )

        rejected.forEach { command ->
            assertTrue(GoffyIntentRouter.route(command) is RoutingDecision.Unsupported)
        }
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
