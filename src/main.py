import os
import logging
from functools import lru_cache
from fastapi import FastAPI, Depends, HTTPException, status, Query, Request, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import Config
from src.db.connection import get_db, init_dbs
from src.db.models import User, AuditLog
from src.auth.jwt import get_password_hash, verify_password, create_access_token, decode_access_token
from src.ingestion.pipeline import IngestionPipeline
from src.retrieval.search import SearchService
from src.retrieval.llm import LLMService
from prometheus_fastapi_instrumentator import Instrumentator
import uuid
from minio import Minio
from src.celery_app import ingest_file_task

logger = logging.getLogger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="AskTheCompany API", version="1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Instrument FastAPI with Prometheus
Instrumentator().instrument(app).expose(app)

# Initialize MinIO client
minio_client = Minio(
    Config.MINIO_ENDPOINT,
    access_key=Config.MINIO_ACCESS_KEY,
    secret_key=Config.MINIO_SECRET_KEY,
    secure=Config.MINIO_SECURE
)
# Create bucket if it doesn't exist
try:
    if not minio_client.bucket_exists("documents"):
        minio_client.make_bucket("documents")
except Exception as e:
    logger.warning(f"MinIO initialization error: {e}")


# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Thread-safe singleton service initialization using lru_cache
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

# ==========================================
# Authentication Dependency
# ==========================================
def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload

# ==========================================
# Routes
# ==========================================
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_dbs()
    yield

app.router.lifespan_context = lifespan

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    # Check if user already exists
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

@app.post("/auth/token")
@limiter.limit("10/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
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
    return {"access_token": access_token, "token_type": "bearer"}

@app.put("/admin/users/{username}/groups", status_code=status.HTTP_200_OK)
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
    return {"message": f"Updated groups for {username}"}

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    health_status = {
        "postgres": False,
        "qdrant": False,
        "redis": False
    }
    
    # Check Postgres
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        health_status["postgres"] = True
    except Exception:
        pass

    # Check Qdrant
    try:
        from src.db.connection import qdrant_client
        qdrant_client.get_collections()
        health_status["qdrant"] = True
    except Exception:
        pass
        
    # Check Redis
    try:
        from src.retrieval.search import redis_client, redis_connected
        if redis_connected and redis_client.ping():
            health_status["redis"] = True
    except Exception:
        pass
        
    return health_status

@app.post("/ingest", status_code=status.HTTP_200_OK)
def trigger_ingestion(user_payload: Dict[str, Any] = Depends(get_current_user_payload)):
    # Requires authentication to prevent unauthorized ingestion
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        seed_dir = os.path.join(project_root, 'data', 'seed')
        
        # Subdirectories map to source types
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
                    
                    # Upload to MinIO
                    object_name = f"{uuid.uuid4()}_{file}"
                    try:
                        minio_client.fput_object("documents", object_name, filepath)
                    except Exception as e:
                        logger.warning(f"Failed to upload {file} to MinIO: {e}")
                        
                    # Dispatch Celery task
                    # In a fully distributed system, we would pass the MinIO object name.
                    # Here we pass the local filepath for simplicity since Celery runs locally.
                    task = ingest_file_task.delay(filepath, source_type)
                    task_ids.append(task.id)
                    
        return {"status": "success", "message": f"Dispatched {len(task_ids)} ingestion tasks to Celery.", "tasks": task_ids}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion dispatch failed: {str(e)}"
        )

@app.post("/ingest/file", status_code=status.HTTP_200_OK)
async def upload_and_ingest(file: UploadFile = File(...), user_payload: Dict[str, Any] = Depends(get_current_user_payload)):
    try:
        # Infer source type
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
            raise HTTPException(status_code=400, detail=f"Unsupported file extension {ext}")
            
        object_name = f"{uuid.uuid4()}_{file.filename}"
        
        # Save to a temporary file to upload to MinIO
        import tempfile
        import shutil
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_filepath = temp_file.name
            
        try:
            minio_client.fput_object("documents", object_name, temp_filepath)
        finally:
            os.remove(temp_filepath)
            
        # Dispatch Celery task with the MinIO object name
        task = ingest_file_task.delay(f"minio://documents/{object_name}", source_type)
        
        return {"status": "success", "message": "File uploaded and task dispatched.", "task": task.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )

@app.post("/query", response_model=QueryResponse)
def query_rag(
    request: QueryRequest,
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
    search: SearchService = Depends(get_search_service),
    llm: LLMService = Depends(get_llm_service)
):
    username = user_payload.get("sub")
    user_groups = user_payload.get("groups", [])
    query_text = request.query
    
    # 1. Check Semantic Cache in Redis
    cached_answer = search.semantic_cache_lookup(query_text, user_groups)
    if cached_answer:
        # Save to Audit Log
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
        
        return QueryResponse(
            answer=cached_answer,
            citations=[],
            retrieved_chunks=[],
            cached=True
        )
        
    # 2. Perform Hybrid Search with ACL Filtering
    retrieved_chunks = search.search(query_text, user_groups, limit=5)
    
    # 3. Generate Answer with Citations using local LLM
    answer, citations = llm.generate_answer(query_text, retrieved_chunks)
    
    # 4. Cache the Response in Redis
    # Calculate the union of all allowed groups of the retrieved chunks
    # to ensure the cache is only returned to someone who has access to all these documents
    chunk_groups = set()
    for chunk in retrieved_chunks:
        chunk_groups.update(chunk["allowed_groups"])
    
    # Cache the response
    search.semantic_cache_set(query_text, answer, list(chunk_groups))
    
    # 5. Log the query and response in PostgreSQL AuditLog
    user_obj = db.query(User).filter(User.username == username).first()
    user_id = user_obj.id if user_obj else None
    
    retrieved_metadata = [
        {
            "chunk_id": chunk["id"],
            "filename": chunk["filename"],
            "source_type": chunk["source_type"],
            "allowed_groups": chunk["allowed_groups"]
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
    
    return QueryResponse(
        answer=answer,
        citations=citations,
        retrieved_chunks=retrieved_chunks,
        cached=False
    )

@app.get("/admin/logs", status_code=status.HTTP_200_OK)
def get_audit_logs(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    user_payload: Dict[str, Any] = Depends(get_current_user_payload),
    db: Session = Depends(get_db)
):
    # Check if user is in admin group
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
                "timestamp": log.timestamp.isoformat(),
                "retrieved_chunks": log.retrieved_chunks
            }
            for log in logs
        ]
    }
