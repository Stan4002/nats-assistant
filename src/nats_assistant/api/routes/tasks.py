from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from nats_assistant.api.dependencies import get_db_session
from nats_assistant.core.tasks import TaskCreate, TaskResponse, TaskUpdate
from nats_assistant.storage.models import Task
from nats_assistant.storage.repositories import TaskRepository

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


def _get_task_or_404(repository: TaskRepository, task_id: str) -> Task:
    task = repository.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    completed: bool | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[Task]:
    return TaskRepository(session).list(completed=completed)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(task_data: TaskCreate, session: Session = Depends(get_db_session)) -> Task:
    return TaskRepository(session).create(task_data)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, session: Session = Depends(get_db_session)) -> Task:
    return _get_task_or_404(TaskRepository(session), task_id)


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    changes: TaskUpdate,
    session: Session = Depends(get_db_session),
) -> Task:
    repository = TaskRepository(session)
    task = _get_task_or_404(repository, task_id)
    return repository.update(task, changes)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str, session: Session = Depends(get_db_session)) -> Response:
    repository = TaskRepository(session)
    task = _get_task_or_404(repository, task_id)
    repository.delete(task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
