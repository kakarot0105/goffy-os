from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable, Collection
from contextlib import suppress
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any, cast
from uuid import UUID
from weakref import WeakValueDictionary

import anyio
from mcp import types
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import (
    AuthenticatedUser,
    BearerAuthBackend,
    RequireAuthMiddleware,
    authorization_context,
)
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.streamable_http import (
    GET_STREAM_KEY,
    EventCallback,
    EventMessage,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from mcp.shared.exceptions import McpError
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from goffy_hub.auth import (
    HUB_ISSUER,
    SAFE_TOOL_SCOPE,
    AuthenticatedPrincipal,
    CredentialAuthenticator,
    paired_client_id,
)
from goffy_hub.operator_audit import OperatorAuditLog
from goffy_hub.registry import (
    ToolArgumentsError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)
from goffy_hub.settings import HubSettings
from goffy_protocol import ToolCapability

MCP_SERVER_VERSION = "0.2.0"
MCP_SAFE_TOOL_SCOPE = SAFE_TOOL_SCOPE
MCP_CALL_QUEUE_TIMEOUT_SECONDS = 1.0
MCP_SESSION_IDLE_TIMEOUT_SECONDS = 60.0
MCP_NOTIFICATION_TIMEOUT_SECONDS = 1.0
MCP_SSE_MAX_LIFETIME_SECONDS = 45.0
MCP_SSE_CLOSE_GRACE_SECONDS = 1.0
MCP_REPLAY_MAX_EVENTS = 64
MCP_REPLAY_MAX_BYTES = 16_384


class HubTokenVerifier:
    def __init__(self, authenticator: CredentialAuthenticator) -> None:
        self._authenticator = authenticator

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await self._authenticator.authenticate_token(token)
        if principal is None:
            return None
        return AccessToken(
            token=token,
            client_id=principal.client_id,
            scopes=list(principal.scopes),
            subject=principal.subject,
            claims={"iss": HUB_ISSUER},
        )


class RegistryMcpAdapter:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_concurrent_calls: int,
        queue_timeout_seconds: float = MCP_CALL_QUEUE_TIMEOUT_SECONDS,
    ) -> None:
        if max_concurrent_calls <= 0:
            raise ValueError("max_concurrent_calls must be positive")
        if queue_timeout_seconds <= 0:
            raise ValueError("queue_timeout_seconds must be positive")
        self._registry = registry
        self._call_slots = asyncio.Semaphore(max_concurrent_calls)
        self._queue_timeout_seconds = queue_timeout_seconds

    async def list_tools(self) -> list[types.Tool]:
        return [_to_mcp_tool(capability) for capability in self._registry.describe()]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | types.CallToolResult:
        try:
            await asyncio.wait_for(
                self._call_slots.acquire(),
                timeout=self._queue_timeout_seconds,
            )
        except TimeoutError as error:
            raise _protocol_error(types.INTERNAL_ERROR, "The Hub is busy.") from error

        try:
            result = await self._registry.invoke(name, arguments)
            return result.structured_content
        except ToolNotFoundError as error:
            raise _protocol_error(types.INVALID_PARAMS, "Unknown or unauthorized tool.") from error
        except ToolArgumentsError as error:
            raise _protocol_error(types.INVALID_PARAMS, "Invalid tool arguments.") from error
        except ToolExecutionError:
            return _tool_error("The tool failed without a verified result.")
        finally:
            self._call_slots.release()


class GoffyMcpServer(Server[Any, Any]):
    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
    ) -> InitializationOptions:
        requested = notification_options or NotificationOptions()
        return super().create_initialization_options(
            NotificationOptions(
                prompts_changed=requested.prompts_changed,
                resources_changed=requested.resources_changed,
                tools_changed=True,
            ),
            experimental_capabilities,
        )


@dataclass(frozen=True, slots=True)
class _StoredMcpEvent:
    event_id: str
    stream_id: str
    message: types.JSONRPCMessage | None
    size_bytes: int


