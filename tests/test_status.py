from fastapi.testclient import TestClient


def test_status_endpoint(client: TestClient):
    response = client.get("/v1/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "nats-assistant"
    assert payload["status"] == "online"
    assert payload["version"] == "0.1.0"
