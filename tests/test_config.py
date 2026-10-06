import json
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from nats_assistant import cli
from nats_assistant.config import ConfigurationError, Settings, get_config_path, get_settings, read_config, set_config_value


def test_missing_config_uses_defaults():
    assert read_config() == {}
    assert get_settings().google_calendar_enabled is False
    assert get_settings().host == "127.0.0.1"
    assert get_settings().port == 8765
    assert not get_config_path().exists()


def test_persisted_config_and_source_precedence(monkeypatch):
    set_config_value("timezone", "Africa/Lusaka")
    set_config_value("google_calendar_enabled", "true")
    set_config_value("google_calendar_id", "primary")
    assert get_settings().google_calendar_enabled is True
    assert get_settings().timezone == "Africa/Lusaka"
    monkeypatch.setenv("NATS_TIMEZONE", "UTC")
    assert get_settings().timezone == "UTC"
    assert Settings(timezone="Europe/Paris").timezone == "Europe/Paris"
    assert read_config()["timezone"] == "Africa/Lusaka"


def test_config_path_default_and_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("NATS_CONFIG_FILE")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_config_path() == tmp_path / ".config/nats-assistant/config.toml"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert get_config_path() == tmp_path / "xdg/nats-assistant/config.toml"


@pytest.mark.parametrize("key,value", [
    ("timezone", "not-a-timezone"), ("google_calendar_enabled", "perhaps"),
    ("port", "0"), ("port", "65536"), ("host", "0.0.0.0"),
    ("host", "192.168.1.1"), ("google_calendar_id", ""),
])
def test_invalid_config_not_written(key, value):
    with pytest.raises(ValidationError):
        set_config_value(key, value)
    assert not get_config_path().exists()


def test_malformed_file_and_secrets_are_controlled():
    path = get_config_path()
    path.parent.mkdir(parents=True)
    path.write_text('timezone = "unfinished')
    with pytest.raises(ConfigurationError):
        get_settings()
    path.write_text('refresh_token = "synthetic-secret"')
    with pytest.raises(ConfigurationError) as raised:
        get_settings()
    assert "synthetic-secret" not in str(raised.value)


def test_config_cli_roundtrip_private_file(capsys):
    assert cli.main(["config", "set", "timezone", "Africa/Lusaka"]) == 0
    assert cli.main(["config", "set", "google_calendar_enabled", "true"]) == 0
    assert cli.main(["config", "set", "google_calendar_id", 'Calendar "quoted" \\ safe']) == 0
    capsys.readouterr()
    assert cli.main(["config", "get", "google_calendar_enabled"]) == 0
    assert capsys.readouterr().out == "true\n"
    assert cli.main(["config", "show"]) == 0
    values = json.loads(capsys.readouterr().out)
    assert values["timezone"] == "Africa/Lusaka"
    assert values["google_calendar_enabled"] is True
    assert values["google_calendar_id"] == 'Calendar "quoted" \\ safe'
    assert "refresh_token" not in values and "client_secret" not in values
    path = get_config_path()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert list(path.parent.glob(".config.toml-*")) == []


@pytest.mark.parametrize("key", ["access_token", "refresh_token", "client_secret", "unknown"])
def test_config_cli_rejects_secret_and_unknown_keys(key, capsys):
    assert cli.main(["config", "set", key, "synthetic-secret"]) == 1
    assert cli.main(["config", "get", key]) == 1
    assert "synthetic-secret" not in str(capsys.readouterr())
    assert not get_config_path().exists()


def test_invalid_value_preserves_existing_file_and_redacts_error(capsys):
    set_config_value("timezone", "UTC")
    before = get_config_path().read_bytes()
    assert cli.main(["config", "set", "port", "synthetic-secret"]) == 1
    assert "synthetic-secret" not in str(capsys.readouterr())
    assert get_config_path().read_bytes() == before


def test_environment_cannot_mask_bad_persisted_value(monkeypatch):
    monkeypatch.setenv("NATS_TIMEZONE", "UTC")
    with pytest.raises(ValidationError):
        set_config_value("timezone", "bad-zone")
    monkeypatch.setenv("NATS_HOST", "0.0.0.0")
    set_config_value("timezone", "Africa/Lusaka")
    assert read_config()["timezone"] == "Africa/Lusaka"


def test_calendar_enabled_survives_fresh_process(tmp_path):
    set_config_value("google_calendar_enabled", "true")
    set_config_value("timezone", "Africa/Lusaka")
    set_config_value("data_dir", str(tmp_path / "data"))
    set_config_value("google_calendar_token_path", str(tmp_path / "missing-token.json"))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("NATS_")}
    environment["NATS_CONFIG_FILE"] = str(get_config_path())
    result = subprocess.run([sys.executable, "-c", (
        "from nats_assistant.api.server import create_app; "
        "app = create_app(); "
        "assert app.state.settings.google_calendar_enabled; "
        "assert app.state.settings.timezone == 'Africa/Lusaka'; "
        "assert app.state.calendar_provider.availability() == 'not_connected'; "
        "print('persisted')"
    )], env=environment, capture_output=True, text=True, check=True, timeout=15)
    assert result.stdout.strip() == "persisted"
