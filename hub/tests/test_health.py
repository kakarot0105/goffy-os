from starlette.testclient import TestClient


def test_health_is_typed_and_minimal(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "protocolVersion": "0.1.0",
        "toolAccess": "enabled",
    }
