import os
import uuid
import logging
import tempfile
import shutil
import time
from functools import lru_cache
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Query, Request, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
try:
    from prometheus_fastapi_instrumentator import Instrumentator
except ImportError:
    Instrumentator = None

try:
    from minio import Minio
except ImportError:
    Minio = None

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
except ImportError:
    class Limiter:
        def __init__(self, key_func=None):
            pass
        def limit(self, limit_value):
            def decorator(func):
                return func
            return decorator
    def get_remote_address(request):
        return "127.0.0.1"
    class RateLimitExceeded(Exception):
        pass
    def _rate_limit_exceeded_handler(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

from config import Config
from src.db.connection import get_db, init_dbs
from src.db.models import User, AuditLog, FailedIngestion
from src.auth.jwt import get_password_hash, verify_password, create_access_token, decode_access_token
from src.auth.oidc import verify_oidc_token
from src.ingestion.pipeline import IngestionPipeline
from src.retrieval.search import SearchService
from src.retrieval.llm import LLMService
from src.celery_app import ingest_file_task

# ==========================================
# Logging Configuration
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("askthecompany.api")

# ==========================================
# Rate Limiter
# ==========================================
limiter = Limiter(key_func=get_remote_address)

# ==========================================
# Application Lifespan & Initialization
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schemas and vector collections...")
    init_dbs()
    logger.info("Application startup complete.")
    yield
    logger.info("Application shutdown.")

app = FastAPI(
    title="AskTheCompany Enterprise API",
    description="Zero-Trust, High-Throughput Enterprise RAG with Payload ACLs & Presidio PII Redaction",
    version="2.0.0",
    lifespan=lifespan
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ==========================================
# CORS Middleware for Next.js & UI
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Request Tracing Middleware
# ==========================================
@app.middleware("http")
async def add_correlation_id_and_timing(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()
    
    response: Response = await call_next(request)
    
    process_time = time.perf_counter() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{process_time * 1000:.2f}"
    return response

# Instrument FastAPI with Prometheus if available
if Instrumentator:
    try:
        Instrumentator().instrument(app).expose(app)
    except Exception as e:
        logger.warning(f"Prometheus instrumentator notice: {e}")

# ==========================================
# MinIO Client
# ==========================================
minio_client = None
if Minio:
    try:
        minio_client = Minio(
            Config.MINIO_ENDPOINT,
            access_key=Config.MINIO_ACCESS_KEY,
            secret_key=Config.MINIO_SECRET_KEY,
            secure=Config.MINIO_SECURE
        )
        if not minio_client.bucket_exists("documents"):
            minio_client.make_bucket("documents")
    except Exception as e:
        logger.warning(f"MinIO initialization notice: {e}")

# ==========================================
# OAuth2 Scheme
# ==========================================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Thread-safe singleton service initialization
@lru_cache(maxsize=1)
def get_pipeline():
    return IngestionPipeline()

@lru_cache(maxsize=1)
def get_llm_service():
    return LLMService()

@lru_cache(maxsize=1)
def get_search_service():
    return SearchService(llm_service=get_llm_service())

# ==========================================
# Pydantic Schemas
# ==========================================
class UserRegister(BaseModel):
    username: str
    password: str

class UserUpdateGroups(BaseModel):
    groups: List[str]

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Query text (max 2000 chars)")

class QueryResponse(BaseModel):
    answer: str
    citations: List[str]
    retrieved_chunks: List[Dict[str, Any]]
    cached: bool

class FailedIngestionResponse(BaseModel):
    id: int
    filepath: str
    source_type: str
    error_message: str
    retry_count: int
    status: str
    created_at: str

# ==========================================
# Authentication Dependency (Local JWT + OIDC)
# ==========================================
def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    if Config.AUTH_MODE == "oidc":
        payload = verify_oidc_token(token)
    else:
        payload = decode_access_token(token)

    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload

# ==========================================
# Authentication Routes
# ==========================================
@app.post("/auth/register", status_code=status.HTTP_201_CREATED, tags=["Authentication"])
@limiter.limit("5/minute")
def register(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    if Config.AUTH_MODE == "oidc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Local registration disabled. System is in OIDC mode (manage users in Keycloak/Okta)."
        )
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    hashed_password = get_password_hash(user_data.password)
    user = User(
        username=user_data.username,
        hashed_password=hashed_password,
        groups=["Public"]
    )
    db.add(user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/auth/token", tags=["Authentication"])
@limiter.limit("10/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    if Config.AUTH_MODE == "oidc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direct login endpoint disabled in OIDC mode. Authenticate via your Identity Provider."
        )
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token = create_access_token(
        data={"sub": user.username, "groups": user.groups}
    )
    return {"access_token": access_token, "token_type": "bearer", "groups": user.groups}

@app.put("/admin/users/{username}/groups", status_code=status.HTTP_200_OK, tags=["Administration"])
def update_user_groups(
    username: str, 
    group_data: UserUpdateGroups, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user_payload)
):
    if "admin" not in current_user.get("groups", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.groups = group_data.groups
    db.commit()
    return {"message": f"Updated groups for {username}", "groups": user.groups}

# ==========================================
# Health & Diagnostic Routes
# ==========================================
@app.get("/health", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def health_check(db: Session = Depends(get_db)):
    health_status = {
        "postgres": False,
        "qdrant": False,
        "redis": False,
        "inference_backend": Config.INFERENCE_BACKEND,
        "auth_mode": Config.AUTH_MODE
    }
    
    # Check Postgres
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        health_status["postgres"] = True
    except Exception as e:
        logger.warning(f"Postgres health check failed: {e}")

    # Check Qdrant
    try:
        from src.db.connection import qdrant_client
        qdrant_client.get_collections()
        health_status["qdrant"] = True
    except Exception as e:
        logger.warning(f"Qdrant health check failed: {e}")
        
    # Check Redis
    try:
        from src.retrieval.search import redis_client, redis_connected
        if redis_connected and redis_client.ping():
            health_status["redis"] = True
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
        
    return health_status

# ==========================================
# Ingestion Endpoints (Async & Non-blocking)
# ==========================================
@app.post("/ingest", status_code=status.HTTP_200_OK, tags=["Ingestion"])
async def trigger_ingestion(user_payload: Dict[str, Any] = Depends(get_current_user_payload)):
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        seed_dir = os.path.join(project_root, 'data', 'seed')
        
        source_mapping = {
            "confluence": "confluence",
            "slack": "slack",
            "excel": "excel",
            "pdfs": "pdf"
        }
        
        task_ids = []
        for folder_name, source_type in source_mapping.items():
            folder_path = os.path.join(seed_dir, folder_name)
            if not os.path.exists(folder_path):
                continue
                
            for root, _, files in os.walk(folder_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    if file.startswith("~$") or file.startswith("temp_"):
                        continue
                    
                    object_name = f"{uuid.uuid4()}_{file}"
                    if minio_client:
                        try:
                            # Non-blocking MinIO upload via threadpool
                            await run_in_threadpool(minio_client.fput_object, "documents", object_name, filepath)
                        except Exception as e:
                            logger.warning(f"Failed to upload {file} to MinIO: {e}")
                        
                    task = ingest_file_task.delay(filepath, source_type)
                    task_ids.append(task.id)
                    
        return {"status": "success", "message": f"Dispatched {len(task_ids)} ingestion tasks to Celery.", "tasks": task_ids}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion dispatch failed: {str(e)}"
        )

@app.post("/ingest/file", status_code=status.HTTP_200_OK, tags=["Ingestion"])
async def upload_and_ingest(
    file: UploadFile = File(...), 
    user_payload: Dict[str, Any] = Depends(get_current_user_payload)
):
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        source_mapping = {
            ".md": "confluence",
            ".json": "slack",
            ".csv": "excel",
            ".xlsx": "excel",
            ".pdf": "pdf"
        }
        source_type = source_mapping.get(ext)
        if not source_type:
            raise HTTPException(status_code=400, detail=f"Unsupported file extension {ext}. Supported: .pdf, .md, .json, .csv, .xlsx")
            
        object_name = f"{uuid.uuid4()}_{file.filename}"
        
        # Save temp file in non-blocking threadpool
        def _save_and_upload():
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                shutil.copyfileobj(file.file, temp_file)
                temp_filepath = temp_file.name
            try:
                if minio_client:
                    minio_client.fput_object("documents", object_name, temp_filepath)
            finally:
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)

        await run_in_threadpool(_save_and_upload)
            
        # Dispatch Celery task with MinIO object URI
        task = ingest_file_task.delay(f"minio://documents/{object_name}", source_type)
        
        return {"status": "success", "message": "File uploaded and ingestion task dispatched.", "task": task.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )

# ==========================================
# RAG Query Endpoint (Rate-limited & Monitored)
# ==========================================
@app.post("/query", response_model=QueryResponse, tags=["Query"])
@limiter.limit("30/minute")
async def query_rag(
    request: Request,
    query_req: QueryRequest,
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
    search: SearchService = Depends(get_search_service),
    llm: LLMService = Depends(get_llm_service)
):
    username = user_payload.get("sub", "unknown_user")
    user_groups = user_payload.get("groups", ["Public"])
    query_text = query_req.query
    
    # 1. Semantic Cache Lookup (RedisVL)
    cached_answer = await run_in_threadpool(search.semantic_cache_lookup, query_text, user_groups)
    if cached_answer:
        def _record_cache_audit():
            user_obj = db.query(User).filter(User.username == username).first()
            user_id = user_obj.id if user_obj else None
            audit_log = AuditLog(
                user_id=user_id,
                query=query_text,
                response=cached_answer,
                retrieved_chunks={"source": "semantic_cache"}
            )
            db.add(audit_log)
            db.commit()

        await run_in_threadpool(_record_cache_audit)
        
        return QueryResponse(
            answer=cached_answer,
            citations=[],
            retrieved_chunks=[],
            cached=True
        )
        
    # 2. Hybrid Search with Vector ACL Filtering (Dense + Sparse + BGE-Reranker)
    retrieved_chunks = await run_in_threadpool(search.search, query_text, user_groups, 5)
    
    # 3. LLM Synthesis with Citation Validation & Confidence Gate
    answer, citations = await run_in_threadpool(llm.generate_answer, query_text, retrieved_chunks)
    
    # 4. Cache Response in Redis (non-blocking)
    chunk_groups = set()
    for chunk in retrieved_chunks:
        chunk_groups.update(chunk.get("allowed_groups", []))
    
    await run_in_threadpool(search.semantic_cache_set, query_text, answer, list(chunk_groups))
    
    # 5. Persist Audit Log in Postgres (non-blocking)
    def _record_query_audit():
        user_obj = db.query(User).filter(User.username == username).first()
        user_id = user_obj.id if user_obj else None
        
        retrieved_metadata = [
            {
                "chunk_id": chunk.get("id"),
                "filename": chunk.get("filename"),
                "source_type": chunk.get("source_type"),
                "allowed_groups": chunk.get("allowed_groups"),
                "rerank_score": chunk.get("rerank_score")
            } for chunk in retrieved_chunks
        ]
        
        audit_log = AuditLog(
            user_id=user_id,
            query=query_text,
            response=answer,
            retrieved_chunks=retrieved_metadata
        )
        db.add(audit_log)
        db.commit()

    await run_in_threadpool(_record_query_audit)
    
    return QueryResponse(
        answer=answer,
        citations=citations,
        retrieved_chunks=retrieved_chunks,
        cached=False
    )

# ==========================================
# Administration & Dead Letter Queue (DLQ)
# ==========================================
@app.get("/admin/logs", status_code=status.HTTP_200_OK, tags=["Administration"])
def get_audit_logs(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db)
):
    user_groups = user_payload.get("groups", [])
    if "admin" not in user_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
        
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()
    total = db.query(AuditLog).count()
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "query": log.query,
                "response": log.response,
                "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                "retrieved_chunks": log.retrieved_chunks
            }
            for log in logs
        ]
    }

