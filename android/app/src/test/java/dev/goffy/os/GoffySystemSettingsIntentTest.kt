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
        assertTrue(
            trusted.copy(packageName = "com.google.android.permissioncontroller")
                .isTrustedSystemSettingsHandler(),
        )
        assertTrue(
            trusted.copy(packageName = "com.android.permissioncontroller")
                .isTrustedSystemSettingsHandler(),
        )
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
        registerSettingsHandler(action = Settings.ACTION_SETTINGS, packageName = "com.example.settings")

        val intent = application.packageManager.resolveTrustedSystemSettingsIntent()

        assertNull(intent)
    }

    @Test
    fun resolvesExactExplicitHomeSettingsIntentWhenAvailable() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(
            action = Settings.ACTION_HOME_SETTINGS,
            packageName = "com.google.android.permissioncontroller",
            activityName = "com.android.permissioncontroller.role.ui.HomeSettingsActivity",
        )

        val intent = application.packageManager.resolveTrustedHomeSettingsIntent()

        requireNotNull(intent)

        assertEquals(Settings.ACTION_HOME_SETTINGS, intent.action)
        assertEquals("com.google.android.permissioncontroller", intent.component?.packageName)
        assertEquals(
            "com.android.permissioncontroller.role.ui.HomeSettingsActivity",
            intent.component?.className,
        )
        assertNull(intent.getPackage())
        assertNull(intent.data)
        assertTrue(intent.categories.isNullOrEmpty())
        assertTrue(intent.flags and Intent.FLAG_ACTIVITY_NEW_TASK != 0)
    }

    @Test
    fun resolvesAospPermissionControllerHomeSettingsIntent() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(
            action = Settings.ACTION_HOME_SETTINGS,
            packageName = "com.android.permissioncontroller",
            activityName = "com.android.permissioncontroller.role.ui.HomeSettingsActivity",
        )

        val intent = application.packageManager.resolveTrustedHomeSettingsIntent()

        requireNotNull(intent)

        assertEquals(Settings.ACTION_HOME_SETTINGS, intent.action)
        assertEquals("com.android.permissioncontroller", intent.component?.packageName)
        assertEquals(
            "com.android.permissioncontroller.role.ui.HomeSettingsActivity",
            intent.component?.className,
        )
    }

    @Test
    fun homeSettingsFallsBackToDefaultAppsSettingsBeforeTopLevelSettings() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(
            action = Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS,
            packageName = "com.android.permissioncontroller",
            activityName = "com.android.permissioncontroller.role.ui.DefaultAppListActivity",
        )
        registerSettingsHandler(action = Settings.ACTION_SETTINGS, packageName = "com.android.settings")

        val intent = application.packageManager.resolveTrustedHomeSettingsIntent()

        requireNotNull(intent)

        assertEquals(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS, intent.action)
        assertEquals("com.android.permissioncontroller", intent.component?.packageName)
    }

    @Test
    fun homeSettingsRejectsUntrustedHandlersBeforeFallback() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(action = Settings.ACTION_HOME_SETTINGS, packageName = "com.example.settings")
        registerSettingsHandler(action = Settings.ACTION_SETTINGS, packageName = "com.android.settings")

        val intent = application.packageManager.resolveTrustedHomeSettingsIntent()

        requireNotNull(intent)

        assertEquals(Settings.ACTION_SETTINGS, intent.action)
        assertEquals("com.android.settings", intent.component?.packageName)
    }

    private fun assertExactExplicitSystemSettingsIntent() {
        val application = RuntimeEnvironment.getApplication()
        registerSettingsHandler(action = Settings.ACTION_SETTINGS, packageName = "com.android.settings")

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
    private fun registerSettingsHandler(
        action: String,
        packageName: String,
        activityName: String = ".Settings",
    ) {
        val applicationInfo = ApplicationInfo().apply {
            this.packageName = packageName
            flags = ApplicationInfo.FLAG_SYSTEM
        }
        val activityInfo = ActivityInfo().apply {
            this.packageName = packageName
            name = activityName
            enabled = true
            exported = true
            this.applicationInfo = applicationInfo
        }
        val resolveInfo = ResolveInfo().apply {
            this.activityInfo = activityInfo
        }
        shadowOf(RuntimeEnvironment.getApplication().packageManager).setResolveInfosForIntent(
            Intent(action),
            listOf(resolveInfo),
        )
    }
}
