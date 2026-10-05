from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from nats_assistant.api.dependencies import get_db_session
from nats_assistant.core.captures import CaptureCreate, CaptureResponse, CaptureStatus, CaptureUpdate
from nats_assistant.storage.models import Capture
from nats_assistant.storage.repositories import CaptureRepository

router = APIRouter(prefix="/v1/captures", tags=["captures"])


def _get_capture_or_404(repository: CaptureRepository, capture_id: str) -> Capture:
    capture = repository.get(capture_id)
    if capture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture not found")
    return capture


@router.get("", response_model=list[CaptureResponse])
def list_captures(
    status: CaptureStatus | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> list[Capture]:
    return CaptureRepository(session).list(status=status)


@router.post("", response_model=CaptureResponse, status_code=status.HTTP_201_CREATED)
def create_capture(capture_data: CaptureCreate, session: Session = Depends(get_db_session)) -> Capture:
    return CaptureRepository(session).create(capture_data)


@router.get("/{capture_id}", response_model=CaptureResponse)
def get_capture(capture_id: str, session: Session = Depends(get_db_session)) -> Capture:
    return _get_capture_or_404(CaptureRepository(session), capture_id)


@router.patch("/{capture_id}", response_model=CaptureResponse)
def update_capture(
    capture_id: str,
    changes: CaptureUpdate,
    session: Session = Depends(get_db_session),
) -> Capture:
    repository = CaptureRepository(session)
    capture = _get_capture_or_404(repository, capture_id)
    return repository.update(capture, changes)
