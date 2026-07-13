package dev.goffy.os.phone

import android.os.Build
import dev.goffy.os.protocol.PhoneDeviceInfo

class AndroidDeviceInfoSource internal constructor(
    private val manufacturer: () -> String = { Build.MANUFACTURER },
    private val model: () -> String = { Build.MODEL },
    private val androidRelease: () -> String = { Build.VERSION.RELEASE },
    private val sdkInt: () -> Int = { Build.VERSION.SDK_INT },
) : DeviceInfoSource {
    override suspend fun read(): PhoneDeviceInfo = PhoneDeviceInfo(
        manufacturer = manufacturer(),
        model = model(),
        androidRelease = androidRelease(),
        sdkInt = sdkInt(),
    )
}
