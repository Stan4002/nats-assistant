from fastapi.testclient import TestClient

from nats_assistant.config import get_settings


def test_status_endpoint(client: TestClient):
    response = client.get("/v1/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "nats-assistant"
    assert payload["status"] == "online"
    assert payload["version"] == "0.1.0"


def test_get_settings_uses_current_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NATS_TIMEZONE", "Europe/Paris")
    monkeypatch.setenv("NATS_DATA_DIR", str(tmp_path / "custom-data"))

    settings = get_settings()
    assert settings.timezone == "Europe/Paris"
    assert settings.data_dir == tmp_path / "custom-data"

    monkeypatch.setenv("NATS_TIMEZONE", "UTC")
    assert get_settings().timezone == "UTC"
