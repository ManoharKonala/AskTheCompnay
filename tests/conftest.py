import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is in path and safe UTF-8 encoding on Windows
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from src.main import app
from src.db.connection import get_db
from src.db.models import Base

# Setup in-memory SQLite for testing DB interactions without Postgres
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT

@pytest.fixture()
def db_session():
    # Create the tables in the in-memory SQLite DB
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

from unittest.mock import patch, MagicMock

# ==========================================
# External Service Mocks
# ==========================================

@pytest.fixture(autouse=True)
def mock_qdrant():
    """Prevent tests from attempting to connect to Qdrant."""
    with patch("src.db.connection.qdrant_client") as m:
        yield m

@pytest.fixture(autouse=True)
def mock_redis():
    """Prevent tests from attempting to connect to Redis."""
    try:
        with patch("redis.Redis.from_url") as r, patch("redisvl.index.SearchIndex", create=True):
            yield r
    except Exception:
        yield None

@pytest.fixture(autouse=True)
def mock_minio():
    """Prevent tests from attempting to connect to MinIO."""
    with patch("src.main.minio_client") as m:
        yield m

@pytest.fixture(autouse=True)
def mock_celery():
    """Prevent tests from dispatching real Celery tasks."""
    with patch("src.main.ingest_file_task.delay") as m:
        yield m

class MockFixture:
    def __init__(self):
        self._patches = []
    
    def patch(self, *args, **kwargs):
        p = patch(*args, **kwargs)
        mock_obj = p.start()
        self._patches.append(p)
        return mock_obj

    def MagicMock(self, *args, **kwargs):
        return MagicMock(*args, **kwargs)

    def stopall(self):
        for p in reversed(self._patches):
            try:
                p.stop()
            except Exception:
                pass

@pytest.fixture
def mocker():
    """Universal mocker fixture based on standard unittest.mock."""
    m = MockFixture()
    try:
        yield m
    finally:
        m.stopall()
