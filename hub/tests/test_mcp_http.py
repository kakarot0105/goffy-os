from __future__ import annotations

import asyncio
import json
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.streamable_http import GET_STREAM_KEY, EventMessage
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from pydantic import SecretStr
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import goffy_hub.mcp_server as mcp_server_module
import goffy_hub.tools.git_status as git_status_module
import goffy_hub.tools.mac_apps as mac_apps_module
from goffy_hub.app import build_registry, create_app
from goffy_hub.auth import CredentialAuthenticator
from goffy_hub.mcp_server import (
    BoundedMcpEventStore,
    McpToolListNotifier,
    RegistryMcpAdapter,
    _ExactMcpEndpoint,
)
from goffy_hub.operator_audit import OperatorAuditLog
from goffy_hub.registry import ToolInvocationResult, ToolRegistry
from goffy_hub.settings import HubSettings
from goffy_hub.tools import (
    build_mac_apps_list_tool,
    build_mac_apps_open_tool,
    build_mac_clipboard_read_tool,
    build_mac_system_tool,
)
from goffy_protocol import MCP_PROTOCOL_VERSION

AUTHORIZATION = "Bearer test-token-that-is-long-enough"  # noqa: S105
MCP_HTTP_HEADERS = {
    "Authorization": AUTHORIZATION,
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "goffy-test-client", "version": "1.0.0"},
        },
    }


def initialize_http_session(client: TestClient) -> str:
    response = client.post("/mcp", json=initialize_request(), headers=MCP_HTTP_HEADERS)
    assert response.status_code == 200
    return response.headers["mcp-session-id"]


@pytest.mark.asyncio
async def test_mcp_audit_records_failure_when_response_fails_after_start() -> None:
    async def failing_after_start(scope: object, receive: object, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("simulated response failure")

    settings = HubSettings(auth_token=SecretStr("test-token-that-is-long-enough"))
    audit_log = OperatorAuditLog(max_events=8)
    endpoint = _ExactMcpEndpoint(
        failing_after_start,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.resolved_mcp_allowed_hosts,
            allowed_origins=settings.resolved_mcp_allowed_origins,
        ),
        authenticator=CredentialAuthenticator(settings, None),
        audit_log=audit_log,
    )
    transport = httpx.ASGITransport(app=endpoint, raise_app_exceptions=False)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8787",
        timeout=5,
    ) as client:
        response = await client.post("/mcp", content=b"{}", headers=MCP_HTTP_HEADERS)
    event = audit_log.snapshot().events[0]

    assert response.status_code == 200
    assert event.source == "mcp"
    assert event.action == "http.post"
    assert event.outcome == "failed"
    assert event.detail_code == "exception_after_status:200"


