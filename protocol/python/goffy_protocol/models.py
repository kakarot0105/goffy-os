from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

PROTOCOL_VERSION = "0.1.0"


class GoffyModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
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


class ToolInvocationPayload(GoffyModel):
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolProgressPayload(GoffyModel):
    tool_name: str
    execution_target: ExecutionTarget
    stage: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=0)
    message: str = Field(min_length=1, max_length=256)


class ToolResultPayload(GoffyModel):
    tool_name: str
    execution_target: ExecutionTarget
    structured_content: dict[str, Any]


class ToolErrorPayload(GoffyModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=256)
    retryable: bool = False


class VerificationResultPayload(GoffyModel):
    succeeded: bool
    summary: str = Field(min_length=1, max_length=256)
    checks: list[str] = Field(default_factory=list, max_length=16)


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
        payload=payload.model_dump(mode="json", by_alias=True),
        correlation_id=correlation_id,
    )
