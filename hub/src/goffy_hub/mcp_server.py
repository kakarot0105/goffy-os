from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from mcp import types
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import AccessToken
from mcp.server.lowlevel import Server
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

from goffy_hub.auth import BEARER_PREFIX, is_authorized
from goffy_hub.registry import (
    ToolArgumentsError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)
from goffy_hub.settings import HubSettings
from goffy_protocol import ToolCapability

MCP_SERVER_VERSION = "0.2.0"
MCP_SAFE_TOOL_SCOPE = "goffy.tools.safe"
MCP_CALL_QUEUE_TIMEOUT_SECONDS = 1.0
MCP_SESSION_IDLE_TIMEOUT_SECONDS = 60.0


class HubTokenVerifier:
    def __init__(self, settings: HubSettings) -> None:
        self._settings = settings

    async def verify_token(self, token: str) -> AccessToken | None:
        if not is_authorized(f"{BEARER_PREFIX}{token}", self._settings):
            return None
        return AccessToken(
            token=token,
            client_id="goffy-local-client",
            scopes=[MCP_SAFE_TOOL_SCOPE],
            subject="local-operator",
            claims={"iss": "goffy-hub"},
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


@dataclass(frozen=True, slots=True)
class McpRuntime:
    server: Server[Any, Any]
    session_manager: GoffyStreamableHTTPSessionManager
    application: ASGIApp
    adapter: RegistryMcpAdapter


class GoffyStreamableHTTPSessionManager(StreamableHTTPSessionManager):
    @property
    def active_session_count(self) -> int:
        return len(self._server_instances)

    async def remove_terminated_session(self, session_id: str) -> bool:
        async with self._session_creation_lock:
            transport = self._server_instances.get(session_id)
            if transport is not None and not transport.is_terminated:
                return False
            self._server_instances.pop(session_id, None)
            self._session_owners.pop(session_id, None)
            return True


def build_mcp_runtime(settings: HubSettings, registry: ToolRegistry) -> McpRuntime:
    adapter = RegistryMcpAdapter(
        registry,
        max_concurrent_calls=settings.mcp_max_concurrent_calls,
    )
    server: Server[Any, Any] = Server(
        "goffy-hub",
        version=MCP_SERVER_VERSION,
        instructions=(
            "GOFFY Hub exposes only allowlisted SAFE tools. Tool annotations are descriptive; "
            "the Hub registry remains authoritative."
        ),
    )

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[types.Tool]:
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
    )

    manager_application = _BoundedHttpMessageMiddleware(
        session_manager.handle_request,
        max_message_bytes=settings.max_message_bytes,
        max_active_sessions=settings.mcp_max_active_sessions,
        session_idle_timeout_seconds=MCP_SESSION_IDLE_TIMEOUT_SECONDS,
        terminated_session_cleanup=session_manager.remove_terminated_session,
    )
    authenticated_application: ASGIApp = AuthenticationMiddleware(
        AuthContextMiddleware(
            RequireAuthMiddleware(
                manager_application,
                required_scopes=[MCP_SAFE_TOOL_SCOPE],
            )
        ),
        backend=BearerAuthBackend(HubTokenVerifier(settings)),
    )
    application = _ExactMcpEndpoint(
        authenticated_application,
        security_settings=security_settings,
    )
    return McpRuntime(
        server=server,
        session_manager=session_manager,
        application=application,
        adapter=adapter,
    )


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
    ) -> None:
        self._application = application
        self._transport_security = TransportSecurityMiddleware(security_settings)

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
        if scope.get("method") not in {"POST", "DELETE"}:
            await PlainTextResponse(
                "Method not allowed",
                status_code=405,
                headers={"Allow": "POST, DELETE"},
            )(scope, receive, send)
            return
        await self._application(scope, receive, send)


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
        self._pending_sessions = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        bounded_receive = receive
        connection = HTTPConnection(scope)
        session_id = connection.headers.get("mcp-session-id")
        request_method: str | None = None
        session_slot_reserved = False
        if scope["type"] == "http" and scope.get("method") == "DELETE" and session_id is None:
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
        if response_status == 404 and session_id:
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

    def _prune_idle_sessions(self) -> None:
        cutoff = asyncio.get_running_loop().time() - self._session_idle_timeout_seconds
        expired = [
            session_id
            for session_id, last_activity in self._active_sessions.items()
            if last_activity <= cutoff
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
