from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from config import Config
from src.db.connection import get_db, init_dbs
from src.db.models import User, AuditLog
from src.auth.jwt import get_password_hash, verify_password, create_access_token, decode_access_token
from src.ingestion.pipeline import IngestionPipeline
from src.retrieval.search import SearchService
from src.retrieval.llm import LLMService

app = FastAPI(title="AskTheCompany API", version="1.0")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Initialize services lazily
pipeline_service = None
search_service = None
llm_service = None

def get_pipeline():
    global pipeline_service
    if pipeline_service is None:
        pipeline_service = IngestionPipeline()
    return pipeline_service

def get_search_service():
    global search_service
    if search_service is None:
        search_service = SearchService()
    return search_service

def get_llm_service():
    global llm_service
    if llm_service is None:
        llm_service = LLMService()
    return llm_service

# ==========================================
# Pydantic Schemas
# ==========================================
class UserRegister(BaseModel):
    username: str
    password: str
    groups: List[str]

class QueryRequest(BaseModel):
    query: str

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
@app.on_event("startup")
def on_startup():
    init_dbs()

@app.post("/auth/register", status_code=status.HTTP_211_ALREADY_REPORTED or status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
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
        groups=user_data.groups
    )
    db.add(user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
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

@app.post("/ingest", status_code=status.HTTP_200_OK)
def trigger_ingestion(pipeline: IngestionPipeline = Depends(get_pipeline)):
    try:
        pipeline.run_ingestion(r"c:\Users\konal\RAG-Futurense\data\seed")
        return {"status": "success", "message": "Seed data ingestion completed successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}"
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
