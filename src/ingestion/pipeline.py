import os
import sys
import hashlib
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from config import Config
from FlagEmbedding import BGEM3FlagModel
from qdrant_client.http import models as rest

from src.db.connection import SessionLocal, qdrant_client, COLLECTION_NAME, init_dbs
from src.db.models import Document, DocumentChunk
from src.ingestion.parsers import ConfluenceParser, SlackParser, ExcelCSVParser, PDFParser

import logging
from datasketch import MinHash, MinHashLSH
import redis

logger = logging.getLogger(__name__)

# Initialize Redis client for LSH storage
try:
    redis_client = redis.from_url(Config.REDIS_URL)
    # Configure LSH to use redis
    lsh = MinHashLSH(
        threshold=0.9, 
        num_perm=128, 
        storage_config={
            'type': 'redis', 
            'redis': {'host': Config.REDIS_URL.split("://")[1].split(":")[0], 'port': 6379}
        }
    )
except Exception as e:
    logger.error(f"Failed to initialize MinHashLSH with Redis: {e}")
    lsh = None


class IngestionPipeline:
    def __init__(self):
        logger.info("Initializing BGE-M3 model...")
        # Load the BGE-M3 model on CPU by default (since we're on a CPU/Windows environment)
        # use_fp16=False is safer for CPU inference
        self.model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)
        
        self.parsers = {
            "confluence": ConfluenceParser(),
            "slack": SlackParser(),
            "excel": ExcelCSVParser(),
            "pdf": PDFParser()
        }

    def hash_token(self, token: str) -> int:
        """Hash a token string to a deterministic 32-bit signed integer for Qdrant sparse vector index.
        Uses SHA-256 instead of Python's built-in hash() which is randomized per process."""
        return int(hashlib.sha256(token.encode('utf-8')).hexdigest(), 16) % 2147483647

    def get_sparse_vector(self, lexical_weights: dict) -> rest.SparseVector:
        """Convert lexical weights from BGE-M3 into a Qdrant SparseVector."""
        indices = []
        values = []
        for token, weight in lexical_weights.items():
            idx = self.hash_token(str(token))
            indices.append(idx)
            values.append(float(weight))
            
        # Qdrant requires sparse vector indices to be unique and sorted
        if indices:
            sorted_pairs = sorted(zip(indices, values))
            indices, values = zip(*sorted_pairs)
            return rest.SparseVector(indices=list(indices), values=list(values))
        return rest.SparseVector(indices=[], values=[])

    def ingest_file(self, db: Session, filepath: str, source_type: str):
        filename = os.path.basename(filepath)
        logger.info(f"Parsing {filename} ({source_type})...")
        
        parser = self.parsers.get(source_type)
        if not parser:
            logger.error(f"No parser found for source type: {source_type}")
            return
            
        chunks_data = parser.parse(filepath)
        if not chunks_data:
            logger.warning(f"No text extracted from {filename}")
            return
            
        # MinHash Deduplication
        unique_chunks_data = []
        for chunk in chunks_data:
            text = chunk["text_content"]
            m = MinHash(num_perm=128)
            for word in text.split():
                m.update(word.encode('utf8'))
            
            # Check if duplicate exists
            is_duplicate = False
            if lsh:
                result = lsh.query(m)
                if len(result) > 0:
                    is_duplicate = True
                    logger.info(f"Duplicate chunk found and skipped: {result[0]}")
            
            if not is_duplicate:
                unique_chunks_data.append(chunk)
                if lsh:
                    # Insert into LSH using a unique key
                    lsh_key = f"{filename}_{chunk['chunk_index']}"
                    lsh.insert(lsh_key, m)
                    
        chunks_data = unique_chunks_data
        
        if not chunks_data:
            logger.warning(f"No unique chunks found in {filename} after deduplication.")
            return
            
        logger.info(f"Extracted {len(chunks_data)} chunks. Generating embeddings...")
        
        # Extract text contents for embedding generation
        texts = [c["text_content"] for c in chunks_data]
        
        # Compute embeddings in a single pass
        embeddings_output = self.model.encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
            batch_size=1,
            max_length=512
        )
        
        dense_vecs = embeddings_output['dense_vecs']
        sparse_vecs = embeddings_output['lexical_weights']
        
        # 1. Save Document metadata in PostgreSQL
        # If document already exists, delete it and its chunks to avoid duplicates (re-ingestion)
        existing_doc = db.query(Document).filter(Document.filepath == filepath).first()
        if existing_doc:
            db.delete(existing_doc)
            db.commit()
            
        doc = Document(
            filename=filename,
            source_type=source_type,
            filepath=filepath
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # 2. Save Chunks in PostgreSQL & Qdrant
        points = []
        for idx, chunk_data in enumerate(chunks_data):
            # Save chunk to Postgres to get a unique ID
            db_chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk_data["chunk_index"],
                text_content=chunk_data["text_content"],
                allowed_groups=chunk_data["allowed_groups"]
            )
            db.add(db_chunk)
            db.commit()
            db.refresh(db_chunk)
            
            # Prepare Qdrant sparse vector
            qdrant_sparse = self.get_sparse_vector(sparse_vecs[idx])
            
            # Prepare Qdrant point
            point = rest.PointStruct(
                id=db_chunk.id,
                vector={
                    "": dense_vecs[idx].tolist(),  # Default dense vector
                    "text-sparse": qdrant_sparse  # Sparse vector
                },
                payload={
                    "chunk_id": db_chunk.id,
                    "document_id": doc.id,
                    "filename": filename,
                    "source_type": source_type,
                    "text": chunk_data["text_content"],
                    "allowed_groups": chunk_data["allowed_groups"]
                }
            )
            points.append(point)
            
        # Upsert points into Qdrant
        if points:
            qdrant_client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            logger.info(f"Successfully ingested {len(points)} chunks into Postgres and Qdrant.")

    def run_ingestion(self, data_dir: str):
        db = SessionLocal()
        try:
            init_dbs()
            
            # Subdirectories map to source types
            source_mapping = {
                "confluence": "confluence",
                "slack": "slack",
                "excel": "excel",
                "pdfs": "pdf"
            }
            
            for folder_name, source_type in source_mapping.items():
                folder_path = os.path.join(data_dir, folder_name)
                if not os.path.exists(folder_path):
                    continue
                    
                for root, _, files in os.walk(folder_path):
                    for file in files:
                        filepath = os.path.join(root, file)
                        # Skip temporary files
                        if file.startswith("~$") or file.startswith("temp_"):
                            continue
                        self.ingest_file(db, filepath, source_type)
        finally:
            db.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # If run directly, ingest the seed data
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    SEED_DATA_DIR = os.path.join(PROJECT_ROOT, 'data', 'seed')
    pipeline = IngestionPipeline()
    pipeline.run_ingestion(SEED_DATA_DIR)
