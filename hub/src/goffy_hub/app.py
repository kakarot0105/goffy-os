from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from goffy_hub.auth import SAFE_TOOL_SCOPE, CredentialAuthenticator
from goffy_hub.connections import WebSocketConnectionRegistry
from goffy_hub.credentials import CredentialStore
from goffy_hub.identity import HubIdentityStore
from goffy_hub.mcp_server import build_mcp_runtime
from goffy_hub.operator_audit import OperatorAuditLog
from goffy_hub.operator_audit_api import build_operator_audit_router
from goffy_hub.pairing import PairingService
from goffy_hub.pairing_api import build_pairing_router
from goffy_hub.registry import (
    ToolArgumentsError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)
from goffy_hub.settings import HubSettings
from goffy_hub.tool_health import ToolHealthMonitor
from goffy_hub.tools import (
    build_git_status_tool,
    build_mac_apps_list_tool,
    build_mac_apps_open_tool,
    build_mac_clipboard_read_tool,
    build_mac_files_largest_tool,
    build_mac_files_list_tool,
    build_mac_processes_list_tool,
    build_mac_system_tool,
)
from goffy_hub.tools.mac_processes import is_mac_processes_supported
from goffy_protocol import (
    MCP_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    CapabilityDiscoveryRequestPayload,
    CapabilityDiscoveryResponsePayload,
    MessageEnvelope,
    MessageType,
    PermissionLevel,
    ToolErrorPayload,
    ToolInvocationPayload,
    ToolProgressPayload,
    ToolResultPayload,
    VerificationResultPayload,
    build_envelope,
)

LOGGER = logging.getLogger(__name__)
SendEvent = Callable[[MessageType, BaseModel, UUID | None], Awaitable[bool]]
MAX_MESSAGES_PER_CONNECTION = 64
WEBSOCKET_TOOL_PERMISSIONS = frozenset({PermissionLevel.SAFE})


class HealthResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    status: str
    protocol_version: str
    tool_access: str
    healthy_tool_count: int
    unavailable_tool_count: int
    tool_registry_revision: int


def build_registry(settings: HubSettings) -> ToolRegistry:
    confirm_tool_names = frozenset({"mac.apps.open"} if settings.mac_app_open_enabled else ())
    registry = ToolRegistry(confirm_tool_names=confirm_tool_names)
    registry.register(
        build_mac_system_tool(
            settings.tool_timeout_seconds,
            settings.tool_health_timeout_seconds,
        )
    )
    if is_mac_processes_supported():
        registry.register(
            build_mac_processes_list_tool(
                settings.tool_timeout_seconds,
                settings.tool_health_timeout_seconds,
            )
        )
    if settings.mac_files_roots:
        registry.register(
            build_mac_files_list_tool(
                settings.mac_files_roots,
                settings.tool_timeout_seconds,
                settings.tool_health_timeout_seconds,
            )
        )
        registry.register(
            build_mac_files_largest_tool(
                settings.mac_files_roots,
                settings.tool_timeout_seconds,
                settings.tool_health_timeout_seconds,
            )
        )
    if settings.git_repo_roots:
        registry.register(
            build_git_status_tool(
                settings.git_repo_roots,
                settings.tool_timeout_seconds,
                settings.tool_health_timeout_seconds,
            )
        )
    if settings.mac_app_allowlist:
        registry.register(
            build_mac_apps_list_tool(
                settings.mac_app_allowlist,
                settings.tool_timeout_seconds,
                settings.tool_health_timeout_seconds,
            )
        )
        if settings.mac_app_open_enabled:
            registry.register(
                build_mac_apps_open_tool(
                    settings.mac_app_allowlist,
                    settings.tool_timeout_seconds,
                    settings.tool_health_timeout_seconds,
                )
            )
    if settings.mac_clipboard_read_enabled:
        registry.register(
            build_mac_clipboard_read_tool(
                settings.tool_timeout_seconds,
                settings.tool_health_timeout_seconds,
            )
        )
    return registry


