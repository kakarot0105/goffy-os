from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from goffy_protocol import ExecutionTarget, PermissionLevel

ToolHandler = Callable[[BaseModel], Awaitable[dict[str, Any]]]


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
    permission: PermissionLevel
    execution_target: ExecutionTarget
    timeout_seconds: float
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    annotations: dict[str, bool]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "permission": self.permission.value,
            "executionTarget": self.execution_target.value,
            "timeoutMs": int(self.timeout_seconds * 1_000),
            "inputSchema": self.input_model.model_json_schema(),
            "outputSchema": self.output_model.model_json_schema(by_alias=True),
            "annotations": self.annotations,
        }


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    definition: ToolDefinition
    structured_content: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        if definition.permission is PermissionLevel.BLOCKED:
            raise ValueError("blocked tools cannot be registered")
        self._tools[definition.name] = definition

    def describe(self) -> list[dict[str, Any]]:
        return [self._tools[name].describe() for name in sorted(self._tools)]

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

        return ToolInvocationResult(
            definition=definition,
            structured_content=output.model_dump(mode="json", by_alias=True),
        )
