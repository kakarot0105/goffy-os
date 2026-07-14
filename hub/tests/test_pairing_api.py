from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings
from goffy_protocol import MCP_PROTOCOL_VERSION, PROTOCOL_VERSION, MessageEnvelope, MessageType

BOOTSTRAP_TOKEN = "bootstrap-token-that-is-long-enough"  # noqa: S105
BOOTSTRAP_HEADERS = {"Authorization": f"Bearer {BOOTSTRAP_TOKEN}"}


@contextmanager
def pairing_client(
    tmp_path: Path,
    *,
    client_host: str = "127.0.0.1",
    max_active_sessions: int = 8,
) -> Iterator[TestClient]:
    settings = HubSettings(
        auth_token=SecretStr(BOOTSTRAP_TOKEN),
        pairing_database_path=tmp_path / "state" / "credentials.sqlite3",
        mcp_max_active_sessions=max_active_sessions,
    )
    with TestClient(
        create_app(settings),
        base_url="http://127.0.0.1:8787",
        client=(client_host, 50_000),
    ) as client:
        yield client


def pair_device(
    client: TestClient,
    *,
    device_id: str = "setup-observation-1",
    display_name: str = "Moto G",
) -> tuple[str, str]:
    challenge_response = client.post(
        "/admin/v1/pairing/challenges",
        headers=BOOTSTRAP_HEADERS,
    )
    assert challenge_response.status_code == 201
    assert challenge_response.headers["cache-control"] == "no-store"
    assert challenge_response.headers["pragma"] == "no-cache"
    challenge = challenge_response.json()
    redemption_response = client.post(
        "/pairing/v1/redeem",
        json={
            "challengeId": challenge["challengeId"],
            "pairingToken": challenge["pairingToken"],
            "deviceId": device_id,
            "displayName": display_name,
        },
    )
    assert redemption_response.status_code == 201
    assert redemption_response.headers["cache-control"] == "no-store"
    assert redemption_response.headers["pragma"] == "no-cache"
    redemption = redemption_response.json()
    return cast(str, redemption["credentialId"]), cast(str, redemption["accessToken"])


def paired_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "paired-test-client", "version": "1.0.0"},
        },
    }


