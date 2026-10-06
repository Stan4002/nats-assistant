from nats_assistant.config import get_settings


def serve() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "nats_assistant.api.server:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
        timeout_graceful_shutdown=10,
    )
