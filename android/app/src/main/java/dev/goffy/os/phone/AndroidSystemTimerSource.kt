package dev.goffy.os.phone

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.pm.ResolveInfo
import android.os.Build
import android.provider.AlarmClock
import dev.goffy.os.protocol.ANDROID_SET_TIMER_ACTION
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.PhoneTimerCreateArguments
import dev.goffy.os.protocol.isAllowlistedSystemClockPackage
import dev.goffy.os.protocol.matchesToolContract

class AndroidSystemTimerSource(context: Context) : TimerSource {
    private val applicationContext = context.applicationContext

    override suspend fun create(arguments: PhoneTimerCreateArguments): PhoneTimerDispatched {
        require(arguments.matchesToolContract()) {
            "timer duration does not match the local contract"
        }
        val implicitIntent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, arguments.durationSeconds)
            putExtra(AlarmClock.EXTRA_SKIP_UI, arguments.skipClockUi)
        }
        val handler = applicationContext.packageManager.resolveTimerHandler(implicitIntent)
            ?: error("no allowlisted system Clock handler is available")
        val activity = handler.activityInfo
        val className = if (activity.name.startsWith('.')) {
            activity.packageName + activity.name
        } else {
            activity.name
        }
        val explicitIntent = Intent(implicitIntent).apply {
            component = ComponentName(activity.packageName, className)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        applicationContext.startActivity(explicitIntent)
        return PhoneTimerDispatched(
            durationSeconds = arguments.durationSeconds,
            clockPackage = activity.packageName,
            clockActivity = className,
            systemApplication = true,
            skipClockUiRequested = arguments.skipClockUi,
            systemAction = ANDROID_SET_TIMER_ACTION,
        )
    }

    @Suppress("DEPRECATION")
    private fun PackageManager.resolveTimerHandler(intent: Intent): ResolveInfo? {
        val resolved = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            resolveActivity(
                intent,
                PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_DEFAULT_ONLY.toLong()),
            )
        } else {
            resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
        } ?: return null
        val activity = resolved.activityInfo ?: return null
        val systemFlags = ApplicationInfo.FLAG_SYSTEM or ApplicationInfo.FLAG_UPDATED_SYSTEM_APP
        val descriptor = TimerHandlerDescriptor(
            packageName = activity.packageName,
            enabled = activity.enabled,
            exported = activity.exported,
            systemApplication = activity.applicationInfo.flags and systemFlags != 0,
        )
        return resolved.takeIf { descriptor.isTrustedSystemTimerHandler() }
    }

}

internal data class TimerHandlerDescriptor(
    val packageName: String,
    val enabled: Boolean,
    val exported: Boolean,
    val systemApplication: Boolean,
)

internal fun TimerHandlerDescriptor.isTrustedSystemTimerHandler(): Boolean =
    packageName.isAllowlistedSystemClockPackage() &&
        enabled &&
        exported &&
        systemApplication
