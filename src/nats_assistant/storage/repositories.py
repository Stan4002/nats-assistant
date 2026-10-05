from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from nats_assistant.core.captures import CaptureCreate, CaptureStatus, CaptureUpdate
from nats_assistant.core.tasks import TaskCreate, TaskUpdate
from nats_assistant.storage.models import Capture, Priority, Task


class CaptureRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, capture_data: CaptureCreate) -> Capture:
        values = capture_data.model_dump()
        values["status"] = capture_data.status if hasattr(capture_data, "status") else CaptureStatus.INBOX
        values["source"] = values.get("source") or "nats"
        now = datetime.now(timezone.utc)
        if "status" not in values or values["status"] is None:
            values["status"] = CaptureStatus.INBOX
        capture = Capture(**values, created_at=now, updated_at=now)
        self.session.add(capture)
        self.session.commit()
        self.session.refresh(capture)
        return capture

    def list(self, status: CaptureStatus | None = None) -> list[Capture]:
        statement = select(Capture)
        if status is not None:
            statement = statement.where(Capture.status.is_(status))
        statement = statement.order_by(Capture.created_at.asc())
        return list(self.session.scalars(statement))

    def get(self, capture_id: str) -> Capture | None:
        return self.session.get(Capture, capture_id)

    def update(self, capture: Capture, changes: CaptureUpdate) -> Capture:
        for field, value in changes.model_dump(exclude_unset=True).items():
            if field == "status" and value is not None:
                value = CaptureStatus(value)
            setattr(capture, field, value)
        capture.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(capture)
        return capture

    def count_inbox(self) -> int:
        return self.session.scalar(select(func.count()).select_from(Capture).where(Capture.status.is_(CaptureStatus.INBOX))) or 0


class TaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, task_data: TaskCreate) -> Task:
        values = task_data.model_dump()
        values["priority"] = Priority(values["priority"].value)
        now = datetime.now(timezone.utc)
        task = Task(**values, source="nats", created_at=now, updated_at=now)
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def list(self, completed: bool | None = None) -> list[Task]:
        statement = select(Task)
        if completed is not None:
            statement = statement.where(Task.completed.is_(completed))
        statement = statement.order_by(
            Task.completed.asc(),
            Task.due.asc().nulls_last(),
            Task.created_at.asc(),
        )
        return list(self.session.scalars(statement))

    def get(self, task_id: str) -> Task | None:
        return self.session.get(Task, task_id)

    def update(self, task: Task, changes: TaskUpdate) -> Task:
        for field, value in changes.model_dump(exclude_unset=True).items():
            if field == "priority" and value is not None:
                value = Priority(value.value)
            setattr(task, field, value)
        task.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(task)
        return task

    def delete(self, task: Task) -> None:
        self.session.delete(task)
        self.session.commit()

    def count_pending(self) -> int:
        return self.session.scalar(select(func.count()).select_from(Task).where(Task.completed.is_(False))) or 0

    def count_due_between(self, start: datetime, end: datetime) -> int:
        statement = select(func.count()).select_from(Task).where(
            Task.completed.is_(False),
            Task.due >= start,
            Task.due < end,
        )
        return self.session.scalar(statement) or 0

    def list_relevant(self, limit: int = 3) -> list[Task]:
        priority_order = case(
            (Task.priority == Priority.CRITICAL, 0),
            (Task.priority == Priority.HIGH, 1),
            (Task.priority == Priority.NORMAL, 2),
            else_=3,
        )
        statement = (
            select(Task)
            .where(Task.completed.is_(False))
            .order_by(priority_order, Task.due.asc().nulls_last(), Task.created_at.asc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))
