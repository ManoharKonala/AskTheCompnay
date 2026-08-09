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

@celery_app.task(
    name="ingest_file_task",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def ingest_file_task(self, filepath: str, source_type: str):
    global _pipeline
    logger.info(f"Starting async ingestion for {filepath} (attempt {self.request.retries + 1}/{self.max_retries + 1})")
    from src.db.connection import SessionLocal
    from src.db.models import FailedIngestion
    
    # Lazy-init fallback if signal didn't fire (e.g., eager mode in tests)
    if _pipeline is None:
        from src.ingestion.pipeline import IngestionPipeline
        _pipeline = IngestionPipeline()
    
    db = SessionLocal()
    try:
        _pipeline.ingest_file(db, filepath, source_type)
        return {"status": "success", "filepath": filepath, "retries": self.request.retries}
    except Exception as exc:
        logger.error(f"Error during ingestion of {filepath} (retry {self.request.retries}/{self.max_retries}): {exc}")
        if self.request.retries >= self.max_retries:
            # Final retry failed: write to Dead Letter Queue (FailedIngestion table)
            try:
                failed_record = FailedIngestion(
                    filepath=filepath,
                    source_type=source_type,
                    error_message=str(exc),
                    retry_count=self.request.retries,
                    status="FAILED"
                )
                db.add(failed_record)
                db.commit()
                logger.critical(f"DLQ: Recorded permanent ingestion failure for {filepath} into database.")
            except Exception as db_err:
                logger.error(f"Failed to record DLQ failure in DB: {db_err}")
        raise exc
    finally:
        db.close()

