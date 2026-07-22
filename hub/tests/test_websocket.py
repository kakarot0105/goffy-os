import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.testclient import TestClient, WebSocketTestSession

import goffy_hub.approval as approval_module
from approval_key_helpers import approval_key_fixture, signed_approval_response
from goffy_hub.app import create_app
from goffy_hub.approval import IssuedApprovalRecord, canonical_arguments_sha256
from goffy_hub.settings import HubSettings
from goffy_hub.tools import mac_apps
from goffy_protocol import (
    PROTOCOL_VERSION,
    ApprovalRequestPayload,
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


def paired_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


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


def test_unhealthy_tool_is_removed_from_android_discovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "")
    assert client.portal is not None
    app = cast(FastAPI, client.app)
    report = client.portal.call(app.state.tool_health_monitor.check_now)
    request = discovery()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(request.model_dump_json(by_alias=True))
        response = receive_envelope(socket)

    payload = CapabilityDiscoveryResponsePayload.model_validate(response.payload)
    assert report.changed is True
    assert payload.tools == []


def test_tool_becoming_unhealthy_after_discovery_is_never_accepted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery_request = discovery()
    invocation_request = invocation()

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        receive_envelope(socket)
        monkeypatch.setattr(platform, "system", lambda: "")
        assert client.portal is not None
        app = cast(FastAPI, client.app)
        client.portal.call(app.state.tool_health_monitor.check_now)
        socket.send_text(invocation_request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "tool_not_found"
    assert error.correlation_id == invocation_request.message_id


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


def mac_app_open_settings() -> HubSettings:
    return HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        mac_app_allowlist=("Safari=com.apple.Safari",),
        mac_app_open_enabled=True,
    )


def approved_mac_app_open_payload(
    *,
    task_id: UUID | None = None,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_task_id = task_id or uuid4()
    resolved_arguments = arguments or {"displayName": "Safari"}
    return {
        "toolName": "mac.apps.open",
        "arguments": resolved_arguments,
        "taskId": str(resolved_task_id),
    }


def test_confirm_mac_app_open_stays_fail_closed_without_device_bound_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    app = create_app(mac_app_open_settings())
    discovery_request = discovery("mac.apps.open")
    invocation_request = invocation(
        "mac.apps.open",
        payload={"toolName": "mac.apps.open", "arguments": {"displayName": "Safari"}},
    )

    with (
        TestClient(app, base_url="http://127.0.0.1:8787") as client,
        client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket,
    ):
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        discovery_response = receive_envelope(socket)
        socket.send_text(invocation_request.model_dump_json(by_alias=True))
        invocation_error = receive_envelope(socket)

    payload = CapabilityDiscoveryResponsePayload.model_validate(discovery_response.payload)
    assert payload.tools == []
    assert invocation_error.message_type is MessageType.TOOL_ERROR
    assert invocation_error.payload["code"] == "capability_discovery_required"
    assert invocation_error.correlation_id == invocation_request.message_id


def test_confirm_mac_app_open_stays_hidden_for_invalid_stored_approval_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        pairing_database_path=tmp_path / "state" / "credentials.sqlite3",
        mac_app_allowlist=("Safari=com.apple.Safari",),
        mac_app_open_enabled=True,
    )
    app = create_app(settings)
    issued = app.state.credential_store.issue("android-test", "Moto G", b"x" * 91)
    request = discovery("mac.apps.open")

    with (
        TestClient(app, base_url="http://127.0.0.1:8787") as client,
        client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(issued.access_token),
        ) as socket,
    ):
        socket.send_text(request.model_dump_json(by_alias=True))
        response = receive_envelope(socket)

    payload = CapabilityDiscoveryResponsePayload.model_validate(response.payload)
    assert response.message_type is MessageType.CAPABILITY_DISCOVERY_RESPONSE
    assert payload.tools == []


