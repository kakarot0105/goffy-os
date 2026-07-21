package dev.goffy.os

enum class DockAwakeStatus {
    AWAKE,
    WAITING_FOR_POWER,
    DISABLED,
}

object GoffyDockAwakePolicy {
    fun status(enabled: Boolean, charging: Boolean): DockAwakeStatus = when {
        !enabled -> DockAwakeStatus.DISABLED
        charging -> DockAwakeStatus.AWAKE
        else -> DockAwakeStatus.WAITING_FOR_POWER
    }

    fun shouldKeepScreenAwake(enabled: Boolean, charging: Boolean): Boolean =
        status(enabled, charging) == DockAwakeStatus.AWAKE
}
