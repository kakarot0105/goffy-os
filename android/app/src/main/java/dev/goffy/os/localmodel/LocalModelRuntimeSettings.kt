package dev.goffy.os.localmodel

import android.content.Context
import android.content.SharedPreferences
import java.util.concurrent.atomic.AtomicReference

data class LocalModelRuntimeSettings(
    val enabledByUser: Boolean = false,
)

fun interface LocalModelRuntimeSettingsSource {
    fun snapshot(): LocalModelRuntimeSettings
}

class MutableLocalModelRuntimeSettingsSource(
    initialSettings: LocalModelRuntimeSettings = LocalModelRuntimeSettings(),
) : LocalModelRuntimeSettingsSource {
    private val current = AtomicReference(initialSettings)

    override fun snapshot(): LocalModelRuntimeSettings = current.get()

    fun update(settings: LocalModelRuntimeSettings) {
        current.set(settings)
    }
}

interface LocalModelRuntimeSettingsStore {
    fun load(): LocalModelRuntimeSettingsLoadResult

    fun save(settings: LocalModelRuntimeSettings): LocalModelRuntimeSettingsSaveResult
}

sealed interface LocalModelRuntimeSettingsLoadResult {
    data class Loaded(val settings: LocalModelRuntimeSettings) : LocalModelRuntimeSettingsLoadResult

    data object Unavailable : LocalModelRuntimeSettingsLoadResult
}

sealed interface LocalModelRuntimeSettingsSaveResult {
    data class Saved(val settings: LocalModelRuntimeSettings) : LocalModelRuntimeSettingsSaveResult

    data object Failed : LocalModelRuntimeSettingsSaveResult
}

class AndroidLocalModelRuntimeSettingsStore(context: Context) : LocalModelRuntimeSettingsStore {
    private val preferences: SharedPreferences = context.applicationContext.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )

    override fun load(): LocalModelRuntimeSettingsLoadResult =
        try {
            LocalModelRuntimeSettingsLoadResult.Loaded(
                LocalModelRuntimeSettings(
                    enabledByUser = preferences.getBoolean(KEY_ENABLED_BY_USER, false),
                ),
            )
        } catch (_: ClassCastException) {
            LocalModelRuntimeSettingsLoadResult.Unavailable
        } catch (_: SecurityException) {
            LocalModelRuntimeSettingsLoadResult.Unavailable
        }

    override fun save(settings: LocalModelRuntimeSettings): LocalModelRuntimeSettingsSaveResult =
        try {
            val committed = preferences.edit()
                .putBoolean(KEY_ENABLED_BY_USER, settings.enabledByUser)
                .commit()
            if (!committed) {
                LocalModelRuntimeSettingsSaveResult.Failed
            } else {
                val verified = preferences.getBoolean(KEY_ENABLED_BY_USER, !settings.enabledByUser)
                if (verified == settings.enabledByUser) {
                    LocalModelRuntimeSettingsSaveResult.Saved(settings)
                } else {
                    LocalModelRuntimeSettingsSaveResult.Failed
                }
            }
        } catch (_: ClassCastException) {
            LocalModelRuntimeSettingsSaveResult.Failed
        } catch (_: SecurityException) {
            LocalModelRuntimeSettingsSaveResult.Failed
        }

    private companion object {
        const val PREFERENCES_NAME = "goffy_local_model_runtime"
        const val KEY_ENABLED_BY_USER = "enabled_by_user"
    }
}
