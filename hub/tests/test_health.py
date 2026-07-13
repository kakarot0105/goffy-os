import platform
from typing import cast

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.testclient import TestClient

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings
from goffy_protocol import PROTOCOL_VERSION


def test_health_is_typed_and_minimal(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "protocolVersion": PROTOCOL_VERSION,
        "toolAccess": "enabled",
        "healthyToolCount": 1,
        "unavailableToolCount": 0,
        "toolRegistryRevision": 1,
    }
    assert cast(FastAPI, client.app).version == "0.2.0"


def test_unhealthy_tool_is_removed_before_app_starts_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "")
    app = create_app(HubSettings(auth_token=SecretStr("test-token-that-is-long-enough")))

    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        response = client.get("/health")

        assert app.state.registry.is_sealed is True
        assert app.state.registry.describe() == []
        assert response.json()["status"] == "degraded"
        assert response.json()["healthyToolCount"] == 0
        assert response.json()["unavailableToolCount"] == 1
        assert response.json()["toolRegistryRevision"] == 0