def test_approval_response_is_rejected_while_confirm_execution_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    app = create_app(mac_app_open_settings())
    request = MessageEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=uuid4(),
        timestamp=datetime.now(UTC),
        device_id="android-test",
        message_type=MessageType.APPROVAL_RESPONSE,
        payload={
            "schemaVersion": "goffy.approval.v1",
            "approvalId": str(uuid4()),
            "taskId": str(uuid4()),
            "approved": True,
        },
    )

    with (
        TestClient(app, base_url="http://127.0.0.1:8787") as client,
        client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket,
    ):
        socket.send_text(request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "approval_unavailable"
    assert error.correlation_id == request.message_id


def test_paired_confirm_mac_app_open_requires_signed_phone_approval_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    opened_apps: list[str] = []

    def fake_open_and_verify_app(
        app: mac_apps.ApprovedMacApp,
        _: float,
    ) -> dict[str, Any]:
        opened_apps.append(app.display_name)
        return {
            "status": "running",
            "displayName": app.display_name,
            "bundleId": app.bundle_id,
            "verified": True,
        }

    monkeypatch.setattr(mac_apps, "_open_and_verify_app", fake_open_and_verify_app)
    key = approval_key_fixture()
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        pairing_database_path=tmp_path / "state" / "credentials.sqlite3",
        mac_app_allowlist=("Safari=com.apple.Safari",),
        mac_app_open_enabled=True,
        tool_timeout_seconds=3.0,
    )
    app = create_app(settings)
    issued = app.state.credential_store.issue(
        "android-test",
        "Moto G",
        key.public_key_spki_der,
    )
    task_id = uuid4()
    discovery_request = discovery("mac.apps.open")
    invocation_request = invocation(
        "mac.apps.open",
        payload={
            "toolName": "mac.apps.open",
            "arguments": {"displayName": "Safari"},
            "taskId": str(task_id),
        },
    )

    with (
        TestClient(app, base_url="http://127.0.0.1:8787") as client,
        client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(issued.access_token),
        ) as socket,
    ):
        socket.send_text(discovery_request.model_dump_json(by_alias=True))
        discovery_response = receive_envelope(socket)
        socket.send_text(invocation_request.model_dump_json(by_alias=True))
        approval_envelope = receive_envelope(socket)
        approval_payload = ApprovalRequestPayload.model_validate(approval_envelope.payload)
        record = IssuedApprovalRecord(
            approval_id=approval_payload.approval_id,
            principal_key=f"paired:{issued.credential.credential_id}",
            task_id=approval_payload.task_id,
            tool_name=approval_payload.tool_name,
            arguments_sha256=approval_payload.arguments_sha256,
            issued_at_epoch_millis=approval_payload.issued_at_epoch_millis,
            expires_at_epoch_millis=approval_payload.expires_at_epoch_millis,
        )
        approval_response = MessageEnvelope(
            protocol_version=PROTOCOL_VERSION,
            message_id=uuid4(),
            timestamp=datetime.now(UTC),
            device_id="android-test",
            message_type=MessageType.APPROVAL_RESPONSE,
            payload=signed_approval_response(
                record=record,
                credential_id=issued.credential.credential_id,
                key=key,
            ).model_dump(mode="json", by_alias=True),
            correlation_id=invocation_request.message_id,
        )
        socket.send_text(approval_response.model_dump_json(by_alias=True))
        events = [receive_envelope(socket) for _ in range(4)]

    discovered = CapabilityDiscoveryResponsePayload.model_validate(discovery_response.payload)
    assert [tool.name for tool in discovered.tools] == ["mac.apps.open"]
    assert approval_envelope.message_type is MessageType.APPROVAL_REQUEST
    assert approval_envelope.correlation_id == invocation_request.message_id
    assert [event.message_type for event in events] == [
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_PROGRESS,
        MessageType.TOOL_RESULT,
        MessageType.VERIFICATION_RESULT,
    ]
    assert events[2].payload["structuredContent"]["verified"] is True
    assert opened_apps == ["Safari"]


