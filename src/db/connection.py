import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from config import Config
from src.db.models import Base

logger = logging.getLogger(__name__)

# ==========================================
# Database Setup (Postgres with SQLite in-memory fallback)
# ==========================================
try:
    engine = create_engine(Config.DATABASE_URL)
except Exception as e:
    logger.warning(f"Could not initialize PostgreSQL engine with {Config.DATABASE_URL}: {e}. Using SQLite in-memory fallback.")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_postgres():
    Base.metadata.create_all(bind=engine)
    logger.info("PostgreSQL tables initialized.")

# ==========================================
# Qdrant Setup
# ==========================================
try:
    qdrant_client = QdrantClient(host=Config.QDRANT_HOST, port=Config.QDRANT_PORT)
except Exception as e:
    logger.warning(f"Could not connect to Qdrant at {Config.QDRANT_HOST}:{Config.QDRANT_PORT}: {e}")
    qdrant_client = None

COLLECTION_NAME = "ask_the_company"

def init_qdrant():
    if not qdrant_client:
        logger.info("Qdrant client not initialized; skipping collection creation.")
        return
    try:
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
            logger.info(f"Qdrant collection '{COLLECTION_NAME}' created with dense (1024) and sparse vector configs.")
        else:
            logger.info(f"Qdrant collection '{COLLECTION_NAME}' already exists.")
    except Exception as e:
        logger.warning(f"Could not initialize Qdrant collection: {e}")

def init_dbs():
    init_postgres()
    init_qdrant()
