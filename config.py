import os
from dotenv import load_dotenv

# Disable Hugging Face symlinks on Windows to prevent WinError 1314 privilege error
import huggingface_hub.file_download
huggingface_hub.file_download.are_symlinks_supported = lambda *args, **kwargs: False
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
load_dotenv()

class Config:
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

    POSTGRES_USER = os.getenv("POSTGRES_USER", "askthecompany")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "your_secure_password")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "askthecompany")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    DATABASE_URL = f"postgresql+pg8000://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    MODEL_NAME = os.getenv("MODEL_NAME", "llama3.1:8b")

    # Inference Backend: "ollama" or "vllm"
    INFERENCE_BACKEND = os.getenv("INFERENCE_BACKEND", "ollama").lower()
    VLLM_API_URL = os.getenv("VLLM_API_URL", "http://localhost:8000/v1")
    VLLM_API_KEY = os.getenv("VLLM_API_KEY", "EMPTY")

    # Authentication Mode: "local" (JWT) or "oidc" (Keycloak/Okta)
    AUTH_MODE = os.getenv("AUTH_MODE", "local").lower()
    JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_key_change_me_in_production")
    OIDC_ISSUER_URL = os.getenv("OIDC_ISSUER_URL", "http://localhost:8080/realms/askthecompany")
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "askthecompany-app")
    OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", None)

    # CORS Origins for Next.js and Streamlit
    CORS_ORIGINS = [
        origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8501").split(",") if origin.strip()
    ]
