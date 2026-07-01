import os
from typing import List, Dict, Any
from FlagEmbedding import FlagReranker, BGEM3FlagModel
from qdrant_client.http import models as rest
import redis
import json

from config import Config
from src.db.connection import qdrant_client, COLLECTION_NAME
from src.ingestion.pipeline import IngestionPipeline

# Initialize the reranker on CPU
print("Initializing BGE-Reranker model...")
reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=False)

# Connect to Redis for caching
try:
    redis_client = redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)
    redis_connected = True
    print("Connected to Redis for semantic caching.")
except Exception as e:
    redis_connected = False
    print(f"Failed to connect to Redis: {e}")

class SearchService:
    def __init__(self):
        # Share the same BGE-M3 model from the ingestion pipeline
        self.pipeline = IngestionPipeline()

    def semantic_cache_lookup(self, query_text: str, user_groups: List[str]) -> str:
        """
        Looks up the query in the Redis cache.
        For simplicity and robustness, we check if there's a cached response.
        To make it semantic, we can check for exact or close matches, or use RedisVL.
        Note: We must ensure that the cached response is only returned if the user 
        has the appropriate permissions for the sources cited in that response.
        """
        if not redis_connected:
            return None
            
        try:
            # We store cache keys by query
            cache_data_str = redis_client.get(f"cache:{query_text}")
            if cache_data_str:
                cache_data = json.loads(cache_data_str)
                # Check if the user's groups allow access to the cached response's sources
                required_groups = cache_data.get("allowed_groups", [])
                
                # If the cache is public, or the user shares at least one required group
                if not required_groups or any(g in user_groups for g in required_groups) or "Public" in required_groups:
                    print("Semantic cache hit!")
                    return cache_data.get("response")
        except Exception as e:
            print(f"Cache lookup failed: {e}")
        return None

    def semantic_cache_set(self, query_text: str, response_text: str, allowed_groups: List[str]):
        if not redis_connected:
            return
        try:
            cache_data = {
                "response": response_text,
                "allowed_groups": allowed_groups
            }
            # Cache for 1 hour (3600 seconds)
            redis_client.setex(f"cache:{query_text}", 3600, json.dumps(cache_data))
            print("Response cached in Redis.")
        except Exception as e:
            print(f"Failed to write to cache: {e}")

    def search(self, query_text: str, user_groups: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        # 1. Generate dense and sparse embeddings for the query
        embeddings = self.pipeline.model.encode(
            [query_text],
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False
        )
        
        dense_vector = embeddings['dense_vector'][0].tolist()
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
            print(f"Qdrant search failed: {e}")
            return []
            
        if not retrieved_chunks:
            return []
            
        # 4. Re-rank the retrieved chunks using BGE-Reranker
        pairs = [[query_text, chunk["text"]] for chunk in retrieved_chunks]
        rerank_scores = reranker.compute_score(pairs)
        
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
