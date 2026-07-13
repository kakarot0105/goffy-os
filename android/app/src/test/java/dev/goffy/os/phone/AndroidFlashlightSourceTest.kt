package dev.goffy.os.phone

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadow.api.Shadow
import org.robolectric.shadows.ShadowCameraCharacteristics

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.O, Build.VERSION_CODES.TIRAMISU])
class AndroidFlashlightSourceTest {
    @Test
    fun changesStateOnlyAfterCallbackAndAlwaysUnregisters() = runTest {
        val backend = FakeTorchBackend(initialEnabled = false)

        val result = AndroidFlashlightSource(backend).set(PhoneFlashlightSetArguments(true))

        assertEquals(listOf(true), backend.setRequests)
        assertEquals(1, backend.registerCalls)
        assertEquals(1, backend.unregisterCalls)
        assertTrue(result.enabled)
        assertTrue(result.stateChanged)
    }

    @Test
    fun alreadyRequestedStateIsCallbackVerifiedWithoutSetCall() = runTest {
        val backend = FakeTorchBackend(initialEnabled = false)

        val result = AndroidFlashlightSource(backend).set(PhoneFlashlightSetArguments(false))

        assertTrue(backend.setRequests.isEmpty())
        assertFalse(result.enabled)
        assertFalse(result.stateChanged)
        assertEquals(1, backend.unregisterCalls)
    }

    @Test
    fun unavailableTorchFailsAndUnregisters() = runTest {
        val backend = FakeTorchBackend(initialEnabled = null, unavailableOnRegister = true)

        val failure = runCatching {
            AndroidFlashlightSource(backend).set(PhoneFlashlightSetArguments(true))
        }.exceptionOrNull()

        assertTrue(failure is IllegalStateException)
        assertEquals(1, backend.unregisterCalls)
    }

    @Test
    fun setTorchFailureUnregistersCallback() = runTest {
        val backend = FakeTorchBackend(
            initialEnabled = false,
            setFailure = IllegalStateException("camera is busy"),
        )

        val failure = runCatching {
            AndroidFlashlightSource(backend).set(PhoneFlashlightSetArguments(true))
        }.exceptionOrNull()

        assertTrue(failure is IllegalStateException)
        assertEquals(1, backend.registerCalls)
        assertEquals(1, backend.unregisterCalls)
    }

    @Test
    fun cancellationUnregistersPendingCallback() = runTest {
        val backend = FakeTorchBackend(initialEnabled = null)
        val operation = launch(start = CoroutineStart.UNDISPATCHED) {
            AndroidFlashlightSource(backend).set(PhoneFlashlightSetArguments(true))
        }

        operation.cancelAndJoin()

        assertEquals(1, backend.registerCalls)
        assertEquals(1, backend.unregisterCalls)
    }

    @Test
    fun rejectsDevicesWithoutABackFacingFlashBeforeRegistration() = runTest {
        val backend = FakeTorchBackend(initialEnabled = false, hasBackFlash = false)

        val failure = runCatching {
            AndroidFlashlightSource(backend).set(PhoneFlashlightSetArguments(true))
        }.exceptionOrNull()

        assertTrue(failure is IllegalStateException)
        assertEquals(0, backend.registerCalls)
    }

    @Test
    fun cameraSelectionPrefersLogicalBackFlashThenStableIdOrder() {
        val candidates = listOf(
            TorchCameraCandidate("front", backFacing = false, hasFlash = true, logicalCamera = true),
            TorchCameraCandidate("9", backFacing = true, hasFlash = true, logicalCamera = false),
            TorchCameraCandidate("2", backFacing = true, hasFlash = true, logicalCamera = true),
            TorchCameraCandidate("1", backFacing = true, hasFlash = true, logicalCamera = true),
        )

        assertEquals("1", candidates.selectPreferredBackFlashCamera())
    }

    @Test
    fun androidBackendSelectsBackFlashAndForwardsTorchCallbacks() {
        val application = RuntimeEnvironment.getApplication()
        val cameraManager = application.getSystemService(CameraManager::class.java)
        val shadowCameraManager = shadowOf(cameraManager)
        shadowCameraManager.addCamera(
            "front",
            cameraCharacteristics(CameraCharacteristics.LENS_FACING_FRONT, hasFlash = true),
        )
        shadowCameraManager.addCamera(
            "back",
            cameraCharacteristics(CameraCharacteristics.LENS_FACING_BACK, hasFlash = true),
        )
        val backend = AndroidCameraTorchBackend(
            cameraManager,
            Handler(Looper.getMainLooper()),
        )
        val states = mutableListOf<Boolean>()
        val callback = object : TorchStateCallback {
            override fun onChanged(cameraId: String, enabled: Boolean) {
                if (cameraId == "back") states += enabled
            }

            override fun onUnavailable(cameraId: String) = Unit
        }

        assertEquals("back", backend.findBackFlashCamera())
        backend.register(callback)
        backend.setTorch("back", true)
        shadowOf(Looper.getMainLooper()).idle()
        backend.unregister(callback)

        assertTrue(shadowCameraManager.getTorchMode("back"))
        assertTrue(states.contains(true))
    }

    private fun cameraCharacteristics(lensFacing: Int, hasFlash: Boolean): CameraCharacteristics {
        val characteristics = ShadowCameraCharacteristics.newCameraCharacteristics()
        val shadow = Shadow.extract<ShadowCameraCharacteristics>(characteristics)
        shadow.set(CameraCharacteristics.LENS_FACING, lensFacing)
        shadow.set(CameraCharacteristics.FLASH_INFO_AVAILABLE, hasFlash)
        return characteristics
    }

    private class FakeTorchBackend(
        private val initialEnabled: Boolean?,
        private val unavailableOnRegister: Boolean = false,
        private val hasBackFlash: Boolean = true,
        private val setFailure: RuntimeException? = null,
    ) : TorchBackend {
        var registerCalls = 0
        var unregisterCalls = 0
        val setRequests = mutableListOf<Boolean>()
        private var callback: TorchStateCallback? = null

        override fun findBackFlashCamera(): String? = if (hasBackFlash) "back" else null

        override fun register(callback: TorchStateCallback) {
            registerCalls += 1
            this.callback = callback
            if (unavailableOnRegister) {
                callback.onUnavailable("back")
            } else if (initialEnabled != null) {
                callback.onChanged("back", initialEnabled)
            }
        }

        override fun unregister(callback: TorchStateCallback) {
            assertEquals(this.callback, callback)
            unregisterCalls += 1
            this.callback = null
        }

        override fun setTorch(cameraId: String, enabled: Boolean) {
            assertEquals("back", cameraId)
            setFailure?.let { throw it }
            setRequests += enabled
            callback?.onChanged(cameraId, enabled)
        }
    }
}
