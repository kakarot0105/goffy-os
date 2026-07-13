from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from goffy_hub.auth import is_authorized
from goffy_hub.registry import (
    ToolArgumentsError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)
from goffy_hub.settings import HubSettings
from goffy_hub.tools import build_mac_system_tool
from goffy_protocol import (
    PROTOCOL_VERSION,
    ExecutionTarget,
    MessageEnvelope,
    MessageType,
    ToolErrorPayload,
    ToolInvocationPayload,
    ToolProgressPayload,
    ToolResultPayload,
    VerificationResultPayload,
    build_envelope,
)

LOGGER = logging.getLogger(__name__)
SendEvent = Callable[[MessageType, BaseModel, UUID | None], Awaitable[None]]


class HealthResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    status: str
    protocol_version: str
    tool_access: str


def build_registry(settings: HubSettings) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(build_mac_system_tool(settings.tool_timeout_seconds))
    return registry


def create_app(settings: HubSettings | None = None) -> FastAPI:
    resolved_settings = settings or HubSettings.from_environment()
    registry = build_registry(resolved_settings)
    app = FastAPI(title="GOFFY Hub", version="0.1.0", docs_url="/docs")
    app.state.settings = resolved_settings
    app.state.registry = registry

    @app.get("/health", response_model=HealthResponse, response_model_by_alias=True)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            protocol_version=PROTOCOL_VERSION,
            tool_access="enabled" if resolved_settings.auth_token else "disabled",
        )

    @app.websocket("/ws/v1")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        if not is_authorized(websocket.headers.get("authorization"), resolved_settings):
            await websocket.close(code=4401, reason="authentication required")
            return

        await websocket.accept()

        async def send_event(
            message_type: MessageType, payload: BaseModel, correlation_id: UUID | None
        ) -> None:
            event = build_envelope(
                message_type=message_type,
                payload=payload,
                correlation_id=correlation_id,
            )
            await websocket.send_text(event.model_dump_json(by_alias=True))

        try:
            while True:
                raw_message = await websocket.receive_text()
                if len(raw_message.encode("utf-8")) > resolved_settings.max_message_bytes:
                    await _send_error(
                        send_event,
                        code="message_too_large",
                        message="Message exceeds the configured size limit.",
                        correlation_id=None,
                    )
                    await websocket.close(code=1009, reason="message too large")
                    return
                await _handle_message(raw_message, registry, send_event)
        except WebSocketDisconnect:
            return

    return app


async def _handle_message(raw_message: str, registry: ToolRegistry, send_event: SendEvent) -> None:
    try:
        envelope = MessageEnvelope.model_validate_json(raw_message)
    except ValidationError:
        await _send_error(
            send_event,
            code="invalid_message",
            message="Message does not match the supported protocol.",
            correlation_id=None,
        )
        return

    if envelope.message_type is not MessageType.TOOL_INVOCATION:
        await _send_error(
            send_event,
            code="unsupported_message_type",
            message="This Hub endpoint accepts ToolInvocation messages only.",
            correlation_id=envelope.message_id,
        )
        return

    try:
        invocation = ToolInvocationPayload.model_validate(envelope.payload)
    except ValidationError:
        await _send_error(
            send_event,
            code="invalid_tool_arguments",
            message="Tool invocation payload is invalid.",
            correlation_id=envelope.message_id,
        )
        return

    await send_event(
        MessageType.TOOL_PROGRESS,
        ToolProgressPayload(
            tool_name=invocation.tool_name,
            execution_target=ExecutionTarget.MAC,
            stage="accepted",
            sequence=0,
            message="Invocation accepted by the Hub.",
        ),
        envelope.message_id,
    )

    try:
        result = await registry.invoke(invocation.tool_name, invocation.arguments)
    except ToolNotFoundError:
        await _send_error(
            send_event,
            code="tool_not_found",
            message="The requested tool is unavailable or unauthorized.",
            correlation_id=envelope.message_id,
        )
        return
    except ToolArgumentsError:
        await _send_error(
            send_event,
            code="invalid_tool_arguments",
            message="Arguments do not match the tool schema.",
            correlation_id=envelope.message_id,
        )
        return
    except ToolExecutionError:
        LOGGER.exception("Tool execution failed for %s", invocation.tool_name)
        await _send_error(
            send_event,
            code="tool_execution_failed",
            message="The tool failed without a verified state change.",
            correlation_id=envelope.message_id,
        )
        return

    await send_event(
        MessageType.TOOL_PROGRESS,
        ToolProgressPayload(
            tool_name=invocation.tool_name,
            execution_target=result.definition.execution_target,
            stage="completed",
            sequence=1,
            message="Tool returned schema-valid structured output.",
        ),
        envelope.message_id,
    )
    await send_event(
        MessageType.TOOL_RESULT,
        ToolResultPayload(
            tool_name=invocation.tool_name,
            execution_target=result.definition.execution_target,
            structured_content=result.structured_content,
        ),
        envelope.message_id,
    )
    await send_event(
        MessageType.VERIFICATION_RESULT,
        VerificationResultPayload(
            succeeded=True,
            summary="System information output matched the registered schema.",
            checks=["tool allowlist", "input schema", "output schema"],
        ),
        envelope.message_id,
    )


async def _send_error(
    send_event: SendEvent,
    *,
    code: str,
    message: str,
    correlation_id: UUID | None,
) -> None:
    await send_event(
        MessageType.TOOL_ERROR,
        ToolErrorPayload(code=code, message=message, retryable=False),
        correlation_id,
    )
