import os
from celery import Celery
from celery.signals import worker_init
from config import Config
import logging

logger = logging.getLogger(__name__)

# Initialize Celery
# Note: we use redis for both broker and backend
celery_app = Celery(
    "askthecompany_tasks",
    broker=Config.REDIS_URL,
    backend=Config.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Worker-level singleton: the heavy BGE-M3 model is loaded ONCE per worker
# process at boot time, not per task.
_pipeline = None

@worker_init.connect
def init_worker_pipeline(**kwargs):
    global _pipeline
    from src.ingestion.pipeline import IngestionPipeline
    logger.info("Loading IngestionPipeline (BGE-M3) for Celery worker...")
    _pipeline = IngestionPipeline()
    logger.info("IngestionPipeline ready.")

@celery_app.task(name="ingest_file_task")
def ingest_file_task(filepath: str, source_type: str):
    global _pipeline
    logger.info(f"Starting async ingestion for {filepath}")
    from src.db.connection import SessionLocal
    
    # Lazy-init fallback if signal didn't fire (e.g., eager mode in tests)
    if _pipeline is None:
        from src.ingestion.pipeline import IngestionPipeline
        _pipeline = IngestionPipeline()
    
    db = SessionLocal()
    try:
        _pipeline.ingest_file(db, filepath, source_type)
        return {"status": "success", "filepath": filepath}
    except Exception as e:
        logger.error(f"Failed async ingestion: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()

