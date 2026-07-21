package dev.goffy.os

import android.content.Intent
import android.os.BatteryManager

internal fun Intent?.isGoffyCharging(): Boolean {
    val status = this?.getIntExtra(
        BatteryManager.EXTRA_STATUS,
        BatteryManager.BATTERY_STATUS_UNKNOWN,
    ) ?: BatteryManager.BATTERY_STATUS_UNKNOWN
    return isGoffyChargingStatus(status)
}

internal fun isGoffyChargingStatus(status: Int): Boolean {
    return status == BatteryManager.BATTERY_STATUS_CHARGING ||
        status == BatteryManager.BATTERY_STATUS_FULL
}
