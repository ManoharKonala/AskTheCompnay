import os
import json
import logging
from typing import List, Dict, Any, Optional

from FlagEmbedding import FlagReranker
from qdrant_client.http import models as rest
import redis

from config import Config
from src.db.connection import qdrant_client, COLLECTION_NAME
from src.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

class SearchService:
    def __init__(self, pipeline: Optional[IngestionPipeline] = None, llm_service=None):
        if pipeline:
            self.pipeline = pipeline
        else:
            self.pipeline = IngestionPipeline()
        
        # Accept injected LLMService to avoid creating a new one per search() call
        self._llm_service = llm_service
            
        logger.info("Initializing BGE-Reranker model...")
        self.reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=False)
        
        self.redis_connected = False
        self.redisvl_index = None
        self.redis_client = None
        
        try:
            self.redis_client = redis.Redis.from_url(Config.REDIS_URL, decode_responses=False)
            self.redis_connected = True
            logger.info("Connected to Redis for semantic caching.")
            
            from redisvl.index import SearchIndex
            from redisvl.schema import IndexSchema
            from redisvl.query import VectorQuery
            
            schema = IndexSchema.from_dict({
                "index": {
                    "name": "semantic_cache",
                    "prefix": "cache",
                    "storage_type": "hash"
                },
                "fields": [
                    {"name": "query_text", "type": "text"},
                    {"name": "response_text", "type": "text"},
                    {"name": "allowed_groups", "type": "tag"},
                    {
                        "name": "query_vector", 
                        "type": "vector", 
                        "attrs": {
                            "dims": 1024,
                            "distance_metric": "cosine",
                            "algorithm": "flat",
                            "datatype": "float32"
                        }
                    }
                ]
            })
            
            self.redisvl_index = SearchIndex(schema, self.redis_client)
            self.redisvl_index.create(overwrite=False)
            self.VectorQuery = VectorQuery
        except Exception as e:
            logger.error(f"Failed to connect to Redis/RedisVL: {e}")

    def semantic_cache_lookup(self, query_text: str, user_groups: List[str]) -> str:
        if not self.redisvl_index:
            return None
        try:
            # 1. Embed query for similarity search
            embeddings = self.pipeline.model.encode(
                [query_text],
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False
            )
            dense_vector = embeddings['dense_vecs'][0].tolist()

            # 2. RedisVL Vector Query
            query = self.VectorQuery(
                vector=dense_vector,
                vector_field_name="query_vector",
                return_fields=["response_text", "allowed_groups", "vector_distance"],
                num_results=1,
                dialect=2
            )
            
            results = self.redisvl_index.query(query)
            if results:
                top_result = results[0]
                distance = float(top_result.get("vector_distance", 1.0))
                # Threshold for semantic equivalence (cosine distance)
                if distance < 0.15: 
                    allowed_groups_str = top_result.get("allowed_groups", "")
                    required_groups = allowed_groups_str.split(",") if allowed_groups_str else []
                    
                    if not required_groups or any(g in user_groups for g in required_groups) or "Public" in required_groups:
                        logger.info(f"Semantic cache hit! (distance: {distance})")
                        return top_result.get("response_text")
        except Exception as e:
            logger.error(f"Semantic Cache lookup failed: {e}")
        return None

    def semantic_cache_set(self, query_text: str, response_text: str, allowed_groups: List[str]):
        if not self.redisvl_index or not self.redis_client:
            return
        try:
            import uuid
            import numpy as np
            
            embeddings = self.pipeline.model.encode(
                [query_text],
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False
            )
            dense_vector = embeddings['dense_vecs'][0].tolist()
            
            record = {
                "query_text": query_text,
                "response_text": response_text,
                "allowed_groups": ",".join(allowed_groups)
            }
            # RedisVL requires vector field to be raw bytes if not using loaded pandas df
            # but load() handles it.
            # Convert vector to numpy float32 bytes for Redis hash storage
            record["query_vector"] = np.array(dense_vector, dtype=np.float32).tobytes()
            
            key = f"cache:{uuid.uuid4()}"
            self.redis_client.hset(key, mapping=record)
            # Expire after 1 hour
            self.redis_client.expire(key, 3600)
            logger.info("Response semantically cached in Redis.")
        except Exception as e:
            logger.error(f"Failed to write to cache: {e}")

    def search(self, query_text: str, user_groups: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        # HyDE: Generate hypothetical answer
        # Use injected LLMService; lazy-init as fallback
        if self._llm_service is None:
            from src.retrieval.llm import LLMService
            self._llm_service = LLMService()
        hyde_answer = self._llm_service.generate_hyde(query_text)
        
        # Combine query + hyde_answer for embedding
        combined_text = f"{query_text}\n{hyde_answer}"
        
        # 1. Generate dense and sparse embeddings for the COMBINED text
        embeddings = self.pipeline.model.encode(
            [combined_text],
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False
        )
        
        dense_vector = embeddings['dense_vecs'][0].tolist()
        sparse_weights = embeddings['lexical_weights'][0]
        qdrant_sparse = self.pipeline.get_sparse_vector(sparse_weights)
        
        # Convert to NamedSparseVector for Qdrant
        named_sparse = rest.NamedSparseVector(
            name="text-sparse",
            vector=rest.SparseVector(
                indices=qdrant_sparse.indices,
                values=qdrant_sparse.values
            )
        )
        
        # 2. Build the ACL Filter
        # A chunk is accessible if its allowed_groups list overlaps with the user's groups
        # or contains "Public"
        allowed_list = ["Public"] + user_groups
        acl_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="allowed_groups",
                    match=rest.MatchAny(any=allowed_list)
                )
            ]
        )
        
        # 3. Perform Hybrid Search in Qdrant (Dense + Sparse with RRF)
        # We retrieve twice the limit to allow the reranker to work on a larger pool
        prefetch_limit = max(20, limit * 2)
        
        try:
            response = qdrant_client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    rest.Prefetch(
                        query=dense_vector,
                        limit=prefetch_limit
                    ),
                    rest.Prefetch(
                        query=named_sparse,
                        using="text-sparse",
                        limit=prefetch_limit
                    )
                ],
                query=rest.FusionQuery(fusion=rest.Fusion.RRF),
                query_filter=acl_filter,
                limit=prefetch_limit
            )
            
            retrieved_chunks = []
            for point in response.points:
                retrieved_chunks.append({
                    "id": point.id,
                    "text": point.payload["text"],
                    "filename": point.payload["filename"],
                    "source_type": point.payload["source_type"],
                    "allowed_groups": point.payload["allowed_groups"]
                })
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []
            
        if not retrieved_chunks:
            return []
            
        # 4. Re-rank the retrieved chunks using BGE-Reranker
        pairs = [[query_text, chunk["text"]] for chunk in retrieved_chunks]
        rerank_scores = self.reranker.compute_score(pairs)
        
        # If compute_score returns a single float instead of a list (for single pair), wrap it
        if isinstance(rerank_scores, float):
            rerank_scores = [rerank_scores]
            
        # Add rerank scores to chunks and sort
        for idx, score in enumerate(rerank_scores):
            retrieved_chunks[idx]["rerank_score"] = float(score)
            
        # Sort chunks by rerank score descending
        retrieved_chunks.sort(key=lambda x: x["rerank_score"], reverse=True)
        
        # Return the top-K chunks
        return retrieved_chunks[:limit]
