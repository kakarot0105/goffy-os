package dev.goffy.os

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidChargingStateTest {
    @Test
    fun chargingAndFullBatteryStatusesCountAsPoweredDockState() {
        assertTrue(isGoffyChargingStatus(android.os.BatteryManager.BATTERY_STATUS_CHARGING))
        assertTrue(isGoffyChargingStatus(android.os.BatteryManager.BATTERY_STATUS_FULL))
    }

    @Test
    fun unpluggedUnknownOrMissingStatusDoesNotKeepAwake() {
        assertFalse(isGoffyChargingStatus(android.os.BatteryManager.BATTERY_STATUS_DISCHARGING))
        assertFalse(isGoffyChargingStatus(android.os.BatteryManager.BATTERY_STATUS_NOT_CHARGING))
        assertFalse(isGoffyChargingStatus(android.os.BatteryManager.BATTERY_STATUS_UNKNOWN))
        assertFalse(isGoffyChargingStatus(Int.MIN_VALUE))
    }
}
