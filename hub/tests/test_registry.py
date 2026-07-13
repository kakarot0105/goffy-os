import pytest
from pydantic import BaseModel, ConfigDict

from goffy_hub.app import build_registry
from goffy_hub.registry import (
    MAX_REGISTERED_TOOLS,
    ToolArgumentsError,
    ToolDefinition,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
)
from goffy_hub.settings import HubSettings
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ok: bool


async def failing_handler(_request: BaseModel) -> dict[str, object]:
    raise RuntimeError("internal implementation detail")


async def successful_handler(_request: BaseModel) -> dict[str, object]:
    return {"ok": True}


def build_test_tool(
    *,
    name: str = "test.tool",
    tool_version: str = "1.0.0",
    permission: PermissionLevel = PermissionLevel.SAFE,
    annotations: ToolAnnotations | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        title=f"{name} title",
        description=f"{name} description",
        tool_version=tool_version,
        permission=permission,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=1.0,
        input_model=EmptyInput,
        output_model=EmptyOutput,
        handler=successful_handler,
        annotations=annotations
        or ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )


def test_registry_exposes_mcp_shaped_metadata() -> None:
    registry = build_registry(HubSettings())

    tools = [
        tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in registry.describe()
    ]
    assert len(tools) == 1
    tool = tools[0]
    assert set(tool) == {
        "name",
        "title",
        "description",
        "inputSchema",
        "outputSchema",
        "annotations",
        "_meta",
    }
    assert tool["name"] == "mac.system_info"
    assert tool["inputSchema"] == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {},
        "type": "object",
    }
    assert tool["outputSchema"] == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "architecture": {"type": "string"},
            "operatingSystem": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["status", "operatingSystem", "architecture"],
        "type": "object",
    }
    assert tool["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert tool["_meta"] == {
        "dev.goffy/toolVersion": "1.0.0",
        "dev.goffy/executionTarget": "MAC",
        "dev.goffy/permission": "SAFE",
        "dev.goffy/timeoutMs": 3000,
    }


def test_registry_describe_is_sorted_and_discover_filters_by_name() -> None:
    registry = ToolRegistry()
    registry.register(build_test_tool(name="zeta.tool"))
    registry.register(build_test_tool(name="alpha.tool"))

    assert [tool.name for tool in registry.describe()] == ["alpha.tool", "zeta.tool"]
    assert [tool.name for tool in registry.discover("alpha.tool")] == ["alpha.tool"]
    assert registry.discover("missing.tool") == []


def test_registry_descriptions_cannot_mutate_cached_capabilities() -> None:
    registry = ToolRegistry()
    registry.register(build_test_tool())

    described = registry.describe()[0]
    described.meta.timeout_ms = 29_999

    assert registry.discover("test.tool")[0].meta.timeout_ms == 1_000


def test_registry_rejects_duplicate_and_blocked_registrations() -> None:
    registry = ToolRegistry()
    definition = build_test_tool()
    registry.register(definition)

    with pytest.raises(ValueError, match="tool already registered"):
        registry.register(definition)

    with pytest.raises(ValueError, match="blocked tools cannot be registered"):
        registry.register(build_test_tool(name="blocked.tool", permission=PermissionLevel.BLOCKED))

    with pytest.raises(ValueError, match="non-SAFE tools require an authorization policy"):
        registry.register(build_test_tool(name="confirm.tool", permission=PermissionLevel.CONFIRM))


def test_registry_rejects_invalid_metadata_and_annotation_combinations() -> None:
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="tool metadata is invalid"):
        registry.register(build_test_tool(tool_version="1.0"))

    with pytest.raises(ValueError, match="tool metadata is invalid"):
        registry.register(
            build_test_tool(
                name="invalid.annotations",
                annotations=ToolAnnotations.model_construct(
                    read_only_hint=True,
                    destructive_hint=True,
                ),
            )
        )

    with pytest.raises(ValueError, match="SAFE tools must declare readOnlyHint=true"):
        registry.register(
            build_test_tool(
                name="unsafe.annotations",
                annotations=ToolAnnotations(
                    read_only_hint=False,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            )
        )

    with pytest.raises(ValueError, match="tool metadata is invalid"):
        registry.register(
            build_test_tool(
                name="missing.annotation",
                annotations=ToolAnnotations.model_construct(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                ),
            )
        )

    with pytest.raises(ValueError, match="SAFE tools must declare idempotentHint=true"):
        registry.register(
            build_test_tool(
                name="non.idempotent",
                annotations=ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=False,
                    open_world_hint=False,
                ),
            )
        )

    with pytest.raises(ValueError, match="SAFE tools must declare openWorldHint=false"):
        registry.register(
            build_test_tool(
                name="open.world",
                annotations=ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=True,
                ),
            )
        )


def test_registry_rejects_more_than_sixty_four_tools() -> None:
    registry = ToolRegistry()

    for index in range(MAX_REGISTERED_TOOLS):
        registry.register(build_test_tool(name=f"tool.{index}"))

    with pytest.raises(ValueError, match="cannot exceed 64 tools"):
        registry.register(build_test_tool(name="tool.overflow"))


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
            tool_version="1.0.0",
            permission=PermissionLevel.SAFE,
            execution_target=ExecutionTarget.MAC,
            timeout_seconds=1,
            input_model=EmptyInput,
            output_model=EmptyOutput,
            handler=failing_handler,
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )

    with pytest.raises(ToolExecutionError, match="handler_failure"):
        await registry.invoke("test.failure", {})
