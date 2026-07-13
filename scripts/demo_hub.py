from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

from websockets.asyncio.client import connect

from goffy_protocol import (
    PROTOCOL_VERSION,
    MessageEnvelope,
    MessageType,
    ToolInvocationPayload,
)


async def demo() -> None:
    token = os.environ.get("GOFFY_HUB_TOKEN")
    if not token:
        raise SystemExit("Set GOFFY_HUB_TOKEN before running the demo.")

    request = MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="demo-client",
        message_type=MessageType.TOOL_INVOCATION,
        payload=ToolInvocationPayload(tool_name="mac.system_info").model_dump(
            mode="json", by_alias=True
        ),
    )

    async with connect(
        "ws://127.0.0.1:8787/ws/v1",
        additional_headers={"Authorization": f"Bearer {token}"},
    ) as socket:
        await socket.send(request.model_dump_json(by_alias=True))
        for _ in range(4):
            event = MessageEnvelope.model_validate_json(await socket.recv())
            print(event.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    asyncio.run(demo())