def tool_list_changed_message() -> types.JSONRPCMessage:
    return types.JSONRPCMessage.model_validate(
        {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    )


@pytest.mark.asyncio
async def test_official_client_initializes_lists_and_calls_registry_tool() -> None:
    settings = HubSettings(auth_token=SecretStr("test-token-that-is-long-enough"))
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialization = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("mac.system_info", {})
            processes = await session.call_tool("mac.processes.list", {"maxEntries": 3})
            with pytest.raises(McpError) as unknown_error:
                await session.call_tool("mac.not_registered", {})

    assert initialization.protocolVersion == MCP_PROTOCOL_VERSION
    assert initialization.capabilities.tools is not None
    assert initialization.capabilities.tools.listChanged is True
    assert get_session_id() is not None
    assert sorted(tool.name for tool in listed.tools) == [
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]
    tool = next(tool for tool in listed.tools if tool.name == "mac.system_info")
    assert tool.name == "mac.system_info"
    assert tool.outputSchema is not None
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.meta == {
        "dev.goffy/toolVersion": "1.0.0",
        "dev.goffy/executionTarget": "MAC",
        "dev.goffy/permission": "SAFE",
        "dev.goffy/timeoutMs": 3000,
    }
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["status"] == "available"
    assert set(result.structuredContent) == {"status", "operatingSystem", "architecture"}
    assert processes.isError is False
    assert processes.structuredContent is not None
    assert processes.structuredContent["status"] == "available"
    assert set(processes.structuredContent) == {
        "status",
        "processCount",
        "skippedCount",
        "truncated",
        "entries",
    }
    assert isinstance(result.content[0], types.TextContent)
    assert json.loads(result.content[0].text) == result.structuredContent
    assert unknown_error.value.error.code == types.INVALID_PARAMS
    assert "unauthorized" in unknown_error.value.error.message.lower()


@pytest.mark.asyncio
async def test_official_client_lists_approved_mac_file_root(tmp_path) -> None:
    (tmp_path / "visible.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        mac_files_roots=(tmp_path,),
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialization = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("mac.files.list", {"rootIndex": 0})
            largest = await session.call_tool("mac.files.largest", {"rootIndex": 0})

    assert initialization.protocolVersion == MCP_PROTOCOL_VERSION
    assert sorted(tool.name for tool in listed.tools) == [
        "goffy.rom.status",
        "mac.files.largest",
        "mac.files.list",
        "mac.processes.list",
        "mac.system_info",
    ]
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["rootIndex"] == 0
    assert result.structuredContent["approvedRoots"] == [{"rootIndex": 0, "name": tmp_path.name}]
    assert [entry["name"] for entry in result.structuredContent["entries"]] == ["visible.txt"]
    assert str(tmp_path) not in json.dumps(result.structuredContent)
    assert largest.isError is False
    assert largest.structuredContent is not None
    assert largest.structuredContent["rootIndex"] == 0
    assert [entry["relativePath"] for entry in largest.structuredContent["entries"]] == [
        "visible.txt"
    ]
    assert str(tmp_path) not in json.dumps(largest.structuredContent)


@pytest.mark.asyncio
async def test_official_client_reads_approved_git_status(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_status_module, "_resolve_git_executable", lambda: Path(sys.executable))

    def fake_status(
        _git_executable: Path,
        _repo_path: Path,
        _include_untracked: bool,
        _timeout_seconds: float,
    ) -> str:
        return "\n".join(
            [
                "# branch.oid 0123456789abcdef0123456789abcdef01234567",
                "# branch.head main",
                "? TODO.md",
            ]
        )

    monkeypatch.setattr(git_status_module, "_run_git_status", fake_status)
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        git_repo_roots=(tmp_path,),
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialization = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("git.status", {"repoIndex": 0, "maxChanges": 5})

    assert initialization.protocolVersion == MCP_PROTOCOL_VERSION
    assert sorted(tool.name for tool in listed.tools) == [
        "git.status",
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["repoIndex"] == 0
    assert result.structuredContent["branch"] == "main"
    assert result.structuredContent["untrackedCount"] == 1
    assert result.structuredContent["approvedRepos"] == [{"repoIndex": 0, "name": tmp_path.name}]
    assert result.structuredContent["changes"] == [
        {
            "path": "TODO.md",
            "pathTruncated": False,
            "indexStatus": "?",
            "workingTreeStatus": "?",
            "kind": "untracked",
        }
    ]
    assert str(tmp_path) not in json.dumps(result.structuredContent)


@pytest.mark.asyncio
async def test_official_client_reads_opt_in_mac_clipboard_text() -> None:
    class FakeClipboardReader:
        def read_text(self) -> str:
            return "copied text"

        def is_available(self) -> bool:
            return True

    registry = ToolRegistry()
    registry.register(build_mac_system_tool(timeout_seconds=1))
    registry.register(
        build_mac_clipboard_read_tool(
            timeout_seconds=1,
            reader=FakeClipboardReader(),
        )
    )
    app = create_app(
        HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")),
        registry=registry,
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialization = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("mac.clipboard.read", {"maxChars": 6})

    assert initialization.protocolVersion == MCP_PROTOCOL_VERSION
    assert sorted(tool.name for tool in listed.tools) == ["mac.clipboard.read", "mac.system_info"]
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent == {
        "status": "available",
        "contentType": "text",
        "text": "copied",
        "textTruncated": True,
        "characterCount": 11,
        "characterCountTruncated": False,
    }


@pytest.mark.asyncio
async def test_official_client_reads_approved_mac_app_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps_module, "is_mac_apps_supported", lambda: True)
    registry = ToolRegistry()
    registry.register(build_mac_system_tool(timeout_seconds=1))
    registry.register(
        build_mac_apps_list_tool(
            ("Safari=com.apple.Safari", "Terminal=com.apple.Terminal"),
            timeout_seconds=1,
        )
    )
    app = create_app(
        HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")),
        registry=registry,
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialization = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("mac.apps.list", {"maxEntries": 1})

    assert initialization.protocolVersion == MCP_PROTOCOL_VERSION
    assert sorted(tool.name for tool in listed.tools) == ["mac.apps.list", "mac.system_info"]
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent == {
        "status": "available",
        "appCount": 2,
        "truncated": True,
        "entries": [
            {
                "appIndex": 0,
                "displayName": "Safari",
                "bundleId": "com.apple.Safari",
            }
        ],
    }
    assert "/Applications" not in json.dumps(result.structuredContent)
    assert isinstance(result.content[0], types.TextContent)
    assert json.loads(result.content[0].text) == result.structuredContent


@pytest.mark.asyncio
async def test_official_client_cannot_call_confirm_mac_app_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps_module, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps_module, "mac_app_open_supported", lambda: True)
    registry = ToolRegistry(confirm_tool_names=frozenset({"mac.apps.open"}))
    registry.register(build_mac_system_tool(timeout_seconds=1))
    registry.register(build_mac_apps_list_tool(("Safari=com.apple.Safari",), timeout_seconds=1))
    registry.register(build_mac_apps_open_tool(("Safari=com.apple.Safari",), timeout_seconds=1))
    app = create_app(
        HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")),
        registry=registry,
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            with pytest.raises(McpError) as rejected:
                await session.call_tool("mac.apps.open", {"displayName": "Safari"})

    assert [tool.name for tool in listed.tools] == ["mac.apps.list", "mac.system_info"]
    assert rejected.value.error.code == types.INVALID_PARAMS
    assert "unauthorized" in rejected.value.error.message.lower()


@pytest.mark.asyncio
async def test_official_client_relists_after_tool_health_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    app = create_app(HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        notifications: asyncio.Queue[types.ServerNotification] = asyncio.Queue()

        async def capture_notification(
            message: object,
        ) -> None:
            if isinstance(message, types.ServerNotification):
                await notifications.put(message)

        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(
                read_stream,
                write_stream,
                message_handler=capture_notification,
            ) as session,
        ):
            initialization = await session.initialize()
            initial_tools = await session.list_tools()
            session_id = _get_session_id()
            assert session_id is not None
            server_transport = app.state.mcp_runtime.session_manager._server_instances[session_id]
            for _ in range(500):
                if GET_STREAM_KEY in server_transport._request_streams:
                    break
                await asyncio.sleep(0.01)
            assert GET_STREAM_KEY in server_transport._request_streams
            monkeypatch.setattr(platform, "system", lambda: "")

            unavailable = await app.state.tool_health_monitor.check_now()
            event_store = server_transport._event_store
            assert isinstance(event_store, BoundedMcpEventStore)
            for _ in range(500):
                if event_store._events:
                    break
                await asyncio.sleep(0.01)
            unavailable_tools = await session.list_tools()
            with pytest.raises(McpError) as unavailable_call:
                await session.call_tool("mac.system_info", {})
            server_transport.close_standalone_sse_stream()
            unavailable_notification = await asyncio.wait_for(notifications.get(), timeout=5)
            assert notifications.empty()
            monkeypatch.setattr(platform, "system", lambda: "Darwin")

            restored = await app.state.tool_health_monitor.check_now()
            for _ in range(500):
                if GET_STREAM_KEY in server_transport._request_streams:
                    break
                await asyncio.sleep(0.01)
            assert GET_STREAM_KEY in server_transport._request_streams
            server_transport.close_standalone_sse_stream()
            restored_notification = await asyncio.wait_for(notifications.get(), timeout=5)
            reconnect_resync = await asyncio.wait_for(notifications.get(), timeout=5)
            assert notifications.empty()
            restored_tools = await session.list_tools()

    assert initialization.capabilities.tools is not None
    assert initialization.capabilities.tools.listChanged is True
    assert isinstance(unavailable_notification.root, types.ToolListChangedNotification)
    assert isinstance(restored_notification.root, types.ToolListChangedNotification)
    assert isinstance(reconnect_resync.root, types.ToolListChangedNotification)
    assert [tool.name for tool in initial_tools.tools] == [
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]
    assert unavailable.changed is True
    assert [tool.name for tool in unavailable_tools.tools] == ["goffy.rom.status"]
    assert unavailable_call.value.error.code == types.INVALID_PARAMS
    assert "unauthorized" in unavailable_call.value.error.message.lower()
    assert restored.changed is True
    assert [tool.name for tool in restored_tools.tools] == [
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]


@pytest.mark.parametrize("authorization", [None, "Bearer incorrect-token-that-is-long-enough"])
def test_mcp_fails_closed_for_missing_or_invalid_token(
    client: TestClient, authorization: str | None
) -> None:
    headers = {"Accept": "application/json, text/event-stream"}
    if authorization is not None:
        headers["Authorization"] = authorization

    response = client.post("/mcp", json=initialize_request(), headers=headers)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    assert response.headers["www-authenticate"].startswith("Bearer ")


def test_mcp_rejects_invalid_origin_before_json_rpc(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=initialize_request(),
        headers={**MCP_HTTP_HEADERS, "Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.text == "Invalid Origin header"


def test_mcp_rejects_invalid_host_before_json_rpc(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=initialize_request(),
        headers={**MCP_HTTP_HEADERS, "Host": "attacker.example"},
    )

    assert response.status_code == 421
    assert response.text == "Invalid Host header"


@pytest.mark.parametrize(
    ("blocked_headers", "expected_status"),
    [
        ({"Host": "attacker.example"}, 421),
        ({"Origin": "https://attacker.example"}, 403),
    ],
)
def test_mcp_rejects_transport_security_before_authentication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    blocked_headers: dict[str, str],
    expected_status: int,
) -> None:
    calls = 0
    authenticator = client.app.state.authenticator
    original_authenticate_header = authenticator.authenticate_header

    async def counted_authenticate_header(authorization: str | None) -> object:
        nonlocal calls
        calls += 1
        return await original_authenticate_header(authorization)

    monkeypatch.setattr(authenticator, "authenticate_header", counted_authenticate_header)

    response = client.post(
        "/mcp",
        json=initialize_request(),
        headers={**MCP_HTTP_HEADERS, **blocked_headers},
    )

    assert response.status_code == expected_status
    assert calls == 0


def test_mcp_uses_exact_non_redirecting_endpoint(client: TestClient) -> None:
    response = client.post("/mcp", json=initialize_request(), headers=MCP_HTTP_HEADERS)
    trailing_slash = client.post("/mcp/", json=initialize_request(), headers=MCP_HTTP_HEADERS)

    assert response.status_code == 200
    assert "location" not in response.headers
    payload = response.json()
    assert payload["id"] == 1
    assert payload["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert payload["result"]["capabilities"]["tools"] == {"listChanged": True}
    assert trailing_slash.status_code == 404


def test_mcp_initialized_notification_is_accepted(client: TestClient) -> None:
    session_id = initialize_http_session(client)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={
            **MCP_HTTP_HEADERS,
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "MCP-Session-Id": session_id,
        },
    )

    assert response.status_code == 202
    assert not response.content


@pytest.mark.parametrize(
    "payload",
    [
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "mac.system_info", "arguments": {}},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ],
)
def test_mcp_requires_initialized_session_before_operations(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post(
        "/mcp",
        json=payload,
        headers={**MCP_HTTP_HEADERS, "MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "mcp_session_required"}


def test_mcp_rejects_reinitialization_and_delete_without_session(client: TestClient) -> None:
    session_id = initialize_http_session(client)
    reinitialize = client.post(
        "/mcp",
        json=initialize_request(),
        headers={**MCP_HTTP_HEADERS, "MCP-Session-Id": session_id},
    )
    delete_without_session = client.delete(
        "/mcp",
        headers={"Authorization": AUTHORIZATION, "Accept": "application/json"},
    )

    assert reinitialize.status_code == 400
    assert reinitialize.json() == {"error": "session_already_initialized"}
    assert delete_without_session.status_code == 400
    assert delete_without_session.json() == {"error": "mcp_session_required"}


def test_invalid_requests_do_not_allocate_or_exhaust_session_capacity() -> None:
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        mcp_max_active_sessions=1,
    )
    app = create_app(settings)

    with TestClient(app, base_url="http://127.0.0.1:8787") as bounded_client:
        malformed = bounded_client.post(
            "/mcp",
            content="{",
            headers=MCP_HTTP_HEADERS,
        )
        batch = bounded_client.post(
            "/mcp",
            json=[initialize_request()],
            headers=MCP_HTTP_HEADERS,
        )
        ping = bounded_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 7, "method": "ping"},
            headers=MCP_HTTP_HEADERS,
        )
        first_session_id = initialize_http_session(bounded_client)
        at_capacity = bounded_client.post(
            "/mcp",
            json=initialize_request(),
            headers=MCP_HTTP_HEADERS,
        )
        terminated = bounded_client.delete(
            "/mcp",
            headers={
                "Authorization": AUTHORIZATION,
                "Accept": "application/json",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "MCP-Session-Id": first_session_id,
            },
        )
        replacement_session_ids = []
        for _ in range(5):
            replacement = bounded_client.post(
                "/mcp",
                json=initialize_request(),
                headers=MCP_HTTP_HEADERS,
            )
            replacement_session_id = replacement.headers["mcp-session-id"]
            replacement_session_ids.append(replacement_session_id)
            assert app.state.mcp_runtime.session_manager.active_session_count == 1
            replacement_termination = bounded_client.delete(
                "/mcp",
                headers={
                    "Authorization": AUTHORIZATION,
                    "Accept": "application/json",
                    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                    "MCP-Session-Id": replacement_session_id,
                },
            )
            assert replacement_termination.status_code == 200
            assert app.state.mcp_runtime.session_manager.active_session_count == 0

    assert malformed.status_code == 400
    assert malformed.json() == {"error": "invalid_request"}
    assert batch.status_code == 400
    assert batch.json() == {"error": "invalid_request"}
    assert ping.status_code == 400
    assert ping.json() == {"error": "mcp_session_required"}
    assert all("mcp-session-id" not in response.headers for response in (malformed, batch, ping))
    assert at_capacity.status_code == 503
    assert at_capacity.json() == {"error": "mcp_session_capacity_reached"}
    assert terminated.status_code == 200
    assert len(set(replacement_session_ids)) == 5
    assert first_session_id not in replacement_session_ids


def test_unknown_tool_is_json_rpc_protocol_error(client: TestClient) -> None:
    session_id = initialize_http_session(client)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "mac.not_registered", "arguments": {}},
        },
        headers={
            **MCP_HTTP_HEADERS,
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "MCP-Session-Id": session_id,
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert "result" not in payload
    assert payload["error"]["code"] == types.INVALID_PARAMS
    assert "unauthorized" in payload["error"]["message"].lower()


def test_mcp_rejects_invalid_transport_headers(client: TestClient) -> None:
    wrong_content_type = client.post(
        "/mcp",
        content="{}",
        headers={**MCP_HTTP_HEADERS, "Content-Type": "text/plain"},
    )
    wrong_protocol = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={**MCP_HTTP_HEADERS, "MCP-Protocol-Version": "1900-01-01"},
    )

    assert wrong_content_type.status_code == 400
    assert wrong_protocol.status_code == 400


def test_mcp_rejects_oversized_http_body(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        content=b"x" * 32_769,
        headers=MCP_HTTP_HEADERS,
    )

    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"


def test_mcp_replaces_oversized_response_with_bounded_error() -> None:
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        max_message_bytes=1_024,
    )
    registry = build_registry(settings)
    registry.register(
        replace(
            build_mac_system_tool(settings.tool_timeout_seconds),
            name="mac.system_info.secondary",
            title="Secondary Mac system information",
        )
    )
    app = create_app(settings, registry=registry)

    with TestClient(app, base_url="http://127.0.0.1:8787") as bounded_client:
        session_id = initialize_http_session(bounded_client)
        response = bounded_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={
                **MCP_HTTP_HEADERS,
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "MCP-Session-Id": session_id,
            },
        )

    assert response.status_code == 500
    assert response.json() == {"error": "response_too_large"}


