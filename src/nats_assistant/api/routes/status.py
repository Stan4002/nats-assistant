from fastapi import APIRouter

from nats_assistant.config import get_settings
from nats_assistant.core.models import StatusResponse

router = APIRouter(prefix="/v1")


@router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    settings = get_settings()
    return StatusResponse(service=settings.service_name, status="online", version=settings.version)