class BoundedMcpEventStore(EventStore):
    """Session-local replay storage for non-sensitive tool-list changes only."""

    def __init__(
        self,
        *,
        max_events: int = MCP_REPLAY_MAX_EVENTS,
        max_bytes: int = MCP_REPLAY_MAX_BYTES,
    ) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._event_prefix = token_urlsafe(18)
        self._next_sequence = 0
        self._events: deque[_StoredMcpEvent] = deque()
        self._stored_bytes = 0
        self._lock = asyncio.Lock()

    async def store_event(
        self,
        stream_id: str,
        message: types.JSONRPCMessage | None,
    ) -> str:
        async with self._lock:
            event_id = self._next_event_id()
            if not _is_replayable_tool_list_event(stream_id, message):
                return event_id
            self._retain_event(event_id, stream_id, message)
            return event_id

    async def replay_events_after(
        self,
        last_event_id: str,
        send_callback: EventCallback,
    ) -> str | None:
        async with self._lock:
            cursor_index = next(
                (
                    index
                    for index, event in enumerate(self._events)
                    if event.event_id == last_event_id
                ),
                None,
            )
            retained = tuple(self._events)
            if cursor_index is None:
                stream_id = GET_STREAM_KEY
                replay: tuple[_StoredMcpEvent, ...] = ()
                requires_resync = True
            else:
                cursor = retained[cursor_index]
                stream_id = cursor.stream_id
                replay = retained[cursor_index + 1 :]
                requires_resync = cursor.message is not None or bool(replay)

            if requires_resync:
                # Reconnects get a fresh invalidation signal. This is also the
                # safe recovery path for foreign or evicted opaque cursors.
                resync_message = _tool_list_changed_message()
                resync_event_id = self._next_event_id()
                resync_event = self._retain_event(
                    resync_event_id,
                    GET_STREAM_KEY,
                    resync_message,
                )
                if resync_event is None:
                    resync_event = _StoredMcpEvent(
                        event_id=resync_event_id,
                        stream_id=GET_STREAM_KEY,
                        message=resync_message,
                        size_bytes=0,
                    )
                replay = (*replay, resync_event)

        for event in replay:
            if event.message is not None and event.stream_id == stream_id:
                await send_callback(EventMessage(event.message, event.event_id))
        return stream_id

    def _next_event_id(self) -> str:
        self._next_sequence += 1
        return f"{self._event_prefix}.{self._next_sequence}"

    def _retain_event(
        self,
        event_id: str,
        stream_id: str,
        message: types.JSONRPCMessage | None,
    ) -> _StoredMcpEvent | None:
        size_bytes = _event_size_bytes(event_id, stream_id, message)
        if size_bytes > self._max_bytes:
            return None
        event = _StoredMcpEvent(
            event_id=event_id,
            stream_id=stream_id,
            message=message,
            size_bytes=size_bytes,
        )
        self._events.append(event)
        self._stored_bytes += size_bytes
        while len(self._events) > self._max_events or self._stored_bytes > self._max_bytes:
            removed = self._events.popleft()
            self._stored_bytes -= removed.size_bytes
        return event


