package dev.goffy.os

import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.ApplicationInfo
import android.content.pm.ResolveInfo
import android.os.Build
import android.provider.Settings
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.TIRAMISU])
class GoffySystemSettingsIntentTest {
    @Test
    fun trustsOnlyEnabledExportedSystemSettingsHandlers() {
        val trusted = SystemSettingsHandlerDescriptor(
            packageName = "com.android.settings",
            enabled = true,
            exported = true,
            systemApplication = true,
        )

        assertTrue(trusted.isTrustedSystemSettingsHandler())
        assertFalse(trusted.copy(packageName = "com.example.settings").isTrustedSystemSettingsHandler())
        assertFalse(trusted.copy(systemApplication = false).isTrustedSystemSettingsHandler())
        assertFalse(trusted.copy(enabled = false).isTrustedSystemSettingsHandler())
        assertFalse(trusted.copy(exported = false).isTrustedSystemSettingsHandler())
    }

    @Test
    @Config(sdk = [Build.VERSION_CODES.O])
    fun resolvesExactExplicitSystemSettingsIntentOnApi26() {
        assertExactExplicitSystemSettingsIntent()
    }

    @Test
    @Config(sdk = [Build.VERSION_CODES.TIRAMISU])
    fun resolvesExactExplicitSystemSettingsIntentOnApi33() {
        assertExactExplicitSystemSettingsIntent()
    }

    @Test
    fun rejectsUntrustedSystemSettingsHandler() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(packageName = "com.example.settings")

        val intent = application.packageManager.resolveTrustedSystemSettingsIntent()

        assertNull(intent)
    }

    private fun assertExactExplicitSystemSettingsIntent() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(packageName = "com.android.settings")

        val intent = application.packageManager.resolveTrustedSystemSettingsIntent()

        requireNotNull(intent)

        assertEquals(Settings.ACTION_SETTINGS, intent.action)
        assertEquals("com.android.settings", intent.component?.packageName)
        assertEquals("com.android.settings.Settings", intent.component?.className)
        assertNull(intent.getPackage())
        assertNull(intent.data)
        assertTrue(intent.categories.isNullOrEmpty())
        assertTrue(intent.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
    }

    @Suppress("DEPRECATION")
    private fun registerSettingsHandler(packageName: String) {
        val applicationInfo = ApplicationInfo().apply {
            this.packageName = packageName
            flags = ApplicationInfo.FLAG_SYSTEM
        }
        val activityInfo = ActivityInfo().apply {
            this.packageName = packageName
            name = ".Settings"
            enabled = true
            exported = true
            this.applicationInfo = applicationInfo
        }
        val resolveInfo = ResolveInfo().apply {
            this.activityInfo = activityInfo
        }
        shadowOf(RuntimeEnvironment.getApplication().packageManager).setResolveInfosForIntent(
            Intent(Settings.ACTION_SETTINGS),
            listOf(resolveInfo),
        )
    }
}
