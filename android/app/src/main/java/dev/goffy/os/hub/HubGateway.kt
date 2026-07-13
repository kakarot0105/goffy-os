package dev.goffy.os.hub

import dev.goffy.os.protocol.ExecutionEvent
import dev.goffy.os.protocol.ToolInvocationRequest
import kotlinx.coroutines.flow.Flow

interface HubGateway {
    fun invoke(config: HubConfig, request: ToolInvocationRequest): Flow<ExecutionEvent>

    fun close()
}