@pytest.mark.asyncio
async def test_mcp_adapter_bounds_concurrent_call_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = build_registry(HubSettings())
    original_invoke_prepared = registry.invoke_prepared
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_invoke_prepared(prepared: Any) -> ToolInvocationResult:
        started.set()
        await release.wait()
        return await original_invoke_prepared(prepared)

    monkeypatch.setattr(registry, "invoke_prepared", blocking_invoke_prepared)
    adapter = RegistryMcpAdapter(
        registry,
        max_concurrent_calls=1,
        queue_timeout_seconds=0.01,
    )
    first_call = asyncio.create_task(adapter.call_tool("mac.system_info", {}))
    await asyncio.wait_for(started.wait(), timeout=1)

    try:
        with pytest.raises(McpError) as rejected:
            await adapter.call_tool("mac.system_info", {})
    finally:
        release.set()
    completed = await first_call

    assert rejected.value.error.code == types.INTERNAL_ERROR
    assert "busy" in rejected.value.error.message.lower()
    assert isinstance(completed, dict)
    assert completed["status"] == "available"


def test_stateful_mcp_validates_get_and_terminates_session(client: TestClient) -> None:
    session_id = initialize_http_session(client)
    session_headers = {
        "Authorization": AUTHORIZATION,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "MCP-Session-Id": session_id,
    }
    get_response = client.get(
        "/mcp",
        headers={**session_headers, "Accept": "application/json"},
    )
    delete_response = client.delete(
        "/mcp",
        headers=session_headers,
    )
    expired_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        headers={**MCP_HTTP_HEADERS, **session_headers},
    )

    assert get_response.status_code == 406
    assert delete_response.status_code == 200
    assert expired_response.status_code == 404


