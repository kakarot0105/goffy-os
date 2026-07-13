from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import SecretStr
from starlette.testclient import TestClient, WebSocketTestSession

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings
from goffy_protocol import (
    PROTOCOL_VERSION,
    CapabilityDiscoveryResponsePayload,
    MessageEnvelope,
    MessageType,
    ToolInvocationPayload,
)

AUTH_HEADERS = {"Authorization": "Bearer test-token-that-is-long-enough"}


def discovery(
    tool_name: str = "mac.system_info", *, payload: dict[str, object] | None = None
) -> MessageEnvelope:
    return MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="android-test",
        message_type=MessageType.CAPABILITY_DISCOVERY_REQUEST,
        payload=payload or {"toolName": tool_name},
    )


def invocation(
    tool_name: str = "mac.system_info", *, payload: dict[str, object] | None = None
) -> MessageEnvelope:
    return MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="android-test",
        message_type=MessageType.TOOL_INVOCATION,
        payload=payload
        or ToolInvocationPayload(tool_name=tool_name, arguments={}).model_dump(
            mode="json", by_alias=True
        ),
    )


def receive_envelope(socket: WebSocketTestSession) -> MessageEnvelope:
    raw = socket.receive_text()
    return MessageEnvelope.model_validate_json(raw)


def test_capability_discovery_returns_filtered_tool_metadata(client: TestClient) -> None:
    request = discovery()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        response = receive_envelope(socket)

    assert response.message_type is MessageType.CAPABILITY_DISCOVERY_RESPONSE
    assert response.correlation_id == request.message_id
    payload = CapabilityDiscoveryResponsePayload.model_validate(response.payload)
    assert payload.tools[0].name == "mac.system_info"
    assert payload.tools[0].meta.tool_version == "1.0.0"
    assert payload.tools[0].meta.execution_target == "MAC"


def test_unknown_capability_discovery_returns_no_tools(client: TestClient) -> None:
    request = discovery("mac.unavailable")

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        response = receive_envelope(socket)

    payload = CapabilityDiscoveryResponsePayload.model_validate(response.payload)
    assert response.message_type is MessageType.CAPABILITY_DISCOVERY_RESPONSE
    assert response.correlation_id == request.message_id
    assert payload.tools == []


def test_invocation_before_discovery_is_blocked(client: TestClient) -> None:
    request = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload == {
        "code": "capability_discovery_required",
        "message": "Capability discovery must succeed before invoking this tool.",
        "retryable": False,
    }
    assert error.correlation_id == request.message_id


def test_system_info_discovery_then_invocation_streams_progress_result_and_verification(
    client: TestClient,
) -> None:
    discovery_request = discovery()
    invocation_request = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        discovery_response = receive_envelope(socket)
        socket.send_text(invocation_request.model_dump_json(by_alias=True))
        events = [receive_envelope(socket) for _ in range(4)]

    assert discovery_response.message_type is MessageType.CAPABILITY_DISCOVERY_RESPONSE
    assert [event.message_type for event in events] == [
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_RESULT,
        MessageType.VERIFICATION_RESULT,
    ]
    assert all(event.correlation_id == invocation_request.message_id for event in events)
    result = events[2].payload
    assert result["toolName"] == "mac.system_info"
    assert result["executionTarget"] == "MAC"
    assert result["structuredContent"]["status"] == "available"
    assert events[3].payload["succeeded"] is True


def test_discovery_is_consumed_by_one_invocation_attempt(client: TestClient) -> None:
    discovery_request = discovery()
    first_invocation = invocation()
    replayed_invocation = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        receive_envelope(socket)
        socket.send_text(first_invocation.model_dump_json(by_alias=True))
        for _ in range(4):
            receive_envelope(socket)
        socket.send_text(replayed_invocation.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "capability_discovery_required"
    assert error.correlation_id == replayed_invocation.message_id


def test_duplicate_message_id_revokes_pending_discovery(client: TestClient) -> None:
    discovery_request = discovery()
    invocation_request = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        receive_envelope(socket)
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        duplicate_error = receive_envelope(socket)
        socket.send_text(invocation_request.model_dump_json(by_alias=True))
        invocation_error = receive_envelope(socket)

    assert duplicate_error.payload["code"] == "duplicate_message"
    assert duplicate_error.correlation_id == discovery_request.message_id
    assert invocation_error.payload["code"] == "capability_discovery_required"


def test_invalid_capability_discovery_payload_returns_error(client: TestClient) -> None:
    request = discovery(payload={"toolName": "mac.system_info", "unexpected": True})

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload == {
        "code": "invalid_capability_discovery",
        "message": "Capability discovery payload is invalid.",
        "retryable": False,
    }
    assert error.correlation_id == request.message_id


def test_malformed_message_revokes_pending_discovery(client: TestClient) -> None:
    discovery_request = discovery()
    invocation_request = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        receive_envelope(socket)
        socket.send_text("not-json")
        malformed_error = receive_envelope(socket)
        socket.send_text(invocation_request.model_dump_json(by_alias=True))
        invocation_error = receive_envelope(socket)

    assert malformed_error.payload["code"] == "invalid_message"
    assert invocation_error.payload["code"] == "capability_discovery_required"


def test_invalid_tool_invocation_payload_returns_error(client: TestClient) -> None:
    request = invocation(
        payload={"toolName": "mac.system_info", "arguments": {}, "unexpected": True}
    )

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload == {
        "code": "invalid_tool_arguments",
        "message": "Tool invocation payload is invalid.",
        "retryable": False,
    }
    assert error.correlation_id == request.message_id


def test_malformed_message_returns_error_without_details(client: TestClient) -> None:
    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text('{"protocolVersion":"unsupported"}')
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "invalid_message"
    assert error.correlation_id is None


def test_message_ids_are_valid_uuids(client: TestClient) -> None:
    request = discovery()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        event = receive_envelope(socket)

    assert isinstance(event.message_id, UUID)


def test_oversized_message_returns_structured_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text("x" * 32_769)
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "message_too_large"


def test_oversized_outbound_discovery_is_closed_before_send() -> None:
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        max_message_bytes=1_024,
    )

    with (
        TestClient(create_app(settings)) as bounded_client,
        bounded_client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket,
    ):
        socket.send_text(discovery().model_dump_json(by_alias=True))
        close_message = socket.receive()

    assert close_message["type"] == "websocket.close"
    assert close_message["code"] == 1009
