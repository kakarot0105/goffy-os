package dev.goffy.os.localmodel

import android.content.Context

fun interface LocalModelRuntimeProviderFactory {
    fun create(
        context: Context,
        settingsSource: LocalModelRuntimeSettingsSource,
    ): LocalModelRuntimeProvider
}

interface LocalModelRuntimeProvider {
    val status: LocalModelRuntimeStatus

    suspend fun observeUnsupportedCommand(command: String): LocalModelIntentObservation
}

class GatedLocalModelRuntimeProvider(
    private val gate: LocalModelRuntimeGate,
    private val adapter: GatedLocalModelRuntimeAdapter,
) : LocalModelRuntimeProvider {
    override val status: LocalModelRuntimeStatus
        get() = gate.status

    override suspend fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
        val currentStatus = gate.status
        if (currentStatus.state != LocalModelRuntimeState.READY) {
            return LocalModelIntentObservation.Disabled(currentStatus.summary)
        }
        return adapter.observeUnsupportedCommand(command)
    }
}

object LocalModelRuntimeProviderLoader {
    fun create(
        context: Context,
        settingsSource: LocalModelRuntimeSettingsSource,
    ): LocalModelRuntimeProvider? =
        try {
            val factory = Class.forName(PROVIDER_FACTORY_CLASS)
                .getDeclaredConstructor()
                .newInstance() as? LocalModelRuntimeProviderFactory
            factory?.create(context.applicationContext, settingsSource)
        } catch (_: ClassNotFoundException) {
            null
        } catch (_: ReflectiveOperationException) {
            null
        } catch (_: LinkageError) {
            null
        } catch (_: SecurityException) {
            null
        }

    private const val PROVIDER_FACTORY_CLASS =
        "dev.goffy.os.localmodel.LiteRtLmLocalModelProviderFactory"
}
