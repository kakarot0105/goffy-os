from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

from websockets.asyncio.client import connect

from goffy_protocol import (
    PROTOCOL_VERSION,
    CapabilityDiscoveryRequestPayload,
    CapabilityDiscoveryResponsePayload,
    MessageEnvelope,
    MessageType,
    ToolInvocationPayload,
)


async def demo() -> None:
    token = os.environ.get("GOFFY_HUB_TOKEN")
    if not token:
        raise SystemExit("Set GOFFY_HUB_TOKEN before running the demo.")

    discovery = MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="demo-client",
        message_type=MessageType.CAPABILITY_DISCOVERY_REQUEST,
        payload=CapabilityDiscoveryRequestPayload(tool_name="mac.system_info").model_dump(
            mode="json", by_alias=True
        ),
    )
    invocation = MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="demo-client",
        message_type=MessageType.TOOL_INVOCATION,
        payload=ToolInvocationPayload(tool_name="mac.system_info", arguments={}).model_dump(
            mode="json", by_alias=True
        ),
    )

    async with connect(
        "ws://127.0.0.1:8787/ws/v1",
        additional_headers={"Authorization": f"Bearer {token}"},
    ) as socket:
        await socket.send(discovery.model_dump_json(by_alias=True))
        discovery_response = MessageEnvelope.model_validate_json(await socket.recv())
        if (
            discovery_response.message_type is not MessageType.CAPABILITY_DISCOVERY_RESPONSE
            or discovery_response.correlation_id != discovery.message_id
        ):
            raise RuntimeError("Hub returned an invalid discovery response")
        capabilities = CapabilityDiscoveryResponsePayload.model_validate(discovery_response.payload)
        if len(capabilities.tools) != 1 or capabilities.tools[0].name != "mac.system_info":
            raise RuntimeError("Hub does not expose a compatible mac.system_info capability")
        print(discovery_response.model_dump_json(by_alias=True, indent=2))

        await socket.send(invocation.model_dump_json(by_alias=True))
        for _ in range(4):
            event = MessageEnvelope.model_validate_json(await socket.recv())
            print(event.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    asyncio.run(demo())