def test_mcp_get_requires_authentication_and_session(client: TestClient) -> None:
    session_id = initialize_http_session(client)
    no_token = client.get(
        "/mcp",
        headers={
            "Accept": "text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "MCP-Session-Id": session_id,
        },
    )
    no_session = client.get(
        "/mcp",
        headers={
            "Authorization": AUTHORIZATION,
            "Accept": "text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        },
    )

    assert no_token.status_code == 401
    assert no_token.json()["error"] == "invalid_token"
    assert no_session.status_code == 400
    assert no_session.json() == {"error": "mcp_session_required"}


def test_mcp_assigns_a_distinct_replay_store_to_each_session(client: TestClient) -> None:
    first_session_id = initialize_http_session(client)
    second_session_id = initialize_http_session(client)
    manager = cast(Any, client.app).state.mcp_runtime.session_manager
    first_store = manager._server_instances[first_session_id]._event_store
    second_store = manager._server_instances[second_session_id]._event_store

    assert isinstance(first_store, BoundedMcpEventStore)
    assert isinstance(second_store, BoundedMcpEventStore)
    assert first_store is not second_store


@pytest.mark.asyncio
async def test_mcp_get_recovers_unknown_cursor_and_rejects_second_stream() -> None:
    app = create_app(HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8787",
            headers={"Authorization": AUTHORIZATION},
            timeout=5,
        ) as http_client:
            initialized = await http_client.post(
                "/mcp",
                json=initialize_request(),
                headers=MCP_HTTP_HEADERS,
            )
            session_id = initialized.headers["mcp-session-id"]
            session_headers = {
                "Authorization": AUTHORIZATION,
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "MCP-Session-Id": session_id,
            }
            await http_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={**session_headers, **MCP_HTTP_HEADERS},
            )
            server_transport = app.state.mcp_runtime.session_manager._server_instances[session_id]
            initial_get_task = asyncio.create_task(http_client.get("/mcp", headers=session_headers))
            for _ in range(500):
                if GET_STREAM_KEY in server_transport._request_streams:
                    break
                await asyncio.sleep(0.01)
            assert GET_STREAM_KEY in server_transport._request_streams
            server_transport.close_standalone_sse_stream()
            initial_get = await asyncio.wait_for(initial_get_task, timeout=5)

            first_get_task = asyncio.create_task(
                http_client.get(
                    "/mcp",
                    headers={**session_headers, "Last-Event-ID": "unknown-cursor"},
                )
            )
            for _ in range(500):
                if GET_STREAM_KEY in server_transport._request_streams:
                    break
                await asyncio.sleep(0.01)
            assert GET_STREAM_KEY in server_transport._request_streams

            second_get = await http_client.get("/mcp", headers=session_headers)
            assert GET_STREAM_KEY in server_transport._request_streams
            server_transport.close_standalone_sse_stream()
            first_get = await asyncio.wait_for(first_get_task, timeout=5)

    assert initial_get.status_code == 200
    assert "id:" in initial_get.text
    assert "notifications/tools/list_changed" not in initial_get.text
    assert first_get.status_code == 200
    assert "notifications/tools/list_changed" in first_get.text
    assert "unknown-cursor" not in first_get.text
    assert second_get.status_code == 409


