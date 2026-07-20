package dev.goffy.os.localmodel

import android.content.Context
import android.os.Build
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.O])
class AndroidLocalModelRuntimeSettingsStoreTest {
    private lateinit var context: Context

    @Before
    fun clearSettings() {
        context = RuntimeEnvironment.getApplication()
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }

    @Test
    fun savePersistsOnlyTheVerifiedUserEnabledFlag() {
        val store = AndroidLocalModelRuntimeSettingsStore(context)

        assertEquals(
            LocalModelRuntimeSettingsLoadResult.Loaded(LocalModelRuntimeSettings()),
            store.load(),
        )
        assertEquals(
            LocalModelRuntimeSettingsSaveResult.Saved(LocalModelRuntimeSettings(enabledByUser = true)),
            store.save(LocalModelRuntimeSettings(enabledByUser = true)),
        )

        val reloaded = AndroidLocalModelRuntimeSettingsStore(context).load()

        assertEquals(
            LocalModelRuntimeSettingsLoadResult.Loaded(LocalModelRuntimeSettings(enabledByUser = true)),
            reloaded,
        )
        assertEquals(
            LocalModelRuntimeSettingsSaveResult.Saved(LocalModelRuntimeSettings(enabledByUser = false)),
            store.save(LocalModelRuntimeSettings(enabledByUser = false)),
        )
        assertEquals(
            LocalModelRuntimeSettingsLoadResult.Loaded(LocalModelRuntimeSettings(enabledByUser = false)),
            AndroidLocalModelRuntimeSettingsStore(context).load(),
        )
    }

    @Test
    fun providerLoaderFailsClosedWhenModelDebugClassIsAbsent() {
        val provider = LocalModelRuntimeProviderLoader.create(
            context,
            MutableLocalModelRuntimeSettingsSource(),
        )

        assertNull(provider)
    }

    private companion object {
        const val PREFERENCES_NAME = "goffy_local_model_runtime"
    }
}
