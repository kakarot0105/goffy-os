from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from goffy_protocol import (
    ExecutionTarget,
    GoffyToolMetadata,
    PermissionLevel,
    ToolAnnotations,
    ToolCapability,
    normalize_json_schema,
)

ToolHandler = Callable[[BaseModel], Awaitable[dict[str, Any]]]
MAX_REGISTERED_TOOLS = 32
MAX_TOOL_CAPABILITY_BYTES = 8_192
MAX_REGISTRY_CAPABILITY_BYTES = 24_576
MAX_TOOL_OUTPUT_BYTES = 8_192


class ToolRegistryError(Exception):
    """Base class for errors safe to map to stable client error codes."""


class ToolNotFoundError(ToolRegistryError):
    pass


class ToolArgumentsError(ToolRegistryError):
    pass


class ToolExecutionError(ToolRegistryError):
    pass


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    tool_version: str
    permission: PermissionLevel
    execution_target: ExecutionTarget
    timeout_seconds: float
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    annotations: ToolAnnotations

    def describe(self) -> ToolCapability:
        return ToolCapability(
            name=self.name,
            title=self.title,
            description=self.description,
            input_schema=normalize_json_schema(self.input_model.model_json_schema(by_alias=True)),
            output_schema=normalize_json_schema(self.output_model.model_json_schema(by_alias=True)),
            annotations=self.annotations,
            meta=GoffyToolMetadata(
                tool_version=self.tool_version,
                execution_target=self.execution_target,
                permission=self.permission,
                timeout_ms=int(self.timeout_seconds * 1_000),
            ),
        )


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    definition: ToolDefinition
    structured_content: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._capabilities: dict[str, ToolCapability] = {}
        self._capability_bytes = 0

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        if len(self._tools) >= MAX_REGISTERED_TOOLS:
            raise ValueError(f"tool registry cannot exceed {MAX_REGISTERED_TOOLS} tools")
        if definition.permission is PermissionLevel.BLOCKED:
            raise ValueError("blocked tools cannot be registered")
        if definition.permission is not PermissionLevel.SAFE:
            raise ValueError("non-SAFE tools require an authorization policy before registration")
        try:
            capability = definition.describe()
        except (ValidationError, ValueError) as error:
            raise ValueError("tool metadata is invalid") from error
        if capability.annotations.read_only_hint is not True:
            raise ValueError("SAFE tools must declare readOnlyHint=true")
        if capability.annotations.destructive_hint is not False:
            raise ValueError("SAFE tools must declare destructiveHint=false")
        if capability.annotations.idempotent_hint is not True:
            raise ValueError("SAFE tools must declare idempotentHint=true")
        if capability.annotations.open_world_hint is not False:
            raise ValueError("SAFE tools must declare openWorldHint=false")
        capability_bytes = len(
            capability.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
        )
        if capability_bytes > MAX_TOOL_CAPABILITY_BYTES:
            raise ValueError("tool capability exceeds the metadata size limit")
        if self._capability_bytes + capability_bytes > MAX_REGISTRY_CAPABILITY_BYTES:
            raise ValueError("tool registry exceeds the metadata size limit")
        self._tools[definition.name] = definition
        self._capabilities[definition.name] = capability
        self._capability_bytes += capability_bytes

    def describe(self) -> list[ToolCapability]:
        return [
            self._capabilities[name].model_copy(deep=True) for name in sorted(self._capabilities)
        ]

    def discover(self, name: str) -> list[ToolCapability]:
        capability = self._capabilities.get(name)
        return [capability.model_copy(deep=True)] if capability is not None else []

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolInvocationResult:
        definition = self._tools.get(name)
        if definition is None:
            raise ToolNotFoundError(name)

        try:
            parsed_input = definition.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ToolArgumentsError(name) from error

        try:
            raw_output = await asyncio.wait_for(
                definition.handler(parsed_input),
                timeout=definition.timeout_seconds,
            )
            output = definition.output_model.model_validate(raw_output)
        except TimeoutError as error:
            raise ToolExecutionError("timeout") from error
        except ValidationError as error:
            raise ToolExecutionError("invalid_output") from error
        except Exception as error:
            raise ToolExecutionError("handler_failure") from error

        structured_content = output.model_dump(mode="json", by_alias=True)
        try:
            output_bytes = len(
                json.dumps(
                    structured_content,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as error:  # pragma: no cover - Pydantic JSON mode is safe
            raise ToolExecutionError("invalid_output") from error
        if output_bytes > MAX_TOOL_OUTPUT_BYTES:
            raise ToolExecutionError("output_too_large")

        return ToolInvocationResult(
            definition=definition,
            structured_content=structured_content,
        )