@pytest.mark.asyncio
async def test_active_mcp_get_keeps_session_alive_past_idle_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server_module, "MCP_SESSION_IDLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(mcp_server_module, "MCP_SSE_MAX_LIFETIME_SECONDS", 0.2)
    app = create_app(HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8787",
                headers={"Authorization": AUTHORIZATION},
                timeout=5,
            ) as http_client,
            streamable_http_client(
                "http://127.0.0.1:8787/mcp",
                http_client=http_client,
            ) as (read_stream, write_stream, get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            initial = await session.list_tools()
            session_id = get_session_id()
            assert session_id is not None
            server_transport = app.state.mcp_runtime.session_manager._server_instances[session_id]
            for _ in range(500):
                if GET_STREAM_KEY in server_transport._request_streams:
                    break
                await asyncio.sleep(0.01)
            assert GET_STREAM_KEY in server_transport._request_streams

            await asyncio.sleep(0.1)
            after_idle_deadline = await session.list_tools()

    assert [tool.name for tool in initial.tools] == [
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]
    assert [tool.name for tool in after_idle_deadline.tools] == [
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]


@pytest.mark.asyncio
async def test_mcp_get_rotates_at_bounded_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server_module, "MCP_SSE_MAX_LIFETIME_SECONDS", 0.05)
    app = create_app(HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8787",
            headers={"Authorization": AUTHORIZATION},
            timeout=5,
        ) as http_client:
            initialized = await http_client.post(
                "/mcp",
                json=initialize_request(),
                headers=MCP_HTTP_HEADERS,
            )
            session_id = initialized.headers["mcp-session-id"]
            session_headers = {
                "Authorization": AUTHORIZATION,
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "MCP-Session-Id": session_id,
            }
            await http_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers={**session_headers, **MCP_HTTP_HEADERS},
            )
            rotated = await asyncio.wait_for(
                http_client.get("/mcp", headers=session_headers),
                timeout=1,
            )
            listed = await http_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers={**session_headers, **MCP_HTTP_HEADERS},
            )

    assert rotated.status_code == 200
    assert "id:" in rotated.text
    assert listed.status_code == 200
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == [
        "goffy.rom.status",
        "mac.processes.list",
        "mac.system_info",
    ]


