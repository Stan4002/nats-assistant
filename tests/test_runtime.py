from fastapi.testclient import TestClient
import pytest

from nats_assistant import cli
from nats_assistant.api.server import create_app
from nats_assistant.config import get_settings, set_config_value
from nats_assistant.providers import google_calendar


def test_serve_passes_supported_configuration(monkeypatch):
    import uvicorn

    set_config_value("port", "9876")
    seen = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: seen.append((args, kwargs)))
    assert cli.main(["serve"]) == 0
    assert seen == [(('nats_assistant.api.server:create_app',), {
        "factory": True, "host": "127.0.0.1", "port": 9876,
        "log_level": "info", "timeout_graceful_shutdown": 10,
    })]


def test_serve_refuses_public_binding(monkeypatch, capsys):
    import uvicorn

    monkeypatch.setenv("NATS_HOST", "0.0.0.0")
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("Public server started"))
    assert cli.main(["serve"]) == 1
    assert "Invalid NATS configuration" in capsys.readouterr().err


@pytest.mark.parametrize("enabled", [True, False])
def test_persisted_startup_preserves_tasks_and_never_authenticates(monkeypatch, tmp_path, enabled):
    set_config_value("data_dir", str(tmp_path / "data"))
    set_config_value("google_calendar_enabled", str(enabled).lower())
    set_config_value("google_calendar_token_path", str(tmp_path / "missing.json"))
    monkeypatch.setattr(google_calendar, "authenticate_google_calendar", lambda *args: pytest.fail("OAuth started at startup"))
    with TestClient(create_app()) as client:
        assert client.post("/v1/tasks", json={"title": "Independent task"}).status_code == 201
        home = client.get("/v1/home").json()
        assert home["tasks"]["pending"] == 1
        assert home["calendar"]["status"] == "not_connected"
        assert client.get("/v1/status").json()["status"] == "online"
    with TestClient(create_app()) as restarted:
        assert restarted.get("/v1/home").json()["tasks"]["pending"] == 1


def test_existing_token_available_after_persisted_restart(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}")
    set_config_value("google_calendar_enabled", "true")
    set_config_value("google_calendar_token_path", str(token))
    monkeypatch.setattr(google_calendar, "authenticate_google_calendar", lambda *args: pytest.fail("Unexpected OAuth"))
    provider = google_calendar.GoogleCalendarProvider(get_settings())
    assert provider.availability() == "online"


def test_status_uses_running_configuration_even_after_bad_edit(tmp_path):
    set_config_value("data_dir", str(tmp_path / "data"))
    from nats_assistant.config import get_config_path

    with TestClient(create_app()) as client:
        get_config_path().write_text('port = "invalid"')
        assert client.get("/v1/status").json()["status"] == "online"
