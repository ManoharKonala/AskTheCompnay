from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from config import Config
from src.db.models import Base

# ==========================================
# PostgreSQL Setup
# ==========================================
engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_postgres():
    Base.metadata.create_all(bind=engine)
    print("PostgreSQL tables initialized.")

# ==========================================
# Qdrant Setup
# ==========================================
qdrant_client = QdrantClient(host=Config.QDRANT_HOST, port=Config.QDRANT_PORT)

COLLECTION_NAME = "ask_the_company"

def init_qdrant():
    collections = qdrant_client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    
    if not exists:
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=rest.VectorParams(
                size=1024,  # BGE-M3 dense vector size
                distance=rest.Distance.COSINE
            ),
            sparse_vectors_config={
                "text-sparse": rest.SparseVectorParams(
                    index=rest.SparseIndexParams(
                        on_disk=True
                    )
                )
            }
        )
        print(f"Qdrant collection '{COLLECTION_NAME}' created with dense (1024) and sparse vector configs.")
    else:
        print(f"Qdrant collection '{COLLECTION_NAME}' already exists.")

def init_dbs():
    init_postgres()
    init_qdrant()
