package dev.goffy.os.localmodel

import java.io.File
import java.io.IOException

enum class LocalModelRuntimeState {
    DISABLED,
    UNAVAILABLE,
    BLOCKED,
    READY,
}

data class LocalModelRuntimeStatus(
    val state: LocalModelRuntimeState,
    val summary: String,
    val enabledByUser: Boolean,
    val runtimeAvailable: Boolean,
    val modelAvailable: Boolean,
    val observeOnly: Boolean = true,
) {
    init {
        require(summary.isSafeLocalModelStatusText()) {
            "local model status summary is not safe bounded text"
        }
    }

    companion object {
        fun disabled(summary: String = "Local model is off; deterministic routing is authoritative.") =
            LocalModelRuntimeStatus(
                state = LocalModelRuntimeState.DISABLED,
                summary = summary,
                enabledByUser = false,
                runtimeAvailable = false,
                modelAvailable = false,
            )
    }
}

data class LocalModelRuntimeGateConfig(
    val enabledByUser: Boolean = false,
    val developerRuntimeAllowed: Boolean = false,
    val runtimeAvailable: Boolean = false,
    val modelRoot: File? = null,
    val modelFile: File? = null,
    val policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(),
)

class LocalModelRuntimeGate(
    private val config: LocalModelRuntimeGateConfig = LocalModelRuntimeGateConfig(),
    private val delegate: LocalModelIntentFallback? = null,
) : LocalModelIntentFallback {
    val status: LocalModelRuntimeStatus
        get() = currentStatus()

    override fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
        val currentStatus = status
        if (currentStatus.state != LocalModelRuntimeState.READY || delegate == null) {
            return LocalModelIntentObservation.Disabled(currentStatus.summary)
        }
        return delegate.observeUnsupportedCommand(command)
    }

    private fun currentStatus(): LocalModelRuntimeStatus =
        try {
            config.toStatus(delegateAvailable = delegate != null)
        } catch (_: SecurityException) {
            config.blockedStatus("Local model path access was blocked by Android security policy.")
        } catch (_: IOException) {
            config.unavailableStatus("Local model path could not be verified.")
        }

    companion object {
        fun goffyLiteDefault(): LocalModelRuntimeGate = LocalModelRuntimeGate()
    }
}

private fun LocalModelRuntimeGateConfig.toStatus(delegateAvailable: Boolean): LocalModelRuntimeStatus {
    if (!enabledByUser) {
        return LocalModelRuntimeStatus.disabled()
    }
    if (!policy.enabled) {
        return disabledStatus("Local model policy is disabled; routing remains deterministic.")
    }
    if (!developerRuntimeAllowed) {
        return blockedStatus("Local model runtime is blocked until production activation is explicitly allowed.")
    }
    if (!runtimeAvailable || !delegateAvailable) {
        return unavailableStatus("Local model runtime provider is not available in this APK.")
    }
    val root = modelRoot?.canonicalFile
        ?: return unavailableStatus("Approved local model directory is unavailable.")
    val file = modelFile?.canonicalFile
        ?: return unavailableStatus("No approved local model file is selected.")
    if (!root.isDirectory) {
        return unavailableStatus("Approved local model directory is unavailable.")
    }
    if (!file.isUnder(root)) {
        return blockedStatus("Local model file is outside the approved app-owned directory.")
    }
    if (!file.name.endsWith(".litertlm")) {
        return blockedStatus("Local model file must be a .litertlm file.")
    }
    if (!file.isFile) {
        return unavailableStatus("Selected local model file is unavailable.")
    }
    if (file.length() !in 1L..policy.maxModelFileBytes) {
        return blockedStatus("Local model file exceeds the GOFFY LITE size budget.")
    }
    return LocalModelRuntimeStatus(
        state = LocalModelRuntimeState.READY,
        summary = "Local model ready for observe-only fallback; deterministic routing remains authoritative.",
        enabledByUser = true,
        runtimeAvailable = true,
        modelAvailable = true,
        observeOnly = true,
    )
}

private fun LocalModelRuntimeGateConfig.unavailableStatus(summary: String) = LocalModelRuntimeStatus(
    state = LocalModelRuntimeState.UNAVAILABLE,
    summary = summary,
    enabledByUser = enabledByUser,
    runtimeAvailable = runtimeAvailable,
    modelAvailable = false,
)

private fun LocalModelRuntimeGateConfig.disabledStatus(summary: String) = LocalModelRuntimeStatus(
    state = LocalModelRuntimeState.DISABLED,
    summary = summary,
    enabledByUser = enabledByUser,
    runtimeAvailable = runtimeAvailable,
    modelAvailable = false,
)

private fun LocalModelRuntimeGateConfig.blockedStatus(summary: String) = LocalModelRuntimeStatus(
    state = LocalModelRuntimeState.BLOCKED,
    summary = summary,
    enabledByUser = enabledByUser,
    runtimeAvailable = runtimeAvailable,
    modelAvailable = false,
)

private fun File.isUnder(root: File): Boolean {
    val canonicalRoot = root.canonicalFile.path.trimEnd(File.separatorChar)
    val canonicalPath = canonicalFile.path
    return canonicalPath.startsWith("$canonicalRoot${File.separator}")
}

private fun String.isSafeLocalModelStatusText(): Boolean =
    isNotBlank() &&
        length <= 160 &&
        none { it.isISOControl() || Character.getType(it) == Character.FORMAT.toInt() }
