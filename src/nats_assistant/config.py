from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _system_timezone_name() -> str:
    local_timezone = datetime.now().astimezone().tzinfo
    timezone_name = getattr(local_timezone, "key", None)
    return timezone_name or "UTC"


class Settings(BaseSettings):
    service_name: str = "nats-assistant"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 8765
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

    model_config = SettingsConfigDict(env_prefix="NATS_", case_sensitive=False, extra="ignore")

    @field_validator("data_dir", "database_file", mode="before")
    @classmethod
    def expand_paths(cls, value):
        if value is None:
            return value
        return Path(value).expanduser()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
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
