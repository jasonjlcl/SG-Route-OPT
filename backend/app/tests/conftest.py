import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ONEMAP_EMAIL", "")
os.environ.setdefault("ONEMAP_PASSWORD", "")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_app.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6399/0")
os.environ.setdefault("JOBS_FORCE_INLINE", "true")

from app.main import app
from app.models import Base
from app.utils.db import engine


@pytest.fixture(autouse=True)
def reset_db():
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
