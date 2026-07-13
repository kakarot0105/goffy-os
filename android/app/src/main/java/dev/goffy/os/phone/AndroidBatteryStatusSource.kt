package dev.goffy.os.phone

import android.content.Context
import android.os.BatteryManager
import dev.goffy.os.protocol.PhoneBatteryStatus

class AndroidBatteryStatusSource(context: Context) : BatteryStatusSource {
    private val batteryManager = checkNotNull(
        context.applicationContext.getSystemService(BatteryManager::class.java),
    ) { "BatteryManager is unavailable" }

    override suspend fun read(): PhoneBatteryStatus {
        val level = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        if (level == Int.MIN_VALUE) {
            throw IllegalStateException("Battery capacity is unsupported")
        }
        return PhoneBatteryStatus(
            levelPercent = level,
            charging = batteryManager.isCharging,
        )
    }
}
