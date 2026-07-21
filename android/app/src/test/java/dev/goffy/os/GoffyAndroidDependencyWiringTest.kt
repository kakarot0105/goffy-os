package dev.goffy.os

import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.localmodel.LocalModelRuntimeState
import dev.goffy.os.protocol.ExecutionTarget
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.TIRAMISU])
@OptIn(ExperimentalCoroutinesApi::class)
class GoffyAndroidDependencyWiringTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setMainDispatcher() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun resetMainDispatcher() {
        Dispatchers.resetMain()
    }

    @Test
    fun androidFactoryUsesMicroIntentFallbackAsNonExecutableHint() {
        val context = RuntimeEnvironment.getApplication() as Context
        val viewModelStore = ViewModelStore()
        MockWebServer().use { server ->
            server.start()
            try {
                val viewModel = ViewModelProvider(
                    viewModelStore,
                    GoffyViewModel.Factory(context),
                )[GoffyViewModel::class.java]

                assertTrue(viewModel.configureHub(endpoint(server), "test-token-12345678901234"))
                viewModel.submitCommand("open my project and run tests")

                val state = viewModel.uiState.value
                val entry = state.timeline.entries.single()
                assertEquals(0, server.requestCount)
                assertEquals(TaskPhase.FAILED, entry.phase)
                assertEquals(ExecutionTarget.PHONE, entry.executionTarget)
                assertNull(entry.toolName)
                assertNull(entry.permission)
                assertNull(entry.result)
                assertTrue(entry.summary.contains("Local model suggested MAC"))
                assertTrue(entry.summary.contains("deterministic route"))
                assertEquals(LocalModelRuntimeState.DISABLED, state.localModelStatus.state)
                assertTrue(state.localModelStatus.summary.contains("micro intent fallback"))
            } finally {
                viewModelStore.clear()
            }
        }
    }

    private fun endpoint(server: MockWebServer): String =
        server.url("/ws/v1").toString().replaceFirst("http://", "ws://")
}
