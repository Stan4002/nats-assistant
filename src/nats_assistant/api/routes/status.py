from fastapi import APIRouter, Request

from nats_assistant.core.models import StatusResponse

router = APIRouter(prefix="/v1")


@router.get("/status", response_model=StatusResponse)
def get_status(request: Request) -> StatusResponse:
    settings = request.app.state.settings
    return StatusResponse(service=settings.service_name, status="online", version=settings.version)
