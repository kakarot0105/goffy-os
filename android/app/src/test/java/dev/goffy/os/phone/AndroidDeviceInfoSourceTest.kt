package dev.goffy.os.phone

import dev.goffy.os.protocol.PhoneDeviceInfo
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class AndroidDeviceInfoSourceTest {
    @Test
    fun mapsOnlyTheApprovedDisplayFields() = runTest {
        val source = AndroidDeviceInfoSource(
            manufacturer = { "motorola" },
            model = { "moto g" },
            androidRelease = { "15" },
            sdkInt = { 35 },
            goffySystemApp = { true },
            goffyHomeCandidate = { true },
            goffyDefaultHome = { false },
        )

        assertEquals(
            PhoneDeviceInfo(
                manufacturer = "motorola",
                model = "moto g",
                androidRelease = "15",
                sdkInt = 35,
                goffySystemApp = true,
                goffyHomeCandidate = true,
                goffyDefaultHome = false,
            ),
            source.read(),
        )
    }
}
