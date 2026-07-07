import pytest
from src.retrieval.search import SearchService

def test_acl_filter_building(mocker):
    # Mock the heavy pipeline and reranker inside SearchService
    mock_pipeline = mocker.MagicMock()
    mock_pipeline.model.encode.return_value = {
        'dense_vecs': [[0.1, 0.2]],
        'lexical_weights': [{"foo": 0.5}]
    }
    
    # We mock SearchService's initialization of BGE-Reranker and Redis
    mocker.patch("src.retrieval.search.FlagReranker")
    mocker.patch("redis.Redis.from_url")
    mocker.patch("redisvl.index.SearchIndex")
    
    mock_qdrant = mocker.patch("src.retrieval.search.qdrant_client.query_points")
    mock_qdrant.return_value.points = []
    
    # We mock the HyDE LLM call
    mock_llm = mocker.patch("src.retrieval.llm.LLMService")
    mock_llm.return_value.generate_hyde.return_value = "hyde answer"
    
    service = SearchService(pipeline=mock_pipeline)
    
    # Run search for a user with HR group
    service.search("test query", ["HR"])
    
    # Check that qdrant_client.query_points was called
    assert mock_qdrant.called
    
    # Inspect the acl_filter that was passed to query_points
    call_kwargs = mock_qdrant.call_args.kwargs
    query_filter = call_kwargs.get("query_filter")
    
    assert query_filter is not None
    # The filter should be a rest.Filter with a must condition for "allowed_groups"
    condition = query_filter.must[0]
    assert condition.key == "allowed_groups"
    
    # The any values should contain "Public" and "HR"
    assert "Public" in condition.match.any
    assert "HR" in condition.match.any
    assert "Management" not in condition.match.any

def test_semantic_cache_logic(mocker):
    mocker.patch("src.retrieval.search.FlagReranker")
    mocker.patch("redis.Redis.from_url")
    
    mock_pipeline = mocker.MagicMock()
    mock_pipeline.model.encode.return_value = {
        'dense_vecs': [[0.1, 0.2]],
        'lexical_weights': [{"foo": 0.5}]
    }
    
    service = SearchService(pipeline=mock_pipeline)
    service.redisvl_index = mocker.MagicMock()
    service.VectorQuery = mocker.MagicMock()
    
    # Mock cache hit with sufficient similarity
    service.redisvl_index.query.return_value = [{
        "response_text": "cached response",
        "allowed_groups": "HR,Public",
        "vector_distance": 0.1 # Below the 0.15 threshold
    }]
    
    # If user has HR, it should hit
    res = service.semantic_cache_lookup("query", ["HR"])
    assert res == "cached response"
    
    # If user has only Engineering, it should hit because 'Public' is allowed
    res_eng = service.semantic_cache_lookup("query", ["Engineering"])
    assert res_eng == "cached response"
    
    # Now simulate a cache entry restricted only to 'Management'
    service.redisvl_index.query.return_value = [{
        "response_text": "secret cached response",
        "allowed_groups": "Management",
        "vector_distance": 0.1
    }]
    
    # HR user cannot see Management cache
    assert service.semantic_cache_lookup("query", ["HR"]) is None
    
    # Management user can see it
    assert service.semantic_cache_lookup("query", ["Management"]) == "secret cached response"
