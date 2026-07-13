import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from goffy_protocol import (
    PROTOCOL_VERSION,
    MessageEnvelope,
    MessageType,
    ToolInvocationPayload,
    ToolProgressPayload,
    ToolResultPayload,
    VerificationResultPayload,
)

FIXTURE_PATH = Path(__file__).parents[1] / "protocol" / "fixtures" / "mac-system-info-flow.jsonl"


def valid_message() -> dict[str, object]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "deviceId": "android-test",
        "messageType": "ToolInvocation",
        "payload": {"toolName": "mac.system_info", "arguments": {}},
    }


def test_wire_message_parses_camel_case_and_serializes_camel_case() -> None:
    envelope = MessageEnvelope.model_validate_json(json.dumps(valid_message()))

    encoded = envelope.model_dump(mode="json", by_alias=True)
    assert encoded["protocolVersion"] == PROTOCOL_VERSION
    assert encoded["messageType"] == MessageType.TOOL_INVOCATION
    assert "message_id" not in encoded


def test_unsupported_protocol_version_is_rejected() -> None:
    message = valid_message()
    message["protocolVersion"] = "99.0.0"

    with pytest.raises(ValidationError, match="unsupported protocol version"):
        MessageEnvelope.model_validate_json(json.dumps(message))


def test_unknown_envelope_field_is_rejected() -> None:
    message = valid_message()
    message["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MessageEnvelope.model_validate_json(json.dumps(message))


def test_tool_name_rejects_command_like_input() -> None:
    with pytest.raises(ValidationError):
        ToolInvocationPayload(tool_name="mac.system_info; rm -rf /", arguments={})


def test_shared_mac_system_info_flow_is_protocol_compatible() -> None:
    envelopes = [
        MessageEnvelope.model_validate_json(line)
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
    ]

    assert [event.message_type for event in envelopes] == [
        MessageType.TOOL_INVOCATION,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_RESULT,
        MessageType.VERIFICATION_RESULT,
    ]
    invocation_id = envelopes[0].message_id
    assert all(event.correlation_id == invocation_id for event in envelopes[1:])
    payloads = [json.dumps(event.payload) for event in envelopes]
    ToolInvocationPayload.model_validate_json(payloads[0])
    ToolProgressPayload.model_validate_json(payloads[1])
    ToolProgressPayload.model_validate_json(payloads[2])
    result = ToolResultPayload.model_validate_json(payloads[3])
    verification = VerificationResultPayload.model_validate_json(payloads[4])
    assert result.structured_content["operatingSystem"] == "Darwin"
    assert verification.succeeded is True