class McpToolListNotifier:
    def __init__(self) -> None:
        self._sessions: WeakValueDictionary[str, ServerSession] = WeakValueDictionary()
        self._lock = asyncio.Lock()

    async def register(self, session_id: str, session: ServerSession) -> None:
        async with self._lock:
            self._sessions[session_id] = session

    async def unregister(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def notify(self, active_session_ids: Collection[str]) -> None:
        active = frozenset(active_session_ids)
        async with self._lock:
            for session_id in tuple(self._sessions):
                if session_id not in active:
                    self._sessions.pop(session_id, None)
            sessions = tuple(self._sessions.items())

        async def send(session_id: str, session: ServerSession) -> None:
            try:
                await asyncio.wait_for(
                    session.send_tool_list_changed(),
                    timeout=MCP_NOTIFICATION_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.unregister(session_id)

        await asyncio.gather(*(send(session_id, session) for session_id, session in sessions))


@dataclass(frozen=True, slots=True)
class McpRuntime:
    server: GoffyMcpServer
    session_manager: GoffyStreamableHTTPSessionManager
    application: ASGIApp
    adapter: RegistryMcpAdapter
    notifier: McpToolListNotifier

    async def notify_tool_list_changed(self) -> None:
        await self.notifier.notify(self.session_manager.active_session_ids)

    async def revoke_credential(self, credential_id: UUID) -> None:
        await self.session_manager.terminate_client(paired_client_id(credential_id))


class GoffyStreamableHTTPSessionManager(StreamableHTTPSessionManager):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        notifier = kwargs.pop("notifier", None)
        if not isinstance(notifier, McpToolListNotifier):
            raise ValueError("GOFFY MCP session manager requires a tool-list notifier")
        authenticator = kwargs.pop("authenticator", None)
        if not isinstance(authenticator, CredentialAuthenticator):
            raise ValueError("GOFFY MCP session manager requires a credential authenticator")
        self._notifier = notifier
        self._authenticator = authenticator
        super().__init__(*args, **kwargs)
        if self.event_store is not None:
            raise ValueError("GOFFY requires a distinct replay store per MCP session")
        self._event_store_creation_lock = asyncio.Lock()
        self._get_request_lock = asyncio.Lock()
        self._get_request_counts: dict[str, int] = {}
        self._termination_callback: Callable[[Collection[str]], Awaitable[None]] | None = None

    def set_termination_callback(
        self,
        callback: Callable[[Collection[str]], Awaitable[None]],
    ) -> None:
        self._termination_callback = callback

    @property
    def active_session_count(self) -> int:
        return len(self._server_instances)

    @property
    def active_session_ids(self) -> frozenset[str]:
        return frozenset(self._server_instances)

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        connection = HTTPConnection(scope)
        session_id = connection.headers.get("mcp-session-id")
        if session_id is None:
            user = scope.get("user")
            requestor = authorization_context(user) if isinstance(user, AuthenticatedUser) else None
            async with self._event_store_creation_lock:
                self.event_store = BoundedMcpEventStore()
                try:
                    await super().handle_request(scope, receive, send)
                finally:
                    self.event_store = None
            if requestor is not None and isinstance(user, AuthenticatedUser):
                current = await self._authenticator.authenticate_token(user.access_token.token)
                if current is None or current.client_id != requestor["client_id"]:
                    await self.terminate_client(requestor["client_id"])
            return

        transport = self._server_instances.get(session_id)
        user = scope.get("user")
        requestor = authorization_context(user) if isinstance(user, AuthenticatedUser) else None
        owns_session = requestor is not None and requestor == self._session_owners.get(session_id)
        if transport is None or not owns_session:
            await super().handle_request(scope, receive, send)
            return

        if scope.get("method") != "GET":
            await self._extend_idle_deadline_if_not_streaming(session_id, transport)
            await transport.handle_request(scope, receive, send)
            return

        if not await self._begin_get_request(session_id, transport):
            await JSONResponse(
                {"error": "mcp_stream_already_active"},
                status_code=409,
            )(scope, receive, send)
            return

        request_task = asyncio.current_task()
        if request_task is None:  # pragma: no cover - ASGI always runs in a task
            await self._finish_get_request(session_id, transport)
            raise RuntimeError("MCP GET requires an active asyncio task")

        async def enforce_stream_lifetime() -> None:
            await asyncio.sleep(MCP_SSE_MAX_LIFETIME_SECONDS)
            transport.close_standalone_sse_stream()
            await asyncio.sleep(MCP_SSE_CLOSE_GRACE_SECONDS)
            request_task.cancel()

        stream_lifetime_task = asyncio.create_task(enforce_stream_lifetime())
        try:
            request_scope = scope
            if connection.headers.get("last-event-id") is None:
                event_store = transport._event_store
                if isinstance(event_store, BoundedMcpEventStore):
                    priming_cursor = await event_store.store_event(GET_STREAM_KEY, None)
                    request_scope = dict(scope)
                    request_scope["headers"] = [
                        *scope.get("headers", []),
                        (b"last-event-id", priming_cursor.encode("ascii")),
                    ]

            await transport.handle_request(request_scope, receive, send)
        finally:
            stream_lifetime_task.cancel()
            with suppress(asyncio.CancelledError):
                await stream_lifetime_task
            await self._finish_get_request(session_id, transport)

    async def _begin_get_request(
        self,
        session_id: str,
        transport: StreamableHTTPServerTransport,
    ) -> bool:
        async with self._get_request_lock:
            if self._get_request_counts.get(session_id, 0) > 0:
                return False
            self._get_request_counts[session_id] = 1
            if transport.idle_scope is not None:
                transport.idle_scope.deadline = float("inf")
            return True

    async def _finish_get_request(
        self,
        session_id: str,
        transport: StreamableHTTPServerTransport,
    ) -> None:
        async with self._get_request_lock:
            self._get_request_counts.pop(session_id, None)
            if (
                self._server_instances.get(session_id) is transport
                and not transport.is_terminated
                and transport.idle_scope is not None
                and self.session_idle_timeout is not None
            ):
                transport.idle_scope.deadline = anyio.current_time() + self.session_idle_timeout

    async def _extend_idle_deadline_if_not_streaming(
        self,
        session_id: str,
        transport: StreamableHTTPServerTransport,
    ) -> None:
        async with self._get_request_lock:
            if transport.idle_scope is None or self.session_idle_timeout is None:
                return
            if self._get_request_counts.get(session_id, 0) > 0:
                transport.idle_scope.deadline = float("inf")
            else:
                transport.idle_scope.deadline = anyio.current_time() + self.session_idle_timeout

    async def remove_terminated_session(self, session_id: str) -> bool:
        async with self._session_creation_lock:
            transport = self._server_instances.get(session_id)
            if transport is not None and not transport.is_terminated:
                return False
            self._server_instances.pop(session_id, None)
            self._session_owners.pop(session_id, None)
            async with self._get_request_lock:
                self._get_request_counts.pop(session_id, None)
            await self._notifier.unregister(session_id)
            return True

    async def terminate_client(self, client_id: str) -> None:
        async with self._session_creation_lock:
            session_ids = tuple(
                session_id
                for session_id, owner in self._session_owners.items()
                if owner["client_id"] == client_id
            )
            transports = tuple(
                self._server_instances.pop(session_id)
                for session_id in session_ids
                if session_id in self._server_instances
            )
            for session_id in session_ids:
                self._session_owners.pop(session_id, None)

        async with self._get_request_lock:
            for session_id in session_ids:
                self._get_request_counts.pop(session_id, None)
        await asyncio.gather(*(self._notifier.unregister(session_id) for session_id in session_ids))
        await asyncio.gather(*(transport.terminate() for transport in transports))
        if self._termination_callback is not None:
            await self._termination_callback(session_ids)


def build_mcp_runtime(
    settings: HubSettings,
    registry: ToolRegistry,
    authenticator: CredentialAuthenticator,
    *,
    audit_log: OperatorAuditLog | None = None,
) -> McpRuntime:
    adapter = RegistryMcpAdapter(
        registry,
        max_concurrent_calls=settings.mcp_max_concurrent_calls,
    )
    notifier = McpToolListNotifier()
    server = GoffyMcpServer(
        "goffy-hub",
        version=MCP_SERVER_VERSION,
        instructions=(
            "GOFFY Hub exposes only allowlisted SAFE tools. Tool annotations are descriptive; "
            "the Hub registry remains authoritative."
        ),
    )

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        request = server.request_context.request
        if isinstance(request, HTTPConnection):
            session_id = request.headers.get("mcp-session-id")
            if session_id is not None:
                await notifier.register(session_id, server.request_context.session)
        return await adapter.list_tools()

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        result = await adapter.call_tool(
            request.params.name,
            request.params.arguments or {},
        )
        if isinstance(result, types.CallToolResult):
            return types.ServerResult(result)
        return types.ServerResult(
            types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result, indent=2))],
                structuredContent=result,
                isError=False,
            )
        )

    server.request_handlers[types.CallToolRequest] = call_tool

    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.resolved_mcp_allowed_hosts,
        allowed_origins=settings.resolved_mcp_allowed_origins,
    )
    session_manager = GoffyStreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=False,
        security_settings=security_settings,
        session_idle_timeout=MCP_SESSION_IDLE_TIMEOUT_SECONDS,
        notifier=notifier,
        authenticator=authenticator,
    )

    manager_application = _BoundedHttpMessageMiddleware(
        session_manager.handle_request,
        max_message_bytes=settings.max_message_bytes,
        max_active_sessions=settings.mcp_max_active_sessions,
        session_idle_timeout_seconds=MCP_SESSION_IDLE_TIMEOUT_SECONDS,
        terminated_session_cleanup=session_manager.remove_terminated_session,
    )
    session_manager.set_termination_callback(manager_application.remove_sessions)
    authenticated_application: ASGIApp = AuthenticationMiddleware(
        AuthContextMiddleware(
            RequireAuthMiddleware(
                manager_application,
                required_scopes=[MCP_SAFE_TOOL_SCOPE],
            )
        ),
        backend=BearerAuthBackend(HubTokenVerifier(authenticator)),
    )
    application = _ExactMcpEndpoint(
        authenticated_application,
        security_settings=security_settings,
        authenticator=authenticator,
        audit_log=audit_log,
    )
    return McpRuntime(
        server=server,
        session_manager=session_manager,
        application=application,
        adapter=adapter,
        notifier=notifier,
    )


