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
