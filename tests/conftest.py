import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

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

# ==========================================
# External Service Mocks
# ==========================================

@pytest.fixture(autouse=True)
def mock_qdrant(mocker):
    """Prevent tests from attempting to connect to Qdrant."""
    return mocker.patch("src.db.connection.qdrant_client")

@pytest.fixture(autouse=True)
def mock_redis(mocker):
    """Prevent tests from attempting to connect to Redis."""
    mocker.patch("redis.Redis.from_url")
    mocker.patch("redisvl.index.SearchIndex")

@pytest.fixture(autouse=True)
def mock_minio(mocker):
    """Prevent tests from attempting to connect to MinIO."""
    return mocker.patch("src.main.minio_client")

@pytest.fixture(autouse=True)
def mock_celery(mocker):
    """Prevent tests from dispatching real Celery tasks."""
    return mocker.patch("src.main.ingest_file_task.delay")
