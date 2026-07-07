import pytest
from src.retrieval.llm import LLMService

def test_confidence_gate(mocker):
    service = LLMService()
    
    # Rerank score is too low (-3.5 < -3.0)
    retrieved_chunks = [{"text": "foo", "rerank_score": -3.5}]
    
    answer, citations = service.generate_answer("query", retrieved_chunks)
    
    assert "confident context" in answer
    assert citations == []

def test_citation_hallucination_stripping(mocker):
    # Mock Ollama call to prevent real network request
    mock_ollama = mocker.patch("src.retrieval.llm.LLMService.call_ollama")
    # Simulate LLM returning a valid and an invalid citation
    mock_ollama.return_value = "Here is the answer. [Source: valid.pdf] [Source: hallucinated.pdf]"
    
    service = LLMService()
    
    # Provide only valid.pdf in context
    retrieved_chunks = [{"text": "foo", "filename": "valid.pdf", "rerank_score": 1.0}]
    
    answer, citations = service.generate_answer("query", retrieved_chunks)
    
    # Assert hallucinated citation was removed from text
    assert "[Source: valid.pdf]" in answer
    assert "[Source: hallucinated.pdf]" not in answer
    
    # Assert only valid citation is returned
    assert citations == ["valid.pdf"]

def test_empty_context(mocker):
    service = LLMService()
    answer, citations = service.generate_answer("query", [])
    
    assert "could not find any relevant information" in answer
    assert citations == []