def create_app(
    settings: HubSettings | None = None,
    *,
    registry: ToolRegistry | None = None,
) -> FastAPI:
    resolved_settings = settings or HubSettings.from_environment()
    registry = registry or build_registry(resolved_settings)
    registry.seal()
    credential_store = (
        CredentialStore(resolved_settings.pairing_database_path)
        if resolved_settings.pairing_database_path is not None
        else None
    )
    hub_identity_path = resolved_settings.resolved_hub_identity_path
    hub_identity_store = (
        HubIdentityStore(hub_identity_path) if hub_identity_path is not None else None
    )
    hub_identity = hub_identity_store.load_or_create() if hub_identity_store is not None else None
    authenticator = CredentialAuthenticator(resolved_settings, credential_store)
    operator_audit_log = OperatorAuditLog(
        max_events=resolved_settings.operator_audit_max_events,
        database_path=resolved_settings.resolved_operator_audit_path,
    )
    pairing_service = (
        PairingService(
            credential_store,
            challenge_ttl_seconds=resolved_settings.pairing_challenge_ttl_seconds,
        )
        if credential_store is not None
        else None
    )
    websocket_connections = WebSocketConnectionRegistry()
    mcp_runtime = build_mcp_runtime(
        resolved_settings,
        registry,
        authenticator,
        audit_log=operator_audit_log,
    )
    tool_health_monitor = ToolHealthMonitor(
        registry,
        interval_seconds=resolved_settings.tool_health_interval_seconds,
        on_change=mcp_runtime.notify_tool_list_changed,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await tool_health_monitor.initialize()
        async with mcp_runtime.session_manager.run():
            monitor_task = asyncio.create_task(tool_health_monitor.run())
            try:
                yield
            finally:
                monitor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor_task

    app = FastAPI(title="GOFFY Hub", version="0.2.0", docs_url="/docs", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.registry = registry
    app.state.mcp_runtime = mcp_runtime
    app.state.tool_health_monitor = tool_health_monitor
    app.state.authenticator = authenticator
    app.state.operator_audit_log = operator_audit_log
    app.state.credential_store = credential_store
    app.state.hub_identity_store = hub_identity_store
    app.state.hub_identity = hub_identity
    app.state.pairing_service = pairing_service
    app.state.websocket_connections = websocket_connections

    app.include_router(build_operator_audit_router(authenticator, operator_audit_log))

    if pairing_service is not None:
        if hub_identity is None:
            raise RuntimeError("paired mode requires a Hub identity")

        async def revoke_live_access(credential_id: UUID) -> None:
            await asyncio.gather(
                websocket_connections.revoke(credential_id),
                mcp_runtime.revoke_credential(credential_id),
            )

        app.include_router(
            build_pairing_router(
                authenticator,
                pairing_service,
                hub_identity,
                on_revoke=revoke_live_access,
                audit_log=operator_audit_log,
            )
        )

    @app.get("/health", response_model=HealthResponse, response_model_by_alias=True)
    async def health() -> HealthResponse:
        tool_health = registry.health_report()
        healthy_tool_count = len(tool_health.available_tool_names)
        total_tool_count = len(tool_health.tools)
        return HealthResponse(
            status="ok" if healthy_tool_count == total_tool_count else "degraded",
            protocol_version=PROTOCOL_VERSION,
            tool_access="enabled" if await authenticator.tool_access_enabled() else "disabled",
            healthy_tool_count=healthy_tool_count,
            unavailable_tool_count=total_tool_count - healthy_tool_count,
            tool_registry_revision=tool_health.revision,
        )

    @app.websocket("/ws/v1")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        principal = await authenticator.authenticate_header(websocket.headers.get("authorization"))
        if principal is None:
            operator_audit_log.record(
                source="websocket",
                action="connect",
                outcome="rejected",
                principal_kind="none",
                detail_code="auth",
            )
            await websocket.close(code=4401, reason="authentication required")
            return
        if not principal.has_scope(SAFE_TOOL_SCOPE):
            operator_audit_log.record(
                source="websocket",
                action="connect",
                outcome="rejected",
                principal_kind=principal.kind.value,
                credential_id=principal.credential_id,
                detail_code="scope",
            )
            await websocket.close(code=4403, reason="insufficient scope")
            return

        await websocket.accept()
        operator_audit_log.record(
            source="websocket",
            action="connect",
            outcome="succeeded",
            principal_kind=principal.kind.value,
            credential_id=principal.credential_id,
        )
        credential_id = principal.credential_id
        if credential_id is not None:
            await websocket_connections.register(credential_id, websocket)
            if not await authenticator.is_active(principal):
                operator_audit_log.record(
                    source="websocket",
                    action="connect",
                    outcome="rejected",
                    principal_kind=principal.kind.value,
                    credential_id=principal.credential_id,
                    detail_code="revoked",
                )
                await websocket_connections.unregister(credential_id, websocket)
                await websocket.close(code=4403, reason="credential revoked")
                return
        discovered_tools: set[str] = set()
        seen_message_ids: set[UUID] = set()
        outbound_closed = False

        async def send_event(
            message_type: MessageType, payload: BaseModel, correlation_id: UUID | None
        ) -> bool:
            nonlocal outbound_closed
            event = build_envelope(
                message_type=message_type,
                payload=payload,
                correlation_id=correlation_id,
            )
            encoded = event.model_dump_json(by_alias=True)
            if len(encoded.encode("utf-8")) > resolved_settings.max_message_bytes:
                outbound_closed = True
                await websocket.close(code=1009, reason="outbound message too large")
                return False
            await websocket.send_text(encoded)
            return True

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
                await _handle_message(
                    raw_message,
                    registry,
                    discovered_tools,
                    seen_message_ids,
                    send_event,
                )
                if outbound_closed:
                    return
        except WebSocketDisconnect:
            return
        finally:
            if credential_id is not None:
                await websocket_connections.unregister(credential_id, websocket)

    # The terminal mount preserves the exact /mcp path without Starlette's slash redirect.
    app.mount("/", mcp_runtime.application, name="mcp")
    return app


async def _handle_message(
    raw_message: str,
    registry: ToolRegistry,
    discovered_tools: set[str],
    seen_message_ids: set[UUID],
    send_event: SendEvent,
) -> None:
    try:
        envelope = MessageEnvelope.model_validate_json(raw_message)
    except ValidationError:
        discovered_tools.clear()
        await _send_error(
            send_event,
            code="invalid_message",
            message="Message does not match the supported protocol.",
            correlation_id=None,
        )
        return

    if envelope.message_id in seen_message_ids:
        discovered_tools.clear()
        await _send_error(
            send_event,
            code="duplicate_message",
            message="Message ID has already been used on this connection.",
            correlation_id=envelope.message_id,
        )
        return
    if len(seen_message_ids) >= MAX_MESSAGES_PER_CONNECTION:
        discovered_tools.clear()
        await _send_error(
            send_event,
            code="connection_message_limit",
            message="Connection message limit reached.",
            correlation_id=envelope.message_id,
        )
        return
    seen_message_ids.add(envelope.message_id)

    if envelope.message_type is MessageType.CAPABILITY_DISCOVERY_REQUEST:
        discovered_tools.clear()
        try:
            discovery_request = CapabilityDiscoveryRequestPayload.model_validate(envelope.payload)
        except ValidationError:
            await _send_error(
                send_event,
                code="invalid_capability_discovery",
                message="Capability discovery payload is invalid.",
                correlation_id=envelope.message_id,
            )
            return

        tools = registry.discover(
            discovery_request.tool_name,
            permissions=WEBSOCKET_TOOL_PERMISSIONS,
        )
        if tools:
            discovered_tools.add(tools[0].name)
        await send_event(
            MessageType.CAPABILITY_DISCOVERY_RESPONSE,
            CapabilityDiscoveryResponsePayload(
                mcp_protocol_version=MCP_PROTOCOL_VERSION,
                list_changed=False,
                tools=tools,
            ),
            envelope.message_id,
        )
        return

    if envelope.message_type is not MessageType.TOOL_INVOCATION:
        discovered_tools.clear()
        await _send_error(
            send_event,
            code="unsupported_message_type",
            message=(
                "This Hub endpoint accepts capability discovery and tool invocation messages only."
            ),
            correlation_id=envelope.message_id,
        )
        return

    invocation_capabilities = frozenset(discovered_tools)
    discovered_tools.clear()
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

    if invocation.tool_name not in invocation_capabilities:
        await _send_error(
            send_event,
            code="capability_discovery_required",
            message="Capability discovery must succeed before invoking this tool.",
            correlation_id=envelope.message_id,
        )
        return

    try:
        prepared = registry.preflight(invocation.tool_name, invocation.arguments)
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
    if prepared.definition.permission not in WEBSOCKET_TOOL_PERMISSIONS:
        await _send_error(
            send_event,
            code="tool_not_found",
            message="The requested tool is unavailable or unauthorized.",
            correlation_id=envelope.message_id,
        )
        return

    if not await send_event(
        MessageType.TOOL_PROGRESS,
        ToolProgressPayload(
            tool_name=invocation.tool_name,
            execution_target=prepared.definition.execution_target,
            stage="accepted",
            sequence=0,
            message="Invocation accepted by the Hub.",
        ),
        envelope.message_id,
    ):
        return

    try:
        result = await registry.invoke_prepared(prepared)
    except ToolExecutionError:
        LOGGER.exception("Tool execution failed for %s", invocation.tool_name)
        await _send_error(
            send_event,
            code="tool_execution_failed",
            message="The tool failed without a verified state change.",
            correlation_id=envelope.message_id,
        )
        return

    if not await send_event(
        MessageType.TOOL_PROGRESS,
        ToolProgressPayload(
            tool_name=invocation.tool_name,
            execution_target=result.definition.execution_target,
            stage="completed",
            sequence=1,
            message="Tool returned schema-valid structured output.",
        ),
        envelope.message_id,
    ):
        return
    if not await send_event(
        MessageType.TOOL_RESULT,
        ToolResultPayload(
            tool_name=invocation.tool_name,
            execution_target=result.definition.execution_target,
            structured_content=result.structured_content,
        ),
        envelope.message_id,
    ):
        return
    await send_event(
        MessageType.VERIFICATION_RESULT,
        VerificationResultPayload(
            succeeded=True,
            summary=f"{result.definition.name} output matched the registered schema.",
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
