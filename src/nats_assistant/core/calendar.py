from datetime import datetime, timezone
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class CalendarState(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    NOT_CONNECTED = "not_connected"
    ERROR = "error"


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    start: AwareDatetime
    end: AwareDatetime
    all_day: bool = False
    location: str | None = None
    source: str
    source_calendar_id: str | None = None
    source_event_id: str | None = None
    status: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarEvent":
        if self.end.astimezone(timezone.utc) <= self.start.astimezone(timezone.utc):
            raise ValueError("Event end must be after start")
        return self


class CalendarEventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[CalendarEvent] = Field(default_factory=list)
    truncated: bool = False


class CalendarSummary(BaseModel):
    status: CalendarState = CalendarState.NOT_CONNECTED
    today_count: int = 0
    next: CalendarEvent | None = None
    events: list[CalendarEvent] = Field(default_factory=list)
    truncated: bool = False
    updated_at: datetime | None = None
    stale: bool = False
