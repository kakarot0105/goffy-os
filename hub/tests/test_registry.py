import asyncio
from dataclasses import replace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, create_model

from goffy_hub.app import build_registry
from goffy_hub.registry import (
    MAX_CONCURRENT_HEALTH_PROBES,
    MAX_REGISTERED_TOOLS,
    MAX_TOOL_OUTPUT_BYTES,
    ToolArgumentsError,
    ToolDefinition,
    ToolExecutionError,
    ToolHealthStatus,
    ToolNotFoundError,
    ToolRegistry,
    ToolUnavailableError,
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


async def healthy_probe() -> bool:
    return True


async def oversized_output_handler(_request: BaseModel) -> dict[str, object]:
    return {"value": "x" * (MAX_TOOL_OUTPUT_BYTES + 1)}


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
        health_probe=healthy_probe,
        health_timeout_seconds=1.0,
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
    assert len(tools) == 2
    tool = next(item for item in tools if item["name"] == "mac.system_info")
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
                annotations=ToolAnnotations.model_construct(  # type: ignore[call-arg]
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
                annotations=ToolAnnotations.model_construct(  # type: ignore[call-arg]
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


def test_registry_rejects_more_than_configured_tool_limit() -> None:
    registry = ToolRegistry()

    for index in range(MAX_REGISTERED_TOOLS):
        registry.register(build_test_tool(name=f"tool.{index}"))

    with pytest.raises(
        ValueError,
        match=rf"cannot exceed {MAX_REGISTERED_TOOLS} tools",
    ):
        registry.register(build_test_tool(name="tool.overflow"))


def test_registry_rejects_oversized_capability_metadata() -> None:
    large_fields: dict[str, Any] = {f"field_{index}": (str, ...) for index in range(600)}
    large_input = create_model(
        "LargeInput",
        __config__=ConfigDict(extra="forbid", strict=True),
        **large_fields,
    )
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="capability exceeds the metadata size limit"):
        registry.register(
            ToolDefinition(
                name="test.large_metadata",
                title="Large metadata",
                description="Exercise the capability metadata boundary.",
                tool_version="1.0.0",
                permission=PermissionLevel.SAFE,
                execution_target=ExecutionTarget.MAC,
                timeout_seconds=1,
                input_model=large_input,
                output_model=EmptyOutput,
                handler=successful_handler,
                health_probe=healthy_probe,
                health_timeout_seconds=1.0,
                annotations=ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            )
        )


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
            health_probe=healthy_probe,
            health_timeout_seconds=1.0,
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


@pytest.mark.asyncio
async def test_registry_rejects_oversized_structured_output() -> None:
    class LargeOutput(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)

        value: str

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.large_output",
            title="Large output test",
            description="Exercise the structured output boundary.",
            tool_version="1.0.0",
            permission=PermissionLevel.SAFE,
            execution_target=ExecutionTarget.MAC,
            timeout_seconds=1,
            input_model=EmptyInput,
            output_model=LargeOutput,
            handler=oversized_output_handler,
            health_probe=healthy_probe,
            health_timeout_seconds=1.0,
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    )

    with pytest.raises(ToolExecutionError, match="output_too_large"):
        await registry.invoke("test.large_output", {})


@pytest.mark.asyncio
async def test_health_transition_hides_rejects_and_restores_registered_tool() -> None:
    healthy = True

    async def probe() -> bool:
        return healthy

    registry = ToolRegistry()
    registry.register(replace(build_test_tool(), health_probe=probe))
    registry.seal()

    initial = await registry.refresh_health()
    healthy = False
    unavailable = await registry.refresh_health()
    unchanged = await registry.refresh_health()

    assert initial.changed is True
    assert unavailable.changed is True
    assert unavailable.revision == 2
    assert unavailable.available_tool_names == ()
    assert unavailable.tools[0].status is ToolHealthStatus.UNAVAILABLE
    assert unchanged.changed is False
    assert unchanged.revision == 2
    assert registry.describe() == []
    assert registry.discover("test.tool") == []
    with pytest.raises(ToolUnavailableError):
        await registry.invoke("test.tool", {})

    healthy = True
    restored = await registry.refresh_health()

    assert restored.changed is True
    assert restored.revision == 3
    assert restored.available_tool_names == ("test.tool",)
    assert restored.tools[0].status is ToolHealthStatus.HEALTHY
    assert (await registry.invoke("test.tool", {})).structured_content == {"ok": True}


@pytest.mark.asyncio
async def test_health_change_does_not_revoke_prepared_invocation() -> None:
    registry = ToolRegistry()
    registry.register(build_test_tool())
    registry.seal()
    await registry.refresh_health()
    prepared = registry.preflight("test.tool", {})

    await registry.mark_all_unavailable()
    result = await registry.invoke_prepared(prepared)

    assert result.structured_content == {"ok": True}
    with pytest.raises(ToolUnavailableError):
        registry.preflight("test.tool", {})


@pytest.mark.asyncio
async def test_health_timeout_exception_and_non_boolean_fail_closed() -> None:
    async def timeout_probe() -> bool:
        await asyncio.sleep(1)
        return True

    async def exception_probe() -> bool:
        raise RuntimeError("sensitive health detail")

    async def non_boolean_probe() -> bool:
        return 1  # type: ignore[return-value]

    registry = ToolRegistry()
    registry.register(
        replace(
            build_test_tool(name="health.timeout"),
            health_probe=timeout_probe,
            health_timeout_seconds=0.01,
        )
    )
    registry.register(
        replace(build_test_tool(name="health.exception"), health_probe=exception_probe)
    )
    registry.register(
        replace(build_test_tool(name="health.non_boolean"), health_probe=non_boolean_probe)
    )

    report = await registry.refresh_health()

    assert report.changed is True
    assert report.available_tool_names == ()
    assert {snapshot.status for snapshot in report.tools} == {ToolHealthStatus.UNAVAILABLE}


@pytest.mark.asyncio
async def test_health_probe_concurrency_is_bounded() -> None:
    active = 0
    maximum_active = 0
    release = asyncio.Event()

    async def probe() -> bool:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        if active == MAX_CONCURRENT_HEALTH_PROBES:
            release.set()
        await release.wait()
        active -= 1
        return True

    registry = ToolRegistry()
    for index in range(MAX_CONCURRENT_HEALTH_PROBES * 2):
        registry.register(replace(build_test_tool(name=f"health.{index}"), health_probe=probe))

    report = await registry.refresh_health()

    assert report.changed is False
    assert maximum_active == MAX_CONCURRENT_HEALTH_PROBES


def test_registry_seal_and_health_timeout_bounds_fail_closed() -> None:
    registry = ToolRegistry()
    registry.register(build_test_tool())
    registry.seal()

    with pytest.raises(RuntimeError, match="sealed"):
        registry.register(build_test_tool(name="test.late"))
    with pytest.raises(ValueError, match="health timeout"):
        ToolRegistry().register(replace(build_test_tool(), health_timeout_seconds=0))
    with pytest.raises(ValueError, match="health timeout"):
        ToolRegistry().register(replace(build_test_tool(), health_timeout_seconds=5.1))
