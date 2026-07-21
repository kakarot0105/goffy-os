package dev.goffy.os.phone

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import dev.goffy.os.protocol.PhoneDeviceInfo

class AndroidDeviceInfoSource internal constructor(
    private val context: Context? = null,
    private val manufacturer: () -> String = { Build.MANUFACTURER },
    private val model: () -> String = { Build.MODEL },
    private val androidRelease: () -> String = { Build.VERSION.RELEASE },
    private val sdkInt: () -> Int = { Build.VERSION.SDK_INT },
    private val goffySystemApp: () -> Boolean = { context?.isGoffySystemApp() ?: false },
    private val goffyHomeCandidate: () -> Boolean = { context?.isGoffyHomeCandidate() ?: false },
    private val goffyDefaultHome: () -> Boolean = { context?.isGoffyDefaultHome() ?: false },
) : DeviceInfoSource {
    override suspend fun read(): PhoneDeviceInfo = PhoneDeviceInfo(
        manufacturer = manufacturer(),
        model = model(),
        androidRelease = androidRelease(),
        sdkInt = sdkInt(),
        goffySystemApp = goffySystemApp(),
        goffyHomeCandidate = goffyHomeCandidate(),
        goffyDefaultHome = goffyDefaultHome(),
    )
}

private fun Context.isGoffySystemApp(): Boolean {
    val flags = applicationInfo.flags
    return flags.hasFlag(ApplicationInfo.FLAG_SYSTEM) ||
        flags.hasFlag(ApplicationInfo.FLAG_UPDATED_SYSTEM_APP)
}

private fun Context.isGoffyHomeCandidate(): Boolean {
    val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
    return packageManager.queryHomeActivities(intent).any { resolveInfo ->
        resolveInfo.activityInfo?.packageName == packageName
    }
}

private fun Context.isGoffyDefaultHome(): Boolean {
    val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
    val resolveInfo = packageManager.resolveHomeActivity(intent)
    return resolveInfo?.activityInfo?.packageName == packageName
}

private fun PackageManager.queryHomeActivities(intent: Intent) =
    if (Build.VERSION.SDK_INT >= 33) {
        queryIntentActivities(
            intent,
            PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_DEFAULT_ONLY.toLong()),
        )
    } else {
        @Suppress("DEPRECATION")
        queryIntentActivities(intent, PackageManager.MATCH_DEFAULT_ONLY)
    }

private fun PackageManager.resolveHomeActivity(intent: Intent) =
    if (Build.VERSION.SDK_INT >= 33) {
        resolveActivity(
            intent,
            PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_DEFAULT_ONLY.toLong()),
        )
    } else {
        @Suppress("DEPRECATION")
        resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
    }

private fun Int.hasFlag(flag: Int): Boolean = this and flag != 0
