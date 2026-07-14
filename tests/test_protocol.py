import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from goffy_protocol import (
    JSON_SCHEMA_DIALECT,
    MCP_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    CapabilityDiscoveryRequestPayload,
    CapabilityDiscoveryResponsePayload,
    MessageEnvelope,
    MessageType,
    ToolInvocationPayload,
    ToolProgressPayload,
    ToolResultPayload,
    VerificationResultPayload,
)

FIXTURE_PATH = Path(__file__).parents[1] / "protocol" / "fixtures" / "mac-system-info-flow.jsonl"
PAIRING_BUNDLE_FIXTURE_PATH = (
    Path(__file__).parents[1] / "protocol" / "fixtures" / "pairing-bundle-v2.json"
)
DISCOVERY_SCHEMA_PATH = (
    Path(__file__).parents[1] / "protocol" / "schemas" / "capability-discovery.schema.json"
)
PAIRING_BUNDLE_SCHEMA_PATH = (
    Path(__file__).parents[1] / "protocol" / "schemas" / "pairing-bundle.schema.json"
)


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


def test_capability_discovery_payloads_are_strict() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapabilityDiscoveryRequestPayload.model_validate(
            {"toolName": "mac.system_info", "unexpected": True}
        )

    with pytest.raises(ValidationError, match="Input should be '2025-11-25'"):
        CapabilityDiscoveryResponsePayload.model_validate(
            {
                "mcpProtocolVersion": "2024-11-05",
                "listChanged": False,
                "tools": [],
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapabilityDiscoveryResponsePayload.model_validate(
            {
                "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
                "listChanged": False,
                "tools": [],
                "unexpected": True,
            }
        )


def test_capability_metadata_matches_android_acceptance_boundary() -> None:
    response = json.loads(FIXTURE_PATH.read_text(encoding="utf-8").splitlines()[1])["payload"]

    missing_hint = deepcopy(response)
    del missing_hint["tools"][0]["annotations"]["openWorldHint"]
    with pytest.raises(ValidationError, match="Field required"):
        CapabilityDiscoveryResponsePayload.model_validate(missing_hint)

    extra_annotation = deepcopy(response)
    extra_annotation["tools"][0]["annotations"]["title"] = "Unexpected annotation title"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapabilityDiscoveryResponsePayload.model_validate(extra_annotation)

    open_input_schema = deepcopy(response)
    open_input_schema["tools"][0]["inputSchema"]["additionalProperties"] = True
    with pytest.raises(ValidationError, match="must reject additional properties"):
        CapabilityDiscoveryResponsePayload.model_validate(open_input_schema)

    described_input_schema = deepcopy(response)
    described_input_schema["tools"][0]["inputSchema"]["description"] = "Not allowed"
    with pytest.raises(ValidationError, match="input schema does not match"):
        CapabilityDiscoveryResponsePayload.model_validate(described_input_schema)

    required_input_schema = deepcopy(response)
    required_input_schema["tools"][0]["inputSchema"]["required"] = []
    with pytest.raises(ValidationError, match="input schema does not match"):
        CapabilityDiscoveryResponsePayload.model_validate(required_input_schema)

    wrong_output_required = deepcopy(response)
    wrong_output_required["tools"][0]["outputSchema"]["required"] = [
        "status",
        "operatingSystem",
        "unexpected",
    ]
    with pytest.raises(ValidationError, match="required fields do not match"):
        CapabilityDiscoveryResponsePayload.model_validate(wrong_output_required)

    decorated_output_field = deepcopy(response)
    decorated_output_field["tools"][0]["outputSchema"]["properties"]["status"]["description"] = (
        "Not allowed"
    )
    with pytest.raises(ValidationError, match="output fields must be plain strings"):
        CapabilityDiscoveryResponsePayload.model_validate(decorated_output_field)

    wrong_execution_target = deepcopy(response)
    wrong_execution_target["tools"][0]["_meta"]["dev.goffy/executionTarget"] = "CLOUD"
    with pytest.raises(ValidationError, match="must target MAC"):
        CapabilityDiscoveryResponsePayload.model_validate(wrong_execution_target)


def test_capability_json_schema_matches_android_acceptance_boundary() -> None:
    schema = json.loads(DISCOVERY_SCHEMA_PATH.read_text(encoding="utf-8"))
    response = json.loads(FIXTURE_PATH.read_text(encoding="utf-8").splitlines()[1])["payload"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(response)

    long_description = deepcopy(response)
    long_description["tools"][0]["description"] = "d" * 300
    CapabilityDiscoveryResponsePayload.model_validate(long_description)
    validator.validate(long_description)

    incompatible = deepcopy(response)
    incompatible["tools"][0]["outputSchema"]["properties"]["status"]["description"] = "Not allowed"
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(incompatible)


def test_pairing_bundle_json_schema_matches_qr_onboarding_boundary() -> None:
    schema = json.loads(PAIRING_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    bundle = json.loads(PAIRING_BUNDLE_FIXTURE_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(bundle)

    lan_claim = deepcopy(bundle)
    lan_claim["hubEndpoint"] = "wss://hub.example/ws/v1"
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(lan_claim)

    localhost_alias = deepcopy(bundle)
    localhost_alias["hubEndpoint"] = "ws://localhost:8787/ws/v1"
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(localhost_alias)

    trusted_lan_claim = deepcopy(bundle)
    trusted_lan_claim["hubIdentity"]["trustedLanSupported"] = True
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(trusted_lan_claim)

    extended = deepcopy(bundle)
    extended["unexpected"] = True
    with pytest.raises(JsonSchemaValidationError):
        validator.validate(extended)


def test_shared_mac_system_info_flow_is_protocol_compatible() -> None:
    envelopes = [
        MessageEnvelope.model_validate_json(line)
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
    ]

    assert [event.message_type for event in envelopes] == [
        MessageType.CAPABILITY_DISCOVERY_REQUEST,
        MessageType.CAPABILITY_DISCOVERY_RESPONSE,
        MessageType.TOOL_INVOCATION,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_RESULT,
        MessageType.VERIFICATION_RESULT,
    ]
    discovery_request_id = envelopes[0].message_id
    invocation_id = envelopes[2].message_id
    assert envelopes[1].correlation_id == discovery_request_id
    assert all(event.correlation_id == invocation_id for event in envelopes[3:])

    payloads = [json.dumps(event.payload) for event in envelopes]
    discovery_request = CapabilityDiscoveryRequestPayload.model_validate_json(payloads[0])
    discovery_response = CapabilityDiscoveryResponsePayload.model_validate_json(payloads[1])
    ToolInvocationPayload.model_validate_json(payloads[2])
    ToolProgressPayload.model_validate_json(payloads[3])
    ToolProgressPayload.model_validate_json(payloads[4])
    result = ToolResultPayload.model_validate_json(payloads[5])
    verification = VerificationResultPayload.model_validate_json(payloads[6])

    assert discovery_request.tool_name == "mac.system_info"
    assert discovery_response.mcp_protocol_version == MCP_PROTOCOL_VERSION
    assert discovery_response.list_changed is False
    assert discovery_response.tools[0].input_schema["$schema"] == JSON_SCHEMA_DIALECT
    assert discovery_response.tools[0].meta.tool_version == "1.0.0"
    assert result.structured_content["operatingSystem"] == "Darwin"
    assert verification.succeeded is True
