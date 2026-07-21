from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from enum import StrEnum
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
ToolHealthProbe = Callable[[], Awaitable[bool]]
MAX_REGISTERED_TOOLS = 32
MAX_TOOL_CAPABILITY_BYTES = 8_192
MAX_REGISTRY_CAPABILITY_BYTES = 24_576
MAX_TOOL_OUTPUT_BYTES = 8_192
MAX_CONCURRENT_HEALTH_PROBES = 4
MAX_TOOL_HEALTH_TIMEOUT_SECONDS = 5.0


class ToolRegistryError(Exception):
    """Base class for errors safe to map to stable client error codes."""


class ToolNotFoundError(ToolRegistryError):
    pass


class ToolUnavailableError(ToolNotFoundError):
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
    health_probe: ToolHealthProbe
    health_timeout_seconds: float
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


@dataclass(frozen=True, slots=True)
class PreparedToolInvocation:
    definition: ToolDefinition
    parsed_input: BaseModel


class ToolHealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ToolHealthSnapshot:
    name: str
    status: ToolHealthStatus


@dataclass(frozen=True, slots=True)
class ToolHealthReport:
    revision: int
    changed: bool
    available_tool_names: tuple[str, ...]
    tools: tuple[ToolHealthSnapshot, ...]


class ToolRegistry:
    def __init__(self, *, confirm_tool_names: Collection[str] = ()) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._capabilities: dict[str, ToolCapability] = {}
        self._healthy: dict[str, bool] = {}
        self._confirm_tool_names = frozenset(confirm_tool_names)
        self._capability_bytes = 0
        self._health_revision = 0
        self._health_lock = asyncio.Lock()
        self._sealed = False

    def register(self, definition: ToolDefinition) -> None:
        if self._sealed:
            raise RuntimeError("tool registry is sealed")
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        if len(self._tools) >= MAX_REGISTERED_TOOLS:
            raise ValueError(f"tool registry cannot exceed {MAX_REGISTERED_TOOLS} tools")
        if definition.permission is PermissionLevel.BLOCKED:
            raise ValueError("blocked tools cannot be registered")
        if definition.permission is PermissionLevel.SAFE:
            self._validate_safe_definition(definition)
        elif definition.permission is PermissionLevel.CONFIRM:
            self._validate_confirm_definition(definition)
        else:
            raise ValueError("sensitive tools cannot be registered")
        if not 0 < definition.health_timeout_seconds <= MAX_TOOL_HEALTH_TIMEOUT_SECONDS:
            raise ValueError(
                f"tool health timeout must be at most {MAX_TOOL_HEALTH_TIMEOUT_SECONDS:g} seconds"
            )
        try:
            capability = definition.describe()
        except (ValidationError, ValueError) as error:
            raise ValueError("tool metadata is invalid") from error
        capability_bytes = len(
            capability.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8")
        )
        if capability_bytes > MAX_TOOL_CAPABILITY_BYTES:
            raise ValueError("tool capability exceeds the metadata size limit")
        if self._capability_bytes + capability_bytes > MAX_REGISTRY_CAPABILITY_BYTES:
            raise ValueError("tool registry exceeds the metadata size limit")
        self._tools[definition.name] = definition
        self._capabilities[definition.name] = capability
        self._healthy[definition.name] = True
        self._capability_bytes += capability_bytes

    def seal(self) -> None:
        if self._sealed:
            return
        self._healthy = dict.fromkeys(self._tools, False)
        self._sealed = True

    @property
    def is_sealed(self) -> bool:
        return self._sealed

    def describe(
        self,
        *,
        permissions: frozenset[PermissionLevel] | None = None,
    ) -> list[ToolCapability]:
        return [
            self._capabilities[name].model_copy(deep=True)
            for name in sorted(self._capabilities)
            if self._healthy[name]
            and (permissions is None or self._tools[name].permission in permissions)
        ]

    def discover(
        self,
        name: str,
        *,
        permissions: frozenset[PermissionLevel] | None = None,
    ) -> list[ToolCapability]:
        capability = self._capabilities.get(name)
        return (
            [capability.model_copy(deep=True)]
            if capability is not None
            and self._healthy[name]
            and (permissions is None or self._tools[name].permission in permissions)
            else []
        )

    def health_report(self) -> ToolHealthReport:
        return self._build_health_report(changed=False)

    async def refresh_health(self) -> ToolHealthReport:
        async with self._health_lock:
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_HEALTH_PROBES)

            async def check(definition: ToolDefinition) -> tuple[str, bool]:
                async with semaphore:
                    try:
                        healthy = await asyncio.wait_for(
                            definition.health_probe(),
                            timeout=definition.health_timeout_seconds,
                        )
                    except TimeoutError:
                        healthy = False
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        healthy = False
                return definition.name, healthy is True

            results = await asyncio.gather(
                *(check(self._tools[name]) for name in sorted(self._tools))
            )
            previous_available = self._available_tool_names()
            self._healthy.update(results)
            changed = previous_available != self._available_tool_names()
            if changed:
                self._health_revision += 1
            return self._build_health_report(changed=changed)

    async def mark_all_unavailable(self) -> ToolHealthReport:
        async with self._health_lock:
            previous_available = self._available_tool_names()
            self._healthy = dict.fromkeys(self._tools, False)
            changed = previous_available != self._available_tool_names()
            if changed:
                self._health_revision += 1
            return self._build_health_report(changed=changed)

    def preflight(self, name: str, arguments: dict[str, Any]) -> PreparedToolInvocation:
        definition = self._tools.get(name)
        if definition is None:
            raise ToolNotFoundError(name)
        if not self._healthy[name]:
            raise ToolUnavailableError(name)

        try:
            parsed_input = definition.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ToolArgumentsError(name) from error
        return PreparedToolInvocation(definition=definition, parsed_input=parsed_input)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolInvocationResult:
        return await self.invoke_prepared(self.preflight(name, arguments))

    async def invoke_prepared(self, prepared: PreparedToolInvocation) -> ToolInvocationResult:
        definition = prepared.definition
        if self._tools.get(definition.name) is not definition:
            raise ToolNotFoundError(definition.name)

        try:
            raw_output = await asyncio.wait_for(
                definition.handler(prepared.parsed_input),
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

    def _validate_safe_definition(self, definition: ToolDefinition) -> None:
        annotations = definition.annotations
        try:
            read_only_hint = annotations.read_only_hint
            destructive_hint = annotations.destructive_hint
            idempotent_hint = annotations.idempotent_hint
            open_world_hint = annotations.open_world_hint
        except AttributeError as error:
            raise ValueError("tool metadata is invalid") from error
        if read_only_hint is not True:
            raise ValueError("SAFE tools must declare readOnlyHint=true")
        if destructive_hint is not False:
            raise ValueError("SAFE tools must declare destructiveHint=false")
        if idempotent_hint is not True:
            raise ValueError("SAFE tools must declare idempotentHint=true")
        if open_world_hint is not False:
            raise ValueError("SAFE tools must declare openWorldHint=false")

    def _validate_confirm_definition(self, definition: ToolDefinition) -> None:
        if definition.name not in self._confirm_tool_names:
            raise ValueError("CONFIRM tools require an explicit authorization policy")
        annotations = definition.annotations
        try:
            read_only_hint = annotations.read_only_hint
            destructive_hint = annotations.destructive_hint
            idempotent_hint = annotations.idempotent_hint
            open_world_hint = annotations.open_world_hint
        except AttributeError as error:
            raise ValueError("tool metadata is invalid") from error
        if read_only_hint is not False:
            raise ValueError("CONFIRM tools must declare readOnlyHint=false")
        if destructive_hint is not False:
            raise ValueError("CONFIRM tools must declare destructiveHint=false")
        if idempotent_hint is not False:
            raise ValueError("CONFIRM tools must declare idempotentHint=false")
        if open_world_hint is not False:
            raise ValueError("CONFIRM tools must declare openWorldHint=false")

    def _available_tool_names(self) -> tuple[str, ...]:
        return tuple(name for name in sorted(self._tools) if self._healthy[name])

    def _build_health_report(self, *, changed: bool) -> ToolHealthReport:
        return ToolHealthReport(
            revision=self._health_revision,
            changed=changed,
            available_tool_names=self._available_tool_names(),
            tools=tuple(
                ToolHealthSnapshot(
                    name=name,
                    status=(
                        ToolHealthStatus.HEALTHY
                        if self._healthy[name]
                        else ToolHealthStatus.UNAVAILABLE
                    ),
                )
                for name in sorted(self._tools)
            ),
        )