def _is_replayable_tool_list_event(
    stream_id: str,
    message: types.JSONRPCMessage | None,
) -> bool:
    if stream_id != GET_STREAM_KEY:
        return False
    if message is None:
        return True
    root = message.root
    return (
        isinstance(root, types.JSONRPCNotification)
        and root.method == "notifications/tools/list_changed"
    )


def _tool_list_changed_message() -> types.JSONRPCMessage:
    return types.JSONRPCMessage(
        types.JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/tools/list_changed",
        )
    )


def _event_size_bytes(
    event_id: str,
    stream_id: str,
    message: types.JSONRPCMessage | None,
) -> int:
    message_bytes = 0
    if message is not None:
        message_bytes = len(
            message.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
        )
    return len(event_id.encode("ascii")) + len(stream_id.encode("utf-8")) + message_bytes


def _to_mcp_tool(capability: ToolCapability) -> types.Tool:
    return types.Tool(
        name=capability.name,
        title=capability.title,
        description=capability.description,
        inputSchema=capability.input_schema,
        outputSchema=capability.output_schema,
        annotations=types.ToolAnnotations.model_validate(
            capability.annotations.model_dump(mode="json", by_alias=True)
        ),
        _meta=capability.meta.model_dump(mode="json", by_alias=True),
    )