def initialize_mcp(client: TestClient, access_token: str) -> str:
    response = client.post(
        "/mcp",
        json=initialize_request(),
        headers={
            **paired_headers(access_token),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    return response.headers["mcp-session-id"]


def mcp_session_headers(access_token: str, session_id: str) -> dict[str, str]:
    return {
        **paired_headers(access_token),
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "MCP-Session-Id": session_id,
    }


def test_pairing_routes_are_absent_until_database_is_explicitly_configured() -> None:
    with TestClient(
        create_app(HubSettings(auth_token=SecretStr(BOOTSTRAP_TOKEN))),
        client=("127.0.0.1", 50_000),
    ) as client:
        response = client.post(
            "/admin/v1/pairing/challenges",
            headers=BOOTSTRAP_HEADERS,
        )

    assert response.status_code == 404


def test_pairing_admin_and_redemption_are_loopback_only(tmp_path: Path) -> None:
    with pairing_client(tmp_path, client_host="192.0.2.10") as client:
        admin_response = client.post(
            "/admin/v1/pairing/challenges",
            headers=BOOTSTRAP_HEADERS,
        )
        redemption_response = client.post(
            "/pairing/v1/redeem",
            json={
                "challengeId": "30303030-3030-4030-8030-303030303030",
                "pairingToken": "p" * 32,
                "deviceId": "setup-observation-1",
                "displayName": "Moto G",
            },
        )
        list_response = client.get(
            "/admin/v1/credentials",
            headers=BOOTSTRAP_HEADERS,
        )
        revoke_response = client.delete(
            "/admin/v1/credentials/30303030-3030-4030-8030-303030303030",
            headers=BOOTSTRAP_HEADERS,
        )
        self_revoke_response = client.delete(
            "/pairing/v1/self",
            headers={"Authorization": "Bearer paired-token-that-is-long-enough"},
        )

    assert admin_response.status_code == 403
    assert redemption_response.status_code == 403
    assert list_response.status_code == 403
    assert revoke_response.status_code == 403
    assert self_revoke_response.status_code == 403
    assert admin_response.json()["detail"]["code"] == "loopback_required"
    assert redemption_response.json()["detail"]["code"] == "loopback_required"


def test_pairing_mints_token_once_and_admin_listing_never_echoes_secrets(tmp_path: Path) -> None:
    with pairing_client(tmp_path) as client:
        credential_id, access_token = pair_device(client)
        response = client.get("/admin/v1/credentials", headers=BOOTSTRAP_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "credentials": [
            {
                "credentialId": credential_id,
                "deviceId": "setup-observation-1",
                "displayName": "Moto G",
                "createdAt": response.json()["credentials"][0]["createdAt"],
                "revokedAt": None,
            }
        ]
    }
    assert access_token not in response.text
    assert "pairingToken" not in response.text


def test_pairing_requires_bootstrap_admin_and_rejects_paired_admin_access(
    tmp_path: Path,
) -> None:
    with pairing_client(tmp_path) as client:
        missing = client.post("/admin/v1/pairing/challenges")
        _credential_id, access_token = pair_device(client)
        paired = client.get(
            "/admin/v1/credentials",
            headers=paired_headers(access_token),
        )

    assert missing.status_code == 401
    assert paired.status_code == 403
    assert paired.json()["detail"]["code"] == "insufficient_scope"


def test_self_revocation_requires_the_paired_principal_and_targets_only_itself(
    tmp_path: Path,
) -> None:
    with pairing_client(tmp_path) as client:
        first_id, first_token = pair_device(client, device_id="observation-1")
        second_id, second_token = pair_device(client, device_id="observation-2")

        missing = client.delete("/pairing/v1/self")
        bootstrap = client.delete("/pairing/v1/self", headers=BOOTSTRAP_HEADERS)
        revoked = client.delete("/pairing/v1/self", headers=paired_headers(first_token))
        repeated = client.delete("/pairing/v1/self", headers=paired_headers(first_token))
        second_access = client.post(
            "/mcp",
            json=initialize_request(),
            headers={
                **paired_headers(second_token),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        listed = client.get("/admin/v1/credentials", headers=BOOTSTRAP_HEADERS)

    assert missing.status_code == 401
    assert bootstrap.status_code == 403
    assert bootstrap.json()["detail"]["code"] == "paired_principal_required"
    assert revoked.status_code == 200
    assert revoked.headers["cache-control"] == "no-store"
    assert revoked.json() == {"credentialId": first_id, "revoked": True}
    assert repeated.status_code == 401
    assert second_access.status_code == 200
    by_id = {item["credentialId"]: item for item in listed.json()["credentials"]}
    assert by_id[first_id]["revokedAt"] is not None
    assert by_id[second_id]["revokedAt"] is None


def test_invalid_pairing_request_is_bounded_and_never_echoes_token(tmp_path: Path) -> None:
    secret_marker = "pairing-secret-that-must-not-be-echoed"  # noqa: S105
    with pairing_client(tmp_path) as client:
        invalid = client.post(
            "/pairing/v1/redeem",
            json={
                "challengeId": "not-a-uuid",
                "pairingToken": secret_marker,
                "deviceId": "setup-observation-1",
                "displayName": "Moto G",
            },
        )
        oversized = client.post(
            "/pairing/v1/redeem",
            content=b"x" * 2_049,
            headers={"Content-Type": "application/json"},
        )

    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_pairing_request"
    assert secret_marker not in invalid.text
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "pairing_request_too_large"


def test_bootstrap_is_admin_only_after_pairing_is_enabled(tmp_path: Path) -> None:
    with pairing_client(tmp_path) as client:
        with (
            pytest.raises(WebSocketDisconnect) as websocket_error,
            client.websocket_connect(
                "/ws/v1",
                headers=BOOTSTRAP_HEADERS,
            ),
        ):
            pass
        mcp_response = client.post(
            "/mcp",
            json=initialize_request(),
            headers={
                **BOOTSTRAP_HEADERS,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )

    assert websocket_error.value.code == 4403
    assert mcp_response.status_code == 403
    assert mcp_response.json()["error"] == "insufficient_scope"


def test_paired_credential_runs_websocket_and_mcp_tool_discovery(tmp_path: Path) -> None:
    with pairing_client(tmp_path) as client:
        _credential_id, access_token = pair_device(client)
        request = MessageEnvelope.model_validate(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": UUID("50505050-5050-4050-8050-505050505050"),
                "timestamp": datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
                "deviceId": "android-test",
                "messageType": MessageType.CAPABILITY_DISCOVERY_REQUEST,
                "payload": {"toolName": "mac.system_info"},
            }
        )
        with client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(access_token),
        ) as socket:
            socket.send_text(request.model_dump_json(by_alias=True))
            websocket_response = MessageEnvelope.model_validate_json(socket.receive_text())

        session_id = initialize_mcp(client, access_token)
        mcp_response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=mcp_session_headers(access_token, session_id),
        )

    assert websocket_response.message_type is MessageType.CAPABILITY_DISCOVERY_RESPONSE
    assert websocket_response.payload["tools"][0]["name"] == "mac.system_info"
    assert mcp_response.status_code == 200
    assert mcp_response.json()["result"]["tools"][0]["name"] == "mac.system_info"


def test_mcp_session_is_owned_by_one_paired_credential(tmp_path: Path) -> None:
    with pairing_client(tmp_path) as client:
        _first_id, first_token = pair_device(client, device_id="observation-1")
        _second_id, second_token = pair_device(client, device_id="observation-2")
        session_id = initialize_mcp(client, first_token)
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}

        wrong_principal = client.post(
            "/mcp",
            json=request,
            headers=mcp_session_headers(second_token, session_id),
        )
        wrong_get = client.get(
            "/mcp",
            headers={
                **mcp_session_headers(second_token, session_id),
                "Accept": "text/event-stream",
            },
        )
        wrong_delete = client.delete(
            "/mcp",
            headers=mcp_session_headers(second_token, session_id),
        )
        owner = client.post(
            "/mcp",
            json=request,
            headers=mcp_session_headers(first_token, session_id),
        )

    assert wrong_principal.status_code == 404
    assert wrong_principal.json()["error"]["message"] == "Session not found"
    assert wrong_get.status_code == 404
    assert wrong_delete.status_code == 404
    assert owner.status_code == 200


def test_revocation_closes_live_websocket_and_mcp_session(tmp_path: Path) -> None:
    with pairing_client(tmp_path) as client:
        credential_id, access_token = pair_device(client)
        session_id = initialize_mcp(client, access_token)
        app = cast(FastAPI, client.app)

        with client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(access_token),
        ) as socket:
            revoked = client.delete("/pairing/v1/self", headers=paired_headers(access_token))
            with pytest.raises(WebSocketDisconnect) as websocket_error:
                socket.receive_text()

        after_revoke = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=mcp_session_headers(access_token, session_id),
        )

        assert revoked.status_code == 200
        assert app.state.mcp_runtime.session_manager.active_session_count == 0

    assert websocket_error.value.code == 4403
    assert after_revoke.status_code == 401
    assert after_revoke.json()["error"] == "invalid_token"


