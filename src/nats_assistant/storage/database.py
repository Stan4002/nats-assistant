from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from nats_assistant.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    settings = get_settings()
    settings.ensure_data_dir()
    return URL.create("sqlite", database=str(settings.database_file))


def create_database_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    settings.ensure_data_dir()
    return create_engine(
        URL.create("sqlite", database=str(settings.database_file)),
        connect_args={"check_same_thread": False},
        future=True,
    )


def init_db(engine: Engine) -> None:
    from nats_assistant.storage import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
