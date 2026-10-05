from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CaptureStatus(str, Enum):
    INBOX = "inbox"
    PROCESSED = "processed"
    ARCHIVED = "archived"


class CaptureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=5000)]
    source: str = "nats"
    status: CaptureStatus = CaptureStatus.INBOX

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must not be blank")
        return value


class CaptureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=5000)] | None = None
    status: CaptureStatus | None = None

    @model_validator(mode="after")
    def validate_update_fields(self) -> "CaptureUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if self.text is not None:
            cleaned = self.text.strip()
            if not cleaned:
                raise ValueError("Text must not be blank")
            self.text = cleaned
        return self

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Text must not be blank")
        return value


class CaptureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    text: str
    status: CaptureStatus
    source: str
    created_at: datetime
    updated_at: datetime
