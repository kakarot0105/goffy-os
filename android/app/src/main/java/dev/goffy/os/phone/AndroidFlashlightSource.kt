package dev.goffy.os.phone

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import dev.goffy.os.protocol.PhoneFlashlightSetArguments
import dev.goffy.os.protocol.PhoneFlashlightState
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CompletableDeferred

class AndroidFlashlightSource internal constructor(
    private val backend: TorchBackend,
) : FlashlightSource {
    constructor(context: Context) : this(
        AndroidCameraTorchBackend(
            cameraManager = context.applicationContext.getSystemService(CameraManager::class.java),
            callbackHandler = Handler(Looper.getMainLooper()),
        ),
    )

    override suspend fun set(arguments: PhoneFlashlightSetArguments): PhoneFlashlightState {
        val cameraId = backend.findBackFlashCamera()
            ?: error("no back-facing camera flash is available")
        return backend.setAndVerifyTorch(cameraId, arguments.enabled)
    }
}

internal interface TorchBackend {
    fun findBackFlashCamera(): String?

    fun register(callback: TorchStateCallback)

    fun unregister(callback: TorchStateCallback)

    fun setTorch(cameraId: String, enabled: Boolean)
}

internal interface TorchStateCallback {
    fun onChanged(cameraId: String, enabled: Boolean)

    fun onUnavailable(cameraId: String)
}

internal class AndroidCameraTorchBackend(
    private val cameraManager: CameraManager,
    private val callbackHandler: Handler,
) : TorchBackend {
    private val callbacks = mutableMapOf<TorchStateCallback, CameraManager.TorchCallback>()

    override fun findBackFlashCamera(): String? = cameraManager.cameraIdList
        .map { cameraId ->
            val characteristics = cameraManager.getCameraCharacteristics(cameraId)
            TorchCameraCandidate(
                cameraId = cameraId,
                backFacing = characteristics.get(CameraCharacteristics.LENS_FACING) ==
                    CameraCharacteristics.LENS_FACING_BACK,
                hasFlash = characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true,
                logicalCamera = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
                    characteristics.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)
                        ?.contains(
                            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA,
                        ) == true,
            )
        }
        .selectPreferredBackFlashCamera()

    override fun register(callback: TorchStateCallback) {
        check(callback !in callbacks) { "torch callback is already registered" }
        val androidCallback = object : CameraManager.TorchCallback() {
            override fun onTorchModeChanged(cameraId: String, enabled: Boolean) {
                callback.onChanged(cameraId, enabled)
            }

            override fun onTorchModeUnavailable(cameraId: String) {
                callback.onUnavailable(cameraId)
            }
        }
        callbacks[callback] = androidCallback
        try {
            cameraManager.registerTorchCallback(androidCallback, callbackHandler)
        } catch (error: Exception) {
            callbacks.remove(callback)
            throw error
        }
    }

    override fun unregister(callback: TorchStateCallback) {
        callbacks.remove(callback)?.let(cameraManager::unregisterTorchCallback)
    }

    override fun setTorch(cameraId: String, enabled: Boolean) {
        cameraManager.setTorchMode(cameraId, enabled)
    }
}

private suspend fun TorchBackend.setAndVerifyTorch(
    targetCameraId: String,
    requestedEnabled: Boolean,
): PhoneFlashlightState {
    val result = CompletableDeferred<PhoneFlashlightState>()
    val initialStateObserved = AtomicBoolean(false)
    val stateChangeRequested = AtomicBoolean(false)
    val callback = object : TorchStateCallback {
        override fun onChanged(cameraId: String, enabled: Boolean) {
            if (cameraId != targetCameraId || result.isCompleted) return
            if (initialStateObserved.compareAndSet(false, true)) {
                if (enabled == requestedEnabled) {
                    result.complete(verifiedFlashlightState(enabled, stateChanged = false))
                } else {
                    stateChangeRequested.set(true)
                    try {
                        setTorch(targetCameraId, requestedEnabled)
                    } catch (error: Exception) {
                        result.completeExceptionally(error)
                    }
                }
            } else if (stateChangeRequested.get() && enabled == requestedEnabled) {
                result.complete(verifiedFlashlightState(enabled, stateChanged = true))
            }
        }

        override fun onUnavailable(cameraId: String) {
            if (cameraId == targetCameraId) {
                result.completeExceptionally(IllegalStateException("back-camera torch is unavailable"))
            }
        }
    }

    var registered = false
    try {
        register(callback)
        registered = true
        return result.await()
    } finally {
        if (registered) unregister(callback)
    }
}

private fun verifiedFlashlightState(enabled: Boolean, stateChanged: Boolean) = PhoneFlashlightState(
    enabled = enabled,
    stateChanged = stateChanged,
)

internal data class TorchCameraCandidate(
    val cameraId: String,
    val backFacing: Boolean,
    val hasFlash: Boolean,
    val logicalCamera: Boolean,
)

internal fun List<TorchCameraCandidate>.selectPreferredBackFlashCamera(): String? =
    asSequence()
        .filter { it.backFacing && it.hasFlash }
        .sortedWith(compareByDescending<TorchCameraCandidate> { it.logicalCamera }.thenBy { it.cameraId })
        .firstOrNull()
        ?.cameraId
