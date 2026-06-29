from fastapi.testclient import TestClient

from wise_mem.api import app


client = TestClient(app)


def test_health_endpoint_returns_expected_payload() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app": "wise-mem"}
