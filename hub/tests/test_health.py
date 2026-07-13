from starlette.testclient import TestClient

from goffy_protocol import PROTOCOL_VERSION


def test_health_is_typed_and_minimal(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "protocolVersion": PROTOCOL_VERSION,
        "toolAccess": "enabled",
    }
    assert client.app.version == "0.2.0"
