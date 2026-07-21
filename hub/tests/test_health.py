import platform
import sys
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.testclient import TestClient

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings
from goffy_hub.tools import mac_clipboard
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
    assert [tool.name for tool in cast(FastAPI, client.app).state.registry.describe()] == [
        "mac.system_info"
    ]
    assert cast(FastAPI, client.app).version == "0.2.0"


def test_health_counts_optional_mac_file_tool_when_roots_are_configured(tmp_path: Path) -> None:
    app = create_app(
        HubSettings(
            auth_token=SecretStr("test-token-that-is-long-enough"),
            mac_files_roots=(tmp_path,),
        )
    )

    with TestClient(app, base_url="http://127.0.0.1:8787") as configured_client:
        response = configured_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["healthyToolCount"] == 2
    assert response.json()["unavailableToolCount"] == 0


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


def test_clipboard_tool_is_healthy_when_opt_in_provider_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClipboardReader:
        def read_text(self) -> str:
            return "copy"

        def is_available(self) -> bool:
            return True

    monkeypatch.setattr(mac_clipboard, "PasteboardClipboardTextReader", FakeClipboardReader)
    app = create_app(
        HubSettings(
            auth_token=SecretStr("test-token-that-is-long-enough"),
            mac_clipboard_read_enabled=True,
        )
    )

    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["healthyToolCount"] == 2
    assert response.json()["unavailableToolCount"] == 0
    assert [tool.name for tool in app.state.registry.describe()] == [
        "mac.clipboard.read",
        "mac.system_info",
    ]


def test_clipboard_tool_is_unavailable_when_opt_in_provider_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    app = create_app(
        HubSettings(
            auth_token=SecretStr("test-token-that-is-long-enough"),
            mac_clipboard_read_enabled=True,
        )
    )

    with TestClient(app, base_url="http://127.0.0.1:8787") as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["healthyToolCount"] == 1
    assert response.json()["unavailableToolCount"] == 1
    assert [tool.name for tool in app.state.registry.describe()] == ["mac.system_info"]
