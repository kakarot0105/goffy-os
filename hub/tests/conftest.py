from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings

TEST_TOKEN = "test-token-that-is-long-enough"  # noqa: S105


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = HubSettings(auth_token=SecretStr(TEST_TOKEN))
    with TestClient(
        create_app(settings),
        base_url="http://127.0.0.1:8787",
    ) as test_client:
        yield test_client
