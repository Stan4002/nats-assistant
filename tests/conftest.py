import pytest
from fastapi.testclient import TestClient

from nats_assistant.api.server import create_app
from nats_assistant.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", timezone="UTC")
    with TestClient(create_app(settings)) as test_client:
        yield test_client
