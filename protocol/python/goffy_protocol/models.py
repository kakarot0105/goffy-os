from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

PROTOCOL_VERSION = "0.2.0"
MCP_PROTOCOL_VERSION: Literal["2025-11-25"] = "2025-11-25"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_.]*$"
SEMVER_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
MAC_SYSTEM_INFO_TOOL_NAME = "mac.system_info"
MAC_SYSTEM_INFO_TOOL_VERSION = "1.0.0"
MAC_SYSTEM_INFO_FIELDS = frozenset({"status", "operatingSystem", "architecture"})
APPROVAL_SCHEMA_VERSION: Literal["goffy.approval.v1"] = "goffy.approval.v1"
SHA256_HEX_PATTERN = r"^[a-f0-9]{64}$"


class GoffyModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        revalidate_instances="always",
        strict=True,
    )


class MessageType(StrEnum):
    PAIRING_REQUEST = "PairingRequest"
    PAIRING_CHALLENGE = "PairingChallenge"
    PAIRING_RESPONSE = "PairingResponse"
    PAIRING_SUCCESS = "PairingSuccess"
    DEVICE_STATUS = "DeviceStatus"
    CAPABILITY_DISCOVERY_REQUEST = "CapabilityDiscoveryRequest"
    CAPABILITY_DISCOVERY_RESPONSE = "CapabilityDiscoveryResponse"
    USER_INTENT = "UserIntent"
    EXECUTION_PLAN = "ExecutionPlan"
    APPROVAL_REQUEST = "ApprovalRequest"
    APPROVAL_RESPONSE = "ApprovalResponse"
    TOOL_INVOCATION = "ToolInvocation"
    TOOL_PROGRESS = "ToolProgress"
    TOOL_RESULT = "ToolResult"
    TOOL_ERROR = "ToolError"
    VERIFICATION_RESULT = "VerificationResult"
    CANCELLATION_REQUEST = "CancellationRequest"
    HEARTBEAT = "Heartbeat"
    AUDIT_EVENT = "AuditEvent"


class ExecutionTarget(StrEnum):
    PHONE = "PHONE"
    MAC = "MAC"
    CLOUD = "CLOUD"


class PermissionLevel(StrEnum):
    SAFE = "SAFE"
    CONFIRM = "CONFIRM"
    SENSITIVE = "SENSITIVE"
    BLOCKED = "BLOCKED"


class MessageEnvelope(GoffyModel):
    protocol_version: str = Field(min_length=1, max_length=32)
    message_id: UUID
    timestamp: datetime
    device_id: str = Field(min_length=1, max_length=128)
    message_type: MessageType
    payload: dict[str, Any]
    correlation_id: UUID | None = None

    @model_validator(mode="after")
    def reject_unsupported_version(self) -> MessageEnvelope:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version: {self.protocol_version}")
        return self


