import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from nats_assistant import cli, quick_entry
from nats_assistant.config import Settings
from nats_assistant.providers.google_calendar import SCOPES, GoogleAuthSetupError, GoogleCalendarProvider, authenticate_google_calendar
from nats_assistant.providers.calendar import CalendarProviderError


def test_google_config_uses_nats_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NATS_GOOGLE_CALENDAR_ENABLED", "true")
    monkeypatch.setenv("NATS_GOOGLE_CALENDAR_TOKEN_PATH", str(tmp_path / "external-token.json"))
    monkeypatch.setenv("NATS_GOOGLE_CALENDAR_ID", "work@example.com")
    settings = Settings()
    assert settings.google_calendar_enabled is True
    assert settings.google_calendar_token_path == tmp_path / "external-token.json"
    assert settings.google_calendar_id == "work@example.com"


def test_google_auth_paths_must_be_outside_repository():
    project = Path(__file__).resolve().parents[1]
    with pytest.raises(ValidationError, match="outside"):
        Settings(google_calendar_token_path=project / "token.json")
    with pytest.raises(ValidationError, match="outside"):
        Settings(google_calendar_credentials_path=project / "client_secret.json")


def test_missing_desktop_credentials_is_controlled(tmp_path):
    with pytest.raises(GoogleAuthSetupError, match="missing"):
        authenticate_google_calendar(Settings(google_calendar_credentials_path=tmp_path / "missing.json"))


def test_explicit_auth_requests_readonly_and_saves_private_token(monkeypatch, tmp_path):
    flow_module = pytest.importorskip("google_auth_oauthlib.flow")
    client = tmp_path / "client.json"
    client.write_text("{}")
    token = tmp_path / "auth" / "token.json"
    seen = {}
    credentials = SimpleNamespace(refresh_token="synthetic", has_scopes=lambda scopes: scopes == SCOPES, to_json=lambda: '{"token": "synthetic"}')

    def request(method, url, **kwargs):
        seen["network_timeout"] = kwargs["timeout"]

    flow = SimpleNamespace(oauth2session=SimpleNamespace(request=request))

    def run_local_server(**kwargs):
        seen["server"] = kwargs
        flow.oauth2session.request("POST", "https://oauth2.googleapis.com/token")
        return credentials

    flow.run_local_server = run_local_server

    def from_file(path, scopes, **kwargs):
        seen["scopes"] = scopes
        seen["pkce"] = kwargs["autogenerate_code_verifier"]
        return flow

    monkeypatch.setattr(flow_module.InstalledAppFlow, "from_client_secrets_file", from_file)
    settings = Settings(google_calendar_credentials_path=client, google_calendar_token_path=token)
    assert authenticate_google_calendar(settings) == token
    assert seen["scopes"] == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert seen["pkce"] is True
    assert seen["server"]["host"] == "127.0.0.1"
    assert seen["server"]["timeout_seconds"] == 180
    assert seen["network_timeout"] == settings.google_calendar_timeout_seconds
    assert token.stat().st_mode & 0o777 == 0o600
    assert json.loads(token.read_text()) == {"token": "synthetic"}
    assert list(token.parent.glob(".token-*")) == []


def test_bad_token_never_starts_browser(monkeypatch, tmp_path):
    pytest.importorskip("google.auth")
    token = tmp_path / "token.json"
    token.write_text("not json")
    provider = GoogleCalendarProvider(Settings(google_calendar_enabled=True, google_calendar_token_path=token))
    with pytest.raises(CalendarProviderError) as raised:
        provider._load_credentials()
    assert raised.value.status == "not_connected"


def test_auth_setup_sanitizes_unexpected_oauth_error(monkeypatch, tmp_path, capsys):
    flow_module = pytest.importorskip("google_auth_oauthlib.flow")
    client = tmp_path / "client.json"
    client.write_text("{}")

    def fail(*args, **kwargs):
        raise RuntimeError("private refresh_token=synthetic-secret")

    monkeypatch.setattr(flow_module.InstalledAppFlow, "from_client_secrets_file", fail)
    with pytest.raises(GoogleAuthSetupError) as raised:
        authenticate_google_calendar(Settings(google_calendar_credentials_path=client))
    assert "synthetic-secret" not in str(raised.value)
    assert capsys.readouterr() == ("", "")


def test_cli_preserves_existing_quick_entry_delegate(monkeypatch):
    seen = []
    monkeypatch.setattr(quick_entry, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["quick", "task", "--title", "Task with spaces"]) == 0
    assert seen == [["quick", "task", "--title", "Task with spaces"]]


def test_auth_cli_failure_does_not_print_secret(monkeypatch, capsys):
    from nats_assistant.providers import google_calendar

    def fail(settings):
        raise GoogleAuthSetupError("Check OAuth setup")

    monkeypatch.setattr(google_calendar, "authenticate_google_calendar", fail)
    assert cli.main(["calendar", "google", "auth"]) == 1
    assert capsys.readouterr().err == "Check OAuth setup\n"
