package dev.goffy.os.localmodel

import android.content.Context

fun interface LocalModelRuntimeProviderFactory {
    fun create(context: Context): LocalModelRuntimeProvider
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