class ApprovalRequestPayload(GoffyModel):
    schema_version: Literal["goffy.approval.v1"] = Field(alias="schemaVersion")
    approval_id: UUID
    task_id: UUID
    tool_name: str = Field(min_length=1, max_length=128, pattern=TOOL_NAME_PATTERN)
    arguments_sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    issued_at_epoch_millis: int = Field(ge=0)
    expires_at_epoch_millis: int = Field(ge=1)

    @field_validator("approval_id", "task_id", mode="before")
    @classmethod
    def parse_uuid(cls, value: UUID | str) -> UUID | str:
        return UUID(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_non_expiring_request(self) -> ApprovalRequestPayload:
        if self.expires_at_epoch_millis <= self.issued_at_epoch_millis:
            raise ValueError("approval request must expire after it is issued")
        return self


class ApprovalResponsePayload(GoffyModel):
    schema_version: Literal["goffy.approval.v1"] = Field(alias="schemaVersion")
    approval_id: UUID
    task_id: UUID
    approved: bool

    @field_validator("approval_id", "task_id", mode="before")
    @classmethod
    def parse_uuid(cls, value: UUID | str) -> UUID | str:
        return UUID(value) if isinstance(value, str) else value


class ToolInvocationPayload(GoffyModel):
    tool_name: str = Field(min_length=1, max_length=128, pattern=TOOL_NAME_PATTERN)
    arguments: dict[str, Any]
    task_id: UUID | None = None

    @field_validator("task_id", mode="before")
    @classmethod
    def parse_task_uuid(cls, value: UUID | str | None) -> UUID | str | None:
        return UUID(value) if isinstance(value, str) else value


class CapabilityDiscoveryRequestPayload(GoffyModel):
    tool_name: str = Field(min_length=1, max_length=128, pattern=TOOL_NAME_PATTERN)


class ToolAnnotations(GoffyModel):
    read_only_hint: bool
    destructive_hint: bool
    idempotent_hint: bool
    open_world_hint: bool

    @model_validator(mode="after")
    def reject_invalid_combinations(self) -> ToolAnnotations:
        if self.read_only_hint and self.destructive_hint:
            raise ValueError("read-only tools cannot be marked destructive")
        return self


class GoffyToolMetadata(GoffyModel):
    tool_version: str = Field(alias="dev.goffy/toolVersion", pattern=SEMVER_PATTERN)
    execution_target: ExecutionTarget = Field(alias="dev.goffy/executionTarget")
    permission: PermissionLevel = Field(alias="dev.goffy/permission")
    timeout_ms: int = Field(alias="dev.goffy/timeoutMs", ge=1, le=30_000)

    @field_validator("execution_target", mode="before")
    @classmethod
    def parse_execution_target(cls, value: ExecutionTarget | str) -> ExecutionTarget | str:
        return ExecutionTarget(value) if isinstance(value, str) else value

    @field_validator("permission", mode="before")
    @classmethod
    def parse_permission_level(cls, value: PermissionLevel | str) -> PermissionLevel | str:
        return PermissionLevel(value) if isinstance(value, str) else value


class ToolCapability(GoffyModel):
    name: str = Field(min_length=1, max_length=128, pattern=TOOL_NAME_PATTERN)
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] = Field(alias="outputSchema")
    annotations: ToolAnnotations
    meta: GoffyToolMetadata = Field(alias="_meta")

    @model_validator(mode="after")
    def enforce_schema_roots(self) -> ToolCapability:
        for schema_name, schema in (
            ("inputSchema", self.input_schema),
            ("outputSchema", self.output_schema),
        ):
            if schema.get("$schema") != JSON_SCHEMA_DIALECT:
                raise ValueError(f"{schema_name} must declare JSON Schema 2020-12")
            if schema.get("type") != "object":
                raise ValueError(f"{schema_name} must use an object root")
            if schema.get("additionalProperties") is not False:
                raise ValueError(f"{schema_name} must reject additional properties")
            if not isinstance(schema.get("properties"), dict):
                raise ValueError(f"{schema_name} must declare object properties")
            if _contains_json_schema_title(schema):
                raise ValueError(f"{schema_name} must not contain generated titles")
        if self.name == MAC_SYSTEM_INFO_TOOL_NAME:
            self._enforce_mac_system_info_contract()
        return self

    def _enforce_mac_system_info_contract(self) -> None:
        if self.meta.tool_version != MAC_SYSTEM_INFO_TOOL_VERSION:
            raise ValueError("mac.system_info has an unsupported tool version")
        if self.meta.execution_target is not ExecutionTarget.MAC:
            raise ValueError("mac.system_info must target MAC")
        if self.meta.permission is not PermissionLevel.SAFE:
            raise ValueError("mac.system_info must use SAFE permission")
        if (
            self.annotations.read_only_hint is not True
            or self.annotations.destructive_hint is not False
            or self.annotations.idempotent_hint is not True
            or self.annotations.open_world_hint is not False
        ):
            raise ValueError("mac.system_info safety annotations are incompatible")
        _enforce_mac_system_info_schemas(self.input_schema, self.output_schema)


