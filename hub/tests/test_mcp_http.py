from __future__ import annotations

import asyncio
import json
import platform
from dataclasses import replace
from typing import Any

import httpx
import pytest
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from pydantic import SecretStr
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from goffy_hub.app import build_registry, create_app
from goffy_hub.mcp_server import RegistryMcpAdapter
from goffy_hub.registry import ToolInvocationResult
from goffy_hub.settings import HubSettings
from goffy_hub.tools import build_mac_system_tool
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
            with pytest.raises(McpError) as unknown_error:
                await session.call_tool("mac.not_registered", {})

    assert initialization.protocolVersion == MCP_PROTOCOL_VERSION
    assert initialization.capabilities.tools is not None
    assert initialization.capabilities.tools.listChanged is False
    assert get_session_id() is not None
    assert len(listed.tools) == 1
    tool = listed.tools[0]
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
    assert isinstance(result.content[0], types.TextContent)
    assert json.loads(result.content[0].text) == result.structuredContent
    assert unknown_error.value.error.code == types.INVALID_PARAMS
    assert "unauthorized" in unknown_error.value.error.message.lower()


@pytest.mark.asyncio
async def test_official_client_relists_after_tool_health_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
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
            ) as (read_stream, write_stream, _get_session_id),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialization = await session.initialize()
            initial_tools = await session.list_tools()
            monkeypatch.setattr(platform, "system", lambda: "")

            unavailable = await app.state.tool_health_monitor.check_now()
            unavailable_tools = await session.list_tools()
            with pytest.raises(McpError) as unavailable_call:
                await session.call_tool("mac.system_info", {})
            monkeypatch.setattr(platform, "system", lambda: "Darwin")

            restored = await app.state.tool_health_monitor.check_now()
            restored_tools = await session.list_tools()

    assert initialization.capabilities.tools is not None
    assert initialization.capabilities.tools.listChanged is False
    assert [tool.name for tool in initial_tools.tools] == ["mac.system_info"]
    assert unavailable.changed is True
    assert unavailable_tools.tools == []
    assert unavailable_call.value.error.code == types.INVALID_PARAMS
    assert "unauthorized" in unavailable_call.value.error.message.lower()
    assert restored.changed is True
    assert [tool.name for tool in restored_tools.tools] == ["mac.system_info"]


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


def test_mcp_uses_exact_non_redirecting_endpoint(client: TestClient) -> None:
    response = client.post("/mcp", json=initialize_request(), headers=MCP_HTTP_HEADERS)
    trailing_slash = client.post("/mcp/", json=initialize_request(), headers=MCP_HTTP_HEADERS)

    assert response.status_code == 200
    assert "location" not in response.headers
    payload = response.json()
    assert payload["id"] == 1
    assert payload["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert payload["result"]["capabilities"]["tools"] == {"listChanged": False}
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
    original_invoke = registry.invoke
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_invoke(name: str, arguments: dict[str, Any]) -> ToolInvocationResult:
        started.set()
        await release.wait()
        return await original_invoke(name, arguments)

    monkeypatch.setattr(registry, "invoke", blocking_invoke)
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


def test_stateful_mcp_declines_get_and_terminates_session(client: TestClient) -> None:
    session_id = initialize_http_session(client)
    session_headers = {
        "Authorization": AUTHORIZATION,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "MCP-Session-Id": session_id,
    }
    get_response = client.get("/mcp", headers=session_headers)
    delete_response = client.delete(
        "/mcp",
        headers=session_headers,
    )
    expired_response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        headers={**MCP_HTTP_HEADERS, **session_headers},
    )

    assert get_response.status_code == 405
    assert get_response.headers["allow"] == "POST, DELETE"
    assert delete_response.status_code == 200
    assert expired_response.status_code == 404


def test_terminal_mcp_mount_closes_unmatched_websocket(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect("/not-found"):
        pass

    assert error.value.code == 1008
