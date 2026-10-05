import pytest
import socket
from fastapi.testclient import TestClient

from nats_assistant.api.server import create_app
from nats_assistant.config import Settings


@pytest.fixture(autouse=True)
def block_external_connections(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must not make network connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", timezone="UTC", google_calendar_enabled=False)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
