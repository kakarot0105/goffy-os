from __future__ import annotations

import platform
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel


class MacSystemInfoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MacSystemInfoOutput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    status: str
    operating_system: str
    architecture: str


async def read_mac_system_info(_request: BaseModel) -> dict[str, Any]:
    return {
        "status": "available",
        "operating_system": platform.system(),
        "architecture": platform.machine(),
    }


def build_mac_system_tool(timeout_seconds: float) -> ToolDefinition:
    return ToolDefinition(
        name="mac.system_info",
        title="Mac system information",
        description="Read a minimal, non-sensitive snapshot of the Hub host.",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacSystemInfoInput,
        output_model=MacSystemInfoOutput,
        handler=read_mac_system_info,
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