def _tool_error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        isError=True,
    )


def _protocol_error(code: int, message: str) -> McpError:
    return McpError(types.ErrorData(code=code, message=message))


class _ExactMcpEndpoint:
    def __init__(
        self,
        application: ASGIApp,
        *,
        security_settings: TransportSecuritySettings,
        authenticator: CredentialAuthenticator,
        audit_log: OperatorAuditLog | None,
    ) -> None:
        self._application = application
        self._transport_security = TransportSecurityMiddleware(security_settings)
        self._authenticator = authenticator
        self._audit_log = audit_log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "Not found"})
            return
        if scope["type"] != "http":
            raise RuntimeError("MCP endpoint received an unsupported ASGI scope")
        if scope.get("path") != "/mcp":
            await PlainTextResponse("Not found", status_code=404)(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        security_error = await self._transport_security.validate_request(
            connection,
            is_post=scope.get("method") == "POST",
        )
        if security_error is not None:
            await security_error(scope, receive, send)
            return
        if scope.get("method") not in {"GET", "POST", "DELETE"}:
            await self._record_mcp_audit(
                scope,
                principal=None,
                outcome="rejected",
                detail_code="status:405",
            )
            await PlainTextResponse(
                "Method not allowed",
                status_code=405,
                headers={"Allow": "GET, POST, DELETE"},
            )(scope, receive, send)
            return
        principal = await self._authenticate_for_audit(scope)
        response_status: int | None = None

        async def audit_send(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
            await send(message)

        try:
            await self._application(scope, receive, audit_send)
        except Exception:
            await self._record_mcp_audit(
                scope,
                principal=principal,
                outcome="failed",
                detail_code=(
                    "exception"
                    if response_status is None
                    else f"exception_after_status:{response_status}"
                ),
            )
            raise
        status_code = response_status or 0
        await self._record_mcp_audit(
            scope,
            principal=principal,
            outcome="succeeded" if 200 <= status_code < 400 else "rejected",
            detail_code=f"status:{status_code}",
        )

    async def _authenticate_for_audit(self, scope: Scope) -> AuthenticatedPrincipal | None:
        connection = HTTPConnection(scope)
        return await self._authenticator.authenticate_header(
            connection.headers.get("authorization")
        )

    async def _record_mcp_audit(
        self,
        scope: Scope,
        *,
        principal: AuthenticatedPrincipal | None,
        outcome: str,
        detail_code: str,
    ) -> None:
        if self._audit_log is None:
            return
        self._audit_log.record(
            source="mcp",
            action=_http_audit_action(scope.get("method")),
            outcome=outcome,
            principal_kind=principal.kind.value if principal else "none",
            credential_id=principal.credential_id if principal else None,
            detail_code=detail_code,
        )


def _http_audit_action(method: object) -> str:
    if not isinstance(method, str):
        return "http.other"
    normalized = method.lower()
    if normalized in {"get", "post", "delete"}:
        return f"http.{normalized}"
    return "http.other"


class _BoundedHttpMessageMiddleware:
    def __init__(
        self,
        application: ASGIApp,
        *,
        max_message_bytes: int,
        max_active_sessions: int,
        session_idle_timeout_seconds: float,
        terminated_session_cleanup: Callable[[str], Awaitable[bool]],
    ) -> None:
        if max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        if max_active_sessions <= 0:
            raise ValueError("max_active_sessions must be positive")
        if session_idle_timeout_seconds <= 0:
            raise ValueError("session_idle_timeout_seconds must be positive")
        self._application = application
        self._max_message_bytes = max_message_bytes
        self._max_active_sessions = max_active_sessions
        self._session_idle_timeout_seconds = session_idle_timeout_seconds
        self._terminated_session_cleanup = terminated_session_cleanup
        self._session_lock = asyncio.Lock()
        self._active_sessions: dict[str, float] = {}
        self._streaming_session_counts: dict[str, int] = {}
        self._pending_sessions = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        bounded_receive = receive
        connection = HTTPConnection(scope)
        session_id = connection.headers.get("mcp-session-id")
        request_method: str | None = None
        session_slot_reserved = False
        if (
            scope["type"] == "http"
            and scope.get("method") in {"GET", "DELETE"}
            and session_id is None
        ):
            await JSONResponse(
                {"error": "mcp_session_required"},
                status_code=400,
            )(scope, receive, send)
            return
        if scope["type"] == "http" and scope.get("method") == "POST":
            body = await self._read_request_body(scope, receive, send)
            if body is None:
                return
            request_method, lifecycle_error = _validate_lifecycle_request(scope, body)
            if lifecycle_error is not None:
                await lifecycle_error(scope, receive, send)
                return
            if request_method == "initialize" and session_id is None:
                session_slot_reserved = await self._reserve_session_slot()
                if not session_slot_reserved:
                    await JSONResponse(
                        {"error": "mcp_session_capacity_reached"},
                        status_code=503,
                    )(scope, receive, send)
                    return
            delivered = False

            async def replay_receive() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            bounded_receive = replay_receive

        if session_id is not None:
            await self._touch_session(session_id)

        if scope.get("method") == "GET":
            response_status: int | None = None

            async def stream_send(message: Message) -> None:
                nonlocal response_status
                if message["type"] == "http.response.start":
                    response_status = cast(int, message["status"])
                await send(message)

            if session_id is not None:
                await self._mark_session_streaming(session_id, increment=1)
            try:
                await self._application(scope, bounded_receive, stream_send)
            finally:
                if session_id is not None:
                    await self._mark_session_streaming(session_id, increment=-1)
                    await self._touch_session(session_id)
            if (
                response_status == 404
                and session_id
                and await self._terminated_session_cleanup(session_id)
            ):
                await self._remove_session(session_id)
            return

        response_messages: list[Message] = []
        response_bytes = 0

        async def capture_send(message: Message) -> None:
            nonlocal response_bytes
            if message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            response_messages.append(message)

        try:
            await self._application(scope, bounded_receive, capture_send)
        except BaseException:
            if session_slot_reserved:
                await self._release_session_reservation()
            raise

        response_status = _response_status(response_messages)
        response_session_id = _response_header(response_messages, b"mcp-session-id")
        if session_slot_reserved:
            accepted_session_id = response_session_id if response_status == 200 else None
            await self._complete_session_reservation(accepted_session_id)
        if (
            scope.get("method") == "DELETE"
            and response_status in {200, 204}
            and session_id
            and await self._terminated_session_cleanup(session_id)
        ):
            await self._remove_session(session_id)
        if (
            response_status == 404
            and session_id
            and await self._terminated_session_cleanup(session_id)
        ):
            await self._remove_session(session_id)

        if response_bytes > self._max_message_bytes:
            await JSONResponse(
                {"error": "response_too_large"},
                status_code=500,
            )(scope, bounded_receive, send)
            return
        for message in response_messages:
            await send(message)

    async def _reserve_session_slot(self) -> bool:
        async with self._session_lock:
            self._prune_idle_sessions()
            if len(self._active_sessions) + self._pending_sessions >= self._max_active_sessions:
                return False
            self._pending_sessions += 1
            return True

    async def _release_session_reservation(self) -> None:
        async with self._session_lock:
            self._pending_sessions -= 1

    async def _complete_session_reservation(self, session_id: str | None) -> None:
        async with self._session_lock:
            self._pending_sessions -= 1
            if session_id is not None:
                self._active_sessions[session_id] = asyncio.get_running_loop().time()

    async def _touch_session(self, session_id: str) -> None:
        async with self._session_lock:
            if session_id in self._active_sessions:
                self._active_sessions[session_id] = asyncio.get_running_loop().time()

    async def _remove_session(self, session_id: str) -> None:
        async with self._session_lock:
            self._active_sessions.pop(session_id, None)
            self._streaming_session_counts.pop(session_id, None)

    async def remove_sessions(self, session_ids: Collection[str]) -> None:
        async with self._session_lock:
            for session_id in session_ids:
                self._active_sessions.pop(session_id, None)
                self._streaming_session_counts.pop(session_id, None)

    async def _mark_session_streaming(self, session_id: str, *, increment: int) -> None:
        async with self._session_lock:
            count = self._streaming_session_counts.get(session_id, 0) + increment
            if count > 0:
                self._streaming_session_counts[session_id] = count
            else:
                self._streaming_session_counts.pop(session_id, None)

    def _prune_idle_sessions(self) -> None:
        cutoff = asyncio.get_running_loop().time() - self._session_idle_timeout_seconds
        expired = [
            session_id
            for session_id, last_activity in self._active_sessions.items()
            if last_activity <= cutoff and session_id not in self._streaming_session_counts
        ]
        for session_id in expired:
            del self._active_sessions[session_id]

    async def _read_request_body(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> bytes | None:
        content_length = HTTPConnection(scope).headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await JSONResponse(
                    {"error": "invalid_content_length"},
                    status_code=400,
                )(scope, receive, send)
                return None
            if declared_length < 0:
                await JSONResponse(
                    {"error": "invalid_content_length"},
                    status_code=400,
                )(scope, receive, send)
                return None
            if declared_length > self._max_message_bytes:
                await JSONResponse(
                    {"error": "request_too_large"},
                    status_code=413,
                )(scope, receive, send)
                return None

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            if message["type"] != "http.request":
                await JSONResponse(
                    {"error": "invalid_http_body"},
                    status_code=400,
                )(scope, receive, send)
                return None
            body.extend(message.get("body", b""))
            if len(body) > self._max_message_bytes:
                await JSONResponse(
                    {"error": "request_too_large"},
                    status_code=413,
                )(scope, receive, send)
                return None
            if not message.get("more_body", False):
                return bytes(body)


def _validate_lifecycle_request(
    scope: Scope, body: bytes
) -> tuple[str | None, JSONResponse | None]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, JSONResponse({"error": "invalid_request"}, status_code=400)
    if not isinstance(payload, dict):
        return None, JSONResponse({"error": "invalid_request"}, status_code=400)

    method = payload.get("method")
    if method is not None and not isinstance(method, str):
        return None, JSONResponse({"error": "invalid_request"}, status_code=400)
    session_id = HTTPConnection(scope).headers.get("mcp-session-id")
    if method == "initialize" and session_id is not None:
        return method, JSONResponse({"error": "session_already_initialized"}, status_code=400)
    if session_id is None and method != "initialize":
        return method, JSONResponse({"error": "mcp_session_required"}, status_code=400)
    return method, None


def _response_status(messages: list[Message]) -> int | None:
    for message in messages:
        if message["type"] == "http.response.start":
            return cast(int, message["status"])
    return None


def _response_header(messages: list[Message], name: bytes) -> str | None:
    for message in messages:
        if message["type"] == "http.response.start":
            for header_name, value in message.get("headers", []):
                if header_name.lower() == name:
                    return cast(bytes, value).decode("ascii")
    return None
