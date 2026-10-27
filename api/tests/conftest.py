import pytest
from fastapi.testclient import TestClient

from carebridge.config import Settings
from carebridge.main import create_app


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests must not pick up .env or api/.env.
    return Settings(_env_file=None, env="test", bq_project="test-project")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
