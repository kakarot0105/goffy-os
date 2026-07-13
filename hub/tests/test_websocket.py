from datetime import UTC, datetime
from uuid import UUID, uuid4

from starlette.testclient import TestClient, WebSocketTestSession

from goffy_protocol import (
    PROTOCOL_VERSION,
    MessageEnvelope,
    MessageType,
    ToolInvocationPayload,
)

AUTH_HEADERS = {"Authorization": "Bearer test-token-that-is-long-enough"}


def invocation(tool_name: str = "mac.system_info") -> MessageEnvelope:
    return MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="android-test",
        message_type=MessageType.TOOL_INVOCATION,
        payload=ToolInvocationPayload(tool_name=tool_name).model_dump(mode="json", by_alias=True),
    )


def receive_envelope(socket: WebSocketTestSession) -> MessageEnvelope:
    raw = socket.receive_text()
    return MessageEnvelope.model_validate_json(raw)


def test_system_info_streams_progress_result_and_verification(client: TestClient) -> None:
    request = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        events = [receive_envelope(socket) for _ in range(4)]

    assert [event.message_type for event in events] == [
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_RESULT,
        MessageType.VERIFICATION_RESULT,
    ]
    assert all(event.correlation_id == request.message_id for event in events)
    result = events[2].payload
    assert result["toolName"] == "mac.system_info"
    assert result["executionTarget"] == "MAC"
    assert result["structuredContent"]["status"] == "available"
    assert events[3].payload["succeeded"] is True


def test_unknown_tool_returns_structured_error(client: TestClient) -> None:
    request = invocation("mac.unavailable")

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        progress = receive_envelope(socket)
        error = receive_envelope(socket)

    assert progress.message_type is MessageType.TOOL_PROGRESS
    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload == {
        "code": "tool_not_found",
        "message": "The requested tool is unavailable or unauthorized.",
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
    request = invocation("mac.unavailable")

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
