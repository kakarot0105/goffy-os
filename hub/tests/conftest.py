from __future__ import annotations

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings

TEST_TOKEN = "test-token-that-is-long-enough"  # noqa: S105


@pytest.fixture
def client() -> TestClient:
    settings = HubSettings(auth_token=SecretStr(TEST_TOKEN))
    return TestClient(create_app(settings))
