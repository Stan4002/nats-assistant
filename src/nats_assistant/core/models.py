from typing import Any, Optional

from pydantic import BaseModel, Field

from nats_assistant.core.tasks import TaskResponse


class TaskSummary(BaseModel):
    pending: int = 0
    due_today: int = 0
    items: list[TaskResponse] = Field(default_factory=list)


class CommsSummary(BaseModel):
    attention_count: int = 0
    items: list[Any] = Field(default_factory=list)


class HomeSummary(BaseModel):
    now: Optional[str] = None
    next: Optional[str] = None
    upcoming: list[Any] = Field(default_factory=list)
    tasks: TaskSummary = Field(default_factory=TaskSummary)
    comms: CommsSummary = Field(default_factory=CommsSummary)


class StatusResponse(BaseModel):
    service: str = "nats-assistant"
    status: str = "online"
    version: str = "0.1.0"