def test_pending_confirm_approval_is_discarded_when_websocket_disconnects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(approval_module, "MAX_PENDING_APPROVALS", 1)
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    key = approval_key_fixture()
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        pairing_database_path=tmp_path / "state" / "credentials.sqlite3",
        mac_app_allowlist=("Safari=com.apple.Safari",),
        mac_app_open_enabled=True,
    )
    app = create_app(settings)
    issued = app.state.credential_store.issue(
        "android-test",
        "Moto G",
        key.public_key_spki_der,
    )

    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        with client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(issued.access_token),
        ) as socket:
            socket.send_text(discovery("mac.apps.open").model_dump_json(by_alias=True))
            receive_envelope(socket)
            socket.send_text(
                invocation(
                    "mac.apps.open",
                    payload=approved_mac_app_open_payload(),
                ).model_dump_json(by_alias=True)
            )
            first_approval = receive_envelope(socket)

        with client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(issued.access_token),
        ) as socket:
            second_invocation = invocation(
                "mac.apps.open",
                payload=approved_mac_app_open_payload(),
            )
            socket.send_text(discovery("mac.apps.open").model_dump_json(by_alias=True))
            receive_envelope(socket)
            socket.send_text(second_invocation.model_dump_json(by_alias=True))
            second_approval = receive_envelope(socket)

    assert first_approval.message_type is MessageType.APPROVAL_REQUEST
    assert second_approval.message_type is MessageType.APPROVAL_REQUEST
    assert second_approval.correlation_id == second_invocation.message_id


def test_safe_tool_rejects_unexpected_approval_artifact(client: TestClient) -> None:
    request = invocation(
        "mac.system_info",
        payload={
            **approved_mac_app_open_payload(),
            "toolName": "mac.system_info",
            "arguments": {},
        },
    )

    with client.websocket_connect("/ws/v1", headers=AUTH_HEADERS) as socket:
        socket.send_text(discovery().model_dump_json(by_alias=True))
        receive_envelope(socket)
        socket.send_text(request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "approval_unexpected"
    assert error.correlation_id == request.message_id


def test_confirm_mac_app_open_rejects_client_minted_approval_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    key = approval_key_fixture()
    settings = HubSettings(
        auth_token=SecretStr("test-token-that-is-long-enough"),
        pairing_database_path=tmp_path / "state" / "credentials.sqlite3",
        mac_app_allowlist=("Safari=com.apple.Safari",),
        mac_app_open_enabled=True,
    )
    app = create_app(settings)
    issued = app.state.credential_store.issue(
        "android-test",
        "Moto G",
        key.public_key_spki_der,
    )
    task_id = uuid4()
    request = invocation(
        "mac.apps.open",
        payload={
            "toolName": "mac.apps.open",
            "arguments": {"displayName": "Safari"},
            "taskId": str(task_id),
            "approval": {
                "schemaVersion": "goffy.approval.v1",
                "approvalId": str(uuid4()),
                "taskId": str(task_id),
                "toolName": "mac.apps.open",
                "argumentsSha256": canonical_arguments_sha256({"displayName": "Safari"}),
                "issuedAtEpochMillis": 1,
                "expiresAtEpochMillis": 60_001,
            },
        },
    )

    with (
        TestClient(app, base_url="http://127.0.0.1:8787") as client,
        client.websocket_connect("/ws/v1", headers=paired_headers(issued.access_token)) as socket,
    ):
        socket.send_text(discovery("mac.apps.open").model_dump_json(by_alias=True))
        receive_envelope(socket)
        socket.send_text(request.model_dump_json(by_alias=True))
        error = receive_envelope(socket)

    assert error.message_type is MessageType.TOOL_ERROR
    assert error.payload["code"] == "invalid_tool_arguments"
    assert error.correlation_id == request.message_id


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
