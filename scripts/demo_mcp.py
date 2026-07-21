from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from goffy_hub.tools.mac_system import MacSystemInfoOutput
from goffy_protocol import MCP_PROTOCOL_VERSION

MCP_URL = "http://127.0.0.1:8787/mcp"


async def demo() -> None:
    token = os.environ.get("GOFFY_HUB_TOKEN")
    if not token:
        raise SystemExit("Set GOFFY_HUB_TOKEN before running the demo.")

    async with AsyncExitStack() as stack:
        http_client = await stack.enter_async_context(
            httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
        )
        read_stream, write_stream, get_session_id = await stack.enter_async_context(
            streamable_http_client(
                MCP_URL,
                http_client=http_client,
                terminate_on_close=False,
            )
        )
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        initialization = await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("mac.system_info", {})

        session_id = get_session_id()
        if session_id is None:
            raise RuntimeError("Hub did not issue an MCP session ID")
        termination = await http_client.delete(
            MCP_URL,
            headers={
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "MCP-Session-Id": session_id,
            },
        )
        if termination.status_code != 200:
            raise RuntimeError("Hub did not terminate the MCP session")

    if initialization.protocolVersion != MCP_PROTOCOL_VERSION:
        raise RuntimeError("Hub negotiated an unsupported MCP protocol version")
    tool_names = sorted(tool.name for tool in tools.tools)
    if "mac.system_info" not in tool_names:
        raise RuntimeError("Hub did not expose the required mac.system_info tool")
    if result.isError or result.structuredContent is None:
        raise RuntimeError("mac.system_info returned an MCP tool error")

    output = MacSystemInfoOutput.model_validate(result.structuredContent)
    print(
        json.dumps(
            {
                "protocolVersion": initialization.protocolVersion,
                "tools": tool_names,
                "result": output.model_dump(mode="json", by_alias=True),
                "sessionTerminated": True,
                "verified": output.status == "available",
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(demo())
