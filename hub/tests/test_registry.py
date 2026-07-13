import pytest
from pydantic import BaseModel, ConfigDict

from goffy_hub.app import build_registry
from goffy_hub.registry import (
    ToolArgumentsError,
    ToolDefinition,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)
from goffy_hub.settings import HubSettings
from goffy_protocol import ExecutionTarget, PermissionLevel


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyOutput(BaseModel):
    ok: bool


async def failing_handler(_request: BaseModel) -> dict[str, object]:
    raise RuntimeError("internal implementation detail")


def test_registry_exposes_mcp_shaped_metadata() -> None:
    registry = build_registry(HubSettings())

    tools = registry.describe()
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "mac.system_info"
    assert tool["permission"] == "SAFE"
    assert tool["executionTarget"] == "MAC"
    assert tool["timeoutMs"] == 3000
    assert tool["inputSchema"]["additionalProperties"] is False
    assert tool["outputSchema"]["additionalProperties"] is False
    assert set(tool["outputSchema"]["required"]) == {
        "status",
        "operatingSystem",
        "architecture",
    }
    assert tool["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


@pytest.mark.asyncio
async def test_registry_rejects_unknown_tool() -> None:
    registry = build_registry(HubSettings())

    with pytest.raises(ToolNotFoundError):
        await registry.invoke("mac.not_registered", {})


@pytest.mark.asyncio
async def test_registry_rejects_extra_arguments() -> None:
    registry = build_registry(HubSettings())

    with pytest.raises(ToolArgumentsError):
        await registry.invoke("mac.system_info", {"command": "whoami"})


@pytest.mark.asyncio
async def test_registry_contains_unexpected_handler_failure() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.failure",
            title="Failure test",
            description="Exercise the failure boundary.",
            permission=PermissionLevel.SAFE,
            execution_target=ExecutionTarget.MAC,
            timeout_seconds=1,
            input_model=EmptyInput,
            output_model=EmptyOutput,
            handler=failing_handler,
            annotations={},
        )
    )

    with pytest.raises(ToolExecutionError, match="handler_failure"):
        await registry.invoke("test.failure", {})
