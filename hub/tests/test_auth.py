import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings


def test_websocket_rejects_missing_authorization(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect("/ws/v1"):
        pass

    assert error.value.code == 4401


def test_websocket_fails_closed_when_token_is_unconfigured() -> None:
    client = TestClient(create_app(HubSettings()))

    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect("/ws/v1", headers={"Authorization": "Bearer any-presented-token"}),
    ):
        pass

    assert error.value.code == 4401


def test_websocket_rejects_incorrect_token(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect(
            "/ws/v1", headers={"Authorization": "Bearer incorrect-token-that-is-long-enough"}
        ),
    ):
        pass

    assert error.value.code == 4401
