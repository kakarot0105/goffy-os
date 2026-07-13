package dev.goffy.os.hub

import dev.goffy.os.protocol.HubStreamEvent
import dev.goffy.os.protocol.ToolInvocationRequest
import kotlinx.coroutines.flow.Flow

interface HubGateway {
    fun invoke(config: HubConfig, request: ToolInvocationRequest): Flow<HubStreamEvent>

    fun close()
}
