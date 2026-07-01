import os
import sys
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from config import Config
from FlagEmbedding import BGEM3FlagModel
from qdrant_client.http import models as rest

from src.db.connection import SessionLocal, qdrant_client, COLLECTION_NAME, init_dbs
from src.db.models import Document, DocumentChunk
from src.ingestion.parsers import ConfluenceParser, SlackParser, ExcelCSVParser, PDFParser

class IngestionPipeline:
    def __init__(self):
        print("Initializing BGE-M3 model...")
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
        """Hash a token string to a 32-bit signed integer for Qdrant sparse vector index."""
        return abs(hash(token)) % 2147483647

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
        print(f"Parsing {filename} ({source_type})...")
        
        parser = self.parsers.get(source_type)
        if not parser:
            print(f"No parser found for source type: {source_type}")
            return
            
        chunks_data = parser.parse(filepath)
        if not chunks_data:
            print(f"No text extracted from {filename}")
            return
            
        print(f"Extracted {len(chunks_data)} chunks. Generating embeddings...")
        
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
            print(f"Successfully ingested {len(points)} chunks into Postgres and Qdrant.")

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
    # If run directly, ingest the seed data
    pipeline = IngestionPipeline()
    pipeline.run_ingestion(r"c:\Users\konal\RAG-Futurense\data\seed")
