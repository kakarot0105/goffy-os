package dev.goffy.os

import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.protocol.PhoneDeviceInfo

internal enum class GoffyHomeSetupStatus {
    UNKNOWN,
    DEFAULT_HOME,
    AVAILABLE,
    UNAVAILABLE,
}

internal data class GoffyHomeSetupUiModel(
    val status: GoffyHomeSetupStatus,
    val canOpenHomeSettings: Boolean,
    val canCheckHomeStatus: Boolean,
)

internal fun GoffyUiState.toGoffyHomeSetupUiModel(): GoffyHomeSetupUiModel {
    val deviceInfo = latestVerifiedDeviceInfo()
    val status = when {
        deviceInfo == null -> GoffyHomeSetupStatus.UNKNOWN
        deviceInfo.goffyDefaultHome -> GoffyHomeSetupStatus.DEFAULT_HOME
        deviceInfo.goffyHomeCandidate -> GoffyHomeSetupStatus.AVAILABLE
        else -> GoffyHomeSetupStatus.UNAVAILABLE
    }
    return GoffyHomeSetupUiModel(
        status = status,
        canOpenHomeSettings = status != GoffyHomeSetupStatus.UNAVAILABLE,
        canCheckHomeStatus = !isBusy,
    )
}

private fun GoffyUiState.latestVerifiedDeviceInfo(): PhoneDeviceInfo? =
    timeline.entries.asReversed().firstNotNullOfOrNull { entry ->
        if (entry.phase == TaskPhase.VERIFIED) {
            entry.result as? PhoneDeviceInfo
        } else {
            null
        }
    }