class CapabilityDiscoveryResponsePayload(GoffyModel):
    mcp_protocol_version: Literal["2025-11-25"]
    list_changed: Literal[False]
    tools: list[ToolCapability] = Field(max_length=1)


class ToolProgressPayload(GoffyModel):
    tool_name: str
    execution_target: ExecutionTarget
    stage: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=0)
    message: str = Field(min_length=1, max_length=256)

    @field_validator("execution_target", mode="before")
    @classmethod
    def parse_execution_target(cls, value: ExecutionTarget | str) -> ExecutionTarget | str:
        return ExecutionTarget(value) if isinstance(value, str) else value


class ToolResultPayload(GoffyModel):
    tool_name: str
    execution_target: ExecutionTarget
    structured_content: dict[str, Any]

    @field_validator("execution_target", mode="before")
    @classmethod
    def parse_execution_target(cls, value: ExecutionTarget | str) -> ExecutionTarget | str:
        return ExecutionTarget(value) if isinstance(value, str) else value


class ToolErrorPayload(GoffyModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=256)
    retryable: bool = False


class VerificationResultPayload(GoffyModel):
    succeeded: bool
    summary: str = Field(min_length=1, max_length=256)
    checks: list[str] = Field(default_factory=list, max_length=16)


def normalize_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_json_schema_value(schema)
    if not isinstance(normalized, dict):
        raise ValueError("tool schemas must serialize to JSON objects")
    normalized["$schema"] = JSON_SCHEMA_DIALECT
    if normalized.get("type") != "object":
        raise ValueError("tool schemas must use an object root")
    sorted_schema = _sort_json_keys(normalized)
    if not isinstance(sorted_schema, dict):
        raise ValueError("tool schemas must serialize to JSON objects")
    return cast(dict[str, Any], sorted_schema)


def build_envelope(
    *,
    message_type: MessageType,
    payload: BaseModel,
    device_id: str = "goffy-hub",
    correlation_id: UUID | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id=device_id,
        message_type=message_type,
        payload=payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        correlation_id=correlation_id,
    )


def _contains_json_schema_title(value: Any, *, property_map: bool = False) -> bool:
    if isinstance(value, dict):
        if property_map:
            return any(_contains_json_schema_title(item) for item in value.values())
        return any(
            key == "title" or _contains_json_schema_title(item, property_map=key == "properties")
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_json_schema_title(item) for item in value)
    return False


def _normalize_json_schema_value(value: Any, *, property_map: bool = False) -> Any:
    if isinstance(value, dict):
        if property_map:
            return {key: _normalize_json_schema_value(item) for key, item in value.items()}
        return {
            key: _normalize_json_schema_value(item, property_map=key == "properties")
            for key, item in value.items()
            if key != "title"
        }
    if isinstance(value, list):
        return [_normalize_json_schema_value(item) for item in value]
    return value


def _sort_json_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sort_json_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_json_keys(item) for item in value]
    return value


def _enforce_mac_system_info_schemas(
    input_schema: dict[str, Any], output_schema: dict[str, Any]
) -> None:
    input_keys = {"$schema", "additionalProperties", "properties", "type"}
    if set(input_schema) != input_keys or input_schema["properties"] != {}:
        raise ValueError("mac.system_info input schema does not match the contract")

    output_keys = input_keys | {"required"}
    if set(output_schema) != output_keys:
        raise ValueError("mac.system_info output schema contains unsupported fields")
    properties = output_schema["properties"]
    if set(properties) != MAC_SYSTEM_INFO_FIELDS:
        raise ValueError("mac.system_info output properties do not match the contract")
    if any(field_schema != {"type": "string"} for field_schema in properties.values()):
        raise ValueError("mac.system_info output fields must be plain strings")
    required = output_schema["required"]
    if (
        not isinstance(required, list)
        or len(required) != len(MAC_SYSTEM_INFO_FIELDS)
        or any(not isinstance(field, str) for field in required)
        or set(required) != MAC_SYSTEM_INFO_FIELDS
    ):
        raise ValueError("mac.system_info required fields do not match the contract")
