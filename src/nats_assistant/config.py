from datetime import datetime
from ipaddress import ip_address
import json
import os
from pathlib import Path
import tempfile
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_KEYS = frozenset({
    "host", "port", "timezone", "data_dir", "database_file",
    "google_calendar_enabled", "google_calendar_id",
    "google_calendar_credentials_path", "google_calendar_token_path",
    "google_calendar_timeout_seconds", "google_calendar_fetch_limit",
    "calendar_max_events", "calendar_lookahead_days", "calendar_refresh_seconds",
})


class ConfigurationError(ValueError):
    """Controlled errors that never include file contents or supplied values."""


def get_config_path() -> Path:
    override = os.environ.get("NATS_CONFIG_FILE")
    if override:
        return Path(override).expanduser().absolute()
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root.expanduser().absolute() / "nats-assistant" / "config.toml"


def read_config() -> dict:
    path = get_config_path()
    try:
        with path.open("rb") as stream:
            values = tomllib.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError):
        raise ConfigurationError("Unable to read NATS configuration; check config.toml syntax and permissions") from None
    if values.keys() - CONFIG_KEYS:
        raise ConfigurationError("NATS configuration contains unsupported keys; secrets do not belong in config.toml")
    return values


def write_private_file(path: Path, contents: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(contents)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _system_timezone_name() -> str:
    local_timezone = datetime.now().astimezone().tzinfo
    timezone_name = getattr(local_timezone, "key", None)
    return timezone_name or "UTC"


class Settings(BaseSettings):
    service_name: str = "nats-assistant"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".local" / "share" / "nats-assistant")
    database_file: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "share" / "nats-assistant" / "nats.db"
    )
    timezone: str = Field(default_factory=_system_timezone_name)
    google_calendar_enabled: bool = False
    google_calendar_credentials_path: Path = Field(
        default_factory=lambda: Path.home() / ".config" / "nats-assistant" / "google" / "client_secret.json"
    )
    google_calendar_token_path: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "share" / "nats-assistant" / "google" / "token.json"
    )
    google_calendar_id: str = Field(default="primary", min_length=1)
    google_calendar_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    google_calendar_fetch_limit: int = Field(default=200, ge=1, le=1000)
    calendar_max_events: int = Field(default=20, ge=1, le=100)
    calendar_lookahead_days: int = Field(default=7, ge=1, le=31)
    calendar_refresh_seconds: int = Field(default=120, ge=30, le=3600)

    model_config = SettingsConfigDict(env_prefix="NATS_", case_sensitive=False, extra="ignore")

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                   dotenv_settings, file_secret_settings):
        return init_settings, env_settings, read_config, file_secret_settings

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        try:
            if ip_address(value).is_loopback:
                return value
        except ValueError:
            pass
        raise ValueError("NATS host must be a loopback IP address")

    @field_validator("data_dir", "database_file", mode="before")
    @classmethod
    def expand_paths(cls, value):
        if value is None:
            return value
        return Path(value).expanduser()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Timezone must be a valid IANA timezone") from None
        return value

    @field_validator("google_calendar_credentials_path", "google_calendar_token_path", mode="before")
    @classmethod
    def validate_google_paths(cls, value):
        path = Path(value).expanduser().resolve()
        project_root = Path(__file__).resolve().parents[2]
        if (project_root / "pyproject.toml").is_file() and path.is_relative_to(project_root):
            raise ValueError("Google auth files must be stored outside the source repository")
        return path

    @model_validator(mode="after")
    def derive_database_file(self) -> "Settings":
        if "database_file" not in self.model_fields_set:
            self.database_file = self.data_dir / "nats.db"
        return self

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.database_file.parent != self.data_dir:
            self.database_file.parent.mkdir(parents=True, exist_ok=True)
        return self.data_dir


def get_settings() -> Settings:
    return Settings()


class _PersistedSettings(Settings):
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                   dotenv_settings, file_secret_settings):
        return (init_settings,)


def set_config_value(key: str, value: str) -> Path:
    if key not in CONFIG_KEYS:
        raise ConfigurationError("Unsupported configuration key")
    values = read_config()
    values[key] = value
    # Validate persisted values without allowing environment overrides to hide
    # a bad value. Defaults cover keys not yet explicitly configured.
    settings = _PersistedSettings(**values)
    serialized = settings.model_dump(mode="json")
    lines = ["# NATS Assistant settings. OAuth secrets belong in separate private files."]
    for name in sorted(values):
        item = serialized[name]
        encoded = str(item).lower() if isinstance(item, bool) else json.dumps(item, ensure_ascii=False)
        lines.append(f"{name} = {encoded}")
    path = get_config_path()
    write_private_file(path, "\n".join(lines) + "\n")
    return path
