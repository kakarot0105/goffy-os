package dev.goffy.os.phone

import android.app.Application
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.ApplicationInfo
import android.content.pm.ResolveInfo
import android.os.Build
import android.provider.AlarmClock
import dev.goffy.os.protocol.ANDROID_SET_TIMER_ACTION
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.PhoneTimerDispatched
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

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.TIRAMISU])
class AndroidSystemTimerSourceTest {
    @Test
    fun trustsOnlyEnabledExportedSystemClockHandlers() {
        val trusted = TimerHandlerDescriptor(
            packageName = "com.google.android.deskclock",
            enabled = true,
            exported = true,
            systemApplication = true,
        )

        assertTrue(trusted.isTrustedSystemTimerHandler())
        assertFalse(trusted.copy(packageName = "android").isTrustedSystemTimerHandler())
        assertFalse(trusted.copy(packageName = "com.example.clock").isTrustedSystemTimerHandler())
        assertFalse(trusted.copy(systemApplication = false).isTrustedSystemTimerHandler())
        assertFalse(trusted.copy(enabled = false).isTrustedSystemTimerHandler())
        assertFalse(trusted.copy(exported = false).isTrustedSystemTimerHandler())
    }

    @Test
    @Config(sdk = [Build.VERSION_CODES.O])
    fun dispatchesExactExplicitTimerIntentOnApi26() = runTest {
        assertExactDispatch()
    }

    @Test
    @Config(sdk = [Build.VERSION_CODES.TIRAMISU])
    fun dispatchesExactExplicitTimerIntentOnApi33() = runTest {
        assertExactDispatch()
    }

    @Test
    @Config(sdk = [Build.VERSION_CODES.TIRAMISU])
    fun rejectsUntrustedResolvedHandlerBeforeDispatch() = runTest {
        val application = RuntimeEnvironment.getApplication()
        registerTimerHandler(application, packageName = "com.example.clock")

        val failure = runCatching {
            AndroidSystemTimerSource(application).create(PhoneTimerCreateArguments(60, true))
        }.exceptionOrNull()

        assertTrue(failure is IllegalStateException)
        assertEquals(null, shadowOf(application).nextStartedActivity)
    }

    private suspend fun assertExactDispatch() {
        val application = RuntimeEnvironment.getApplication()
        registerTimerHandler(application, packageName = "com.google.android.deskclock")

        val result = AndroidSystemTimerSource(application).create(
            PhoneTimerCreateArguments(durationSeconds = 300, skipClockUi = true),
        )
        val launched = requireNotNull(shadowOf(application).nextStartedActivity)

        assertEquals(AlarmClock.ACTION_SET_TIMER, launched.action)
        assertEquals("com.google.android.deskclock", launched.component?.packageName)
        assertEquals(
            "com.google.android.deskclock.TimerActivity",
            launched.component?.className,
        )
        assertEquals(300, launched.getIntExtra(AlarmClock.EXTRA_LENGTH, -1))
        assertTrue(launched.getBooleanExtra(AlarmClock.EXTRA_SKIP_UI, false))
        assertFalse(launched.hasExtra(AlarmClock.EXTRA_MESSAGE))
        assertTrue(launched.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
        assertEquals(
            PhoneTimerDispatched(
                durationSeconds = 300,
                clockPackage = "com.google.android.deskclock",
                clockActivity = "com.google.android.deskclock.TimerActivity",
                systemApplication = true,
                skipClockUiRequested = true,
                systemAction = ANDROID_SET_TIMER_ACTION,
            ),
            result,
        )
    }

    private fun registerTimerHandler(application: Application, packageName: String) {
        val applicationInfo = ApplicationInfo().apply {
            this.packageName = packageName
            flags = ApplicationInfo.FLAG_SYSTEM
        }
        val activityInfo = ActivityInfo().apply {
            this.packageName = packageName
            name = ".TimerActivity"
            enabled = true
            exported = true
            this.applicationInfo = applicationInfo
        }
        val resolveInfo = ResolveInfo().apply {
            this.activityInfo = activityInfo
        }
        shadowOf(application.packageManager).setResolveInfosForIntent(
            Intent(AlarmClock.ACTION_SET_TIMER),
            listOf(resolveInfo),
        )
    }
}