@app.get("/admin/dlq", status_code=status.HTTP_200_OK, tags=["Administration"])
def get_dlq_records(
    status_filter: Optional[str] = Query(None, description="Filter by status (FAILED, RETRIED, RESOLVED)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db)
):
    user_groups = user_payload.get("groups", [])
    if "admin" not in user_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    
    query = db.query(FailedIngestion)
    if status_filter:
        query = query.filter(FailedIngestion.status == status_filter.upper())
        
    records = query.order_by(FailedIngestion.created_at.desc()).offset(skip).limit(limit).all()
    total = query.count()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "records": [
            {
                "id": r.id,
                "filepath": r.filepath,
                "source_type": r.source_type,
                "error_message": r.error_message,
                "retry_count": r.retry_count,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else ""
            }
            for r in records
        ]
    }

@app.post("/admin/dlq/{dlq_id}/retry", status_code=status.HTTP_200_OK, tags=["Administration"])
def retry_dlq_record(
    dlq_id: int,
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db)
):
    user_groups = user_payload.get("groups", [])
    if "admin" not in user_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
        
    record = db.query(FailedIngestion).filter(FailedIngestion.id == dlq_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="DLQ record not found")
        
    # Re-dispatch Celery task
    task = ingest_file_task.delay(record.filepath, record.source_type)
    record.status = "RETRIED"
    db.commit()
    
    return {
        "status": "success",
        "message": f"Re-dispatched task {task.id} for {record.filepath}",
        "task_id": task.id
    }
