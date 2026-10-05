from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from nats_assistant.api.dependencies import get_db_session
from nats_assistant.config import Settings
from nats_assistant.core.calendar_context import build_calendar_summary
from nats_assistant.core.models import HomeSummary
from nats_assistant.core.tasks import TaskResponse
from nats_assistant.storage.repositories import CaptureRepository, TaskRepository

router = APIRouter(prefix="/v1", tags=["home"])


@router.get("/home", response_model=HomeSummary)
def get_home(request: Request, session: Session = Depends(get_db_session)) -> HomeSummary:
    settings: Settings = request.app.state.settings
    local_timezone = ZoneInfo(settings.timezone)
    now_local = datetime.now(local_timezone)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=local_timezone)
    end_local = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=local_timezone)

    repository = TaskRepository(session)
    captures_repository = CaptureRepository(session)
    tasks = repository.list_relevant(limit=5)
    return HomeSummary(
        tasks={
            "pending": repository.count_pending(),
            "due_today": repository.count_due_between(
                start_local.astimezone(timezone.utc),
                end_local.astimezone(timezone.utc),
            ),
            "items": [TaskResponse.model_validate(task) for task in tasks],
        },
        captures={"inbox_count": captures_repository.count_inbox()},
        calendar=build_calendar_summary(
            request.app.state.calendar_provider,
            now_local,
            max_events=settings.calendar_max_events,
            lookahead_days=settings.calendar_lookahead_days,
        ),
    )