@pytest.mark.asyncio
async def test_mcp_replay_store_replays_only_bounded_session_local_list_changes() -> None:
    first_store = BoundedMcpEventStore(max_events=2, max_bytes=1_024)
    second_store = BoundedMcpEventStore(max_events=2, max_bytes=1_024)
    notification = tool_list_changed_message()
    priming_id = await first_store.store_event(GET_STREAM_KEY, None)
    first_notification_id = await first_store.store_event(GET_STREAM_KEY, notification)
    await first_store.store_event("request-7", notification)
    replayed: list[EventMessage] = []

    async def capture_replay(event: EventMessage) -> None:
        replayed.append(event)

    stream_id = await first_store.replay_events_after(priming_id, capture_replay)
    isolated = await second_store.replay_events_after(first_notification_id, capture_replay)
    await first_store.store_event(GET_STREAM_KEY, notification)
    evicted = await first_store.replay_events_after(priming_id, capture_replay)

    assert stream_id == GET_STREAM_KEY
    assert isolated == GET_STREAM_KEY
    assert evicted == GET_STREAM_KEY
    assert len(replayed) == 4
    assert replayed[0].event_id == first_notification_id
    assert all(
        isinstance(event.message.root, types.JSONRPCNotification)
        and event.message.root.method == "notifications/tools/list_changed"
        for event in replayed
    )


@pytest.mark.asyncio
async def test_mcp_notifier_quarantines_stalled_session_without_blocking_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_server_module, "MCP_NOTIFICATION_TIMEOUT_SECONDS", 0.01)
    notifier = McpToolListNotifier()

    class StubSession:
        def __init__(self, *, stalls: bool) -> None:
            self.calls = 0
            self.stalls = stalls

        async def send_tool_list_changed(self) -> None:
            self.calls += 1
            if self.stalls:
                await asyncio.Event().wait()

    healthy = StubSession(stalls=False)
    stalled = StubSession(stalls=True)
    await notifier.register("healthy", cast(Any, healthy))
    await notifier.register("stalled", cast(Any, stalled))

    await notifier.notify({"healthy", "stalled"})
    await notifier.notify({"healthy", "stalled"})

    assert healthy.calls == 2
    assert stalled.calls == 1


def test_terminal_mcp_mount_closes_unmatched_websocket(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect("/not-found"):
        pass

    assert error.value.code == 1008