def test_revocation_immediately_releases_mcp_session_capacity(tmp_path: Path) -> None:
    with pairing_client(tmp_path, max_active_sessions=1) as client:
        first_credential_id, first_token = pair_device(client, device_id="observation-1")
        initialize_mcp(client, first_token)
        revoked = client.delete(
            f"/admin/v1/credentials/{first_credential_id}",
            headers=BOOTSTRAP_HEADERS,
        )
        _second_credential_id, second_token = pair_device(
            client,
            device_id="observation-2",
        )
        replacement_session_id = initialize_mcp(client, second_token)

    assert revoked.status_code == 200
    assert replacement_session_id


def test_health_reports_tool_access_only_after_a_paired_credential_exists(tmp_path: Path) -> None:
    with pairing_client(tmp_path) as client:
        before = client.get("/health")
        pair_device(client)
        after = client.get("/health")

    assert before.json()["toolAccess"] == "disabled"
    assert after.json()["toolAccess"] == "enabled"


def test_paired_credential_survives_hub_restart_but_pending_challenge_does_not(
    tmp_path: Path,
) -> None:
    with pairing_client(tmp_path) as first_client:
        _credential_id, access_token = pair_device(first_client)
        pending = first_client.post(
            "/admin/v1/pairing/challenges",
            headers=BOOTSTRAP_HEADERS,
        ).json()

    with pairing_client(tmp_path) as restarted_client:
        with restarted_client.websocket_connect(
            "/ws/v1",
            headers=paired_headers(access_token),
        ):
            pass
        stale_challenge = restarted_client.post(
            "/pairing/v1/redeem",
            json={
                "challengeId": pending["challengeId"],
                "pairingToken": pending["pairingToken"],
                "deviceId": "setup-observation-2",
                "displayName": "Second phone",
            },
        )

    assert stale_challenge.status_code == 400
    assert stale_challenge.json()["detail"]["code"] == "invalid_pairing_challenge"


def test_runtime_credential_store_failure_fails_closed_without_secret_echo(
    tmp_path: Path,
) -> None:
    with pairing_client(tmp_path) as client:
        credential_id, access_token = pair_device(client)
        challenge = client.post(
            "/admin/v1/pairing/challenges",
            headers=BOOTSTRAP_HEADERS,
        ).json()
        app = cast(FastAPI, client.app)
        database_path = app.state.credential_store.database_path
        database_path.write_bytes(b"corrupt-after-startup")

        health = client.get("/health")
        challenge_creation = client.post(
            "/admin/v1/pairing/challenges",
            headers=BOOTSTRAP_HEADERS,
        )
        mcp = client.post(
            "/mcp",
            json=initialize_request(),
            headers={
                **paired_headers(access_token),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        with (
            pytest.raises(WebSocketDisconnect) as websocket_error,
            client.websocket_connect(
                "/ws/v1",
                headers=paired_headers(access_token),
            ),
        ):
            pass
        listed = client.get("/admin/v1/credentials", headers=BOOTSTRAP_HEADERS)
        revoked = client.delete(
            f"/admin/v1/credentials/{credential_id}",
            headers=BOOTSTRAP_HEADERS,
        )
        redeemed = client.post(
            "/pairing/v1/redeem",
            json={
                "challengeId": challenge["challengeId"],
                "pairingToken": challenge["pairingToken"],
                "deviceId": "observation-2",
                "displayName": "Second phone",
            },
        )
        self_revoked = client.delete(
            "/pairing/v1/self",
            headers=paired_headers(access_token),
        )

    assert health.status_code == 200
    assert health.json()["toolAccess"] == "disabled"
    assert challenge_creation.status_code == 503
    assert mcp.status_code == 401
    assert websocket_error.value.code == 4401
    assert listed.status_code == 503
    assert revoked.status_code == 503
    assert redeemed.status_code == 503
    assert self_revoked.status_code == 401
    assert access_token not in listed.text + revoked.text + redeemed.text + self_revoked.text
