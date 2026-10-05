from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from nats_assistant.api.routes.captures import router as captures_router
from nats_assistant.api.routes.home import router as home_router
from nats_assistant.api.routes.status import router as status_router
from nats_assistant.api.routes.tasks import router as tasks_router
from nats_assistant.config import Settings, get_settings
from nats_assistant.providers.calendar import CalendarProvider
from nats_assistant.providers.google_calendar import GoogleCalendarProvider
from nats_assistant.storage.database import create_database_engine, init_db


def create_app(settings: Settings | None = None, calendar_provider: CalendarProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_database_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        yield
        engine.dispose()

    app = FastAPI(title=settings.service_name, version=settings.version, lifespan=lifespan)
    app.state.settings = settings
    app.state.calendar_provider = calendar_provider
    if calendar_provider is None and settings.google_calendar_enabled:
        app.state.calendar_provider = GoogleCalendarProvider(settings)
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.include_router(status_router)
    app.include_router(home_router)
    app.include_router(tasks_router)
    app.include_router(captures_router)
    return app


app = create_app()
