import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

    POSTGRES_USER = os.getenv("POSTGRES_USER", "askthecompany")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "your_secure_password")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "askthecompany")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    MODEL_NAME = os.getenv("MODEL_NAME", "llama3.1:8b")

    JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_key_change_me_in_production")
