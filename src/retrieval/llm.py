import requests
import re
import logging
from typing import List, Dict, Any, Tuple
from config import Config

from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self.ollama_url = f"{Config.OLLAMA_HOST}/api/generate"
        try:
            self.langfuse = Langfuse()
        except Exception as e:
            logger.error(f"Failed to init Langfuse: {e}")

    @observe(as_type="generation")
    def call_ollama(self, prompt: str, system_prompt: str) -> str:
        payload = {
            "model": Config.MODEL_NAME,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.0  # Set temperature to 0 for factual consistency
            }
        }
        langfuse_context.update_current_observation(
            model=Config.MODEL_NAME,
            input=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        )
        try:
            response = requests.post(self.ollama_url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json().get("response", "").strip()
            langfuse_context.update_current_observation(output=result)
            return result
        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")
            return f"Error: Unable to reach the LLM service at {Config.OLLAMA_HOST}. Make sure Ollama is running and the model {Config.MODEL_NAME} is pulled."

    @observe(as_type="generation")
    def generate_hyde(self, query_text: str) -> str:
        system_prompt = "You are an expert. Write a brief, hypothetical answer to the user's question. Focus on the expected vocabulary and structure."
        return self.call_ollama(query_text, system_prompt)

    @observe(as_type="generation")
    def generate_answer(self, query_text: str, retrieved_chunks: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
        """
        Formats the prompt, calls the LLM, and validates citations.
        Returns a tuple of (validated_answer, list_of_valid_cited_files).
        """
        if not retrieved_chunks:
            return "I could not find any relevant information in the company documents that you are authorized to see.", []
            
        # Confidence Gate: If the top retrieved chunk has a very low reranker score, refuse to answer
        if retrieved_chunks[0].get("rerank_score", 0.0) < -3.0:
            return "I don't have enough confident context to answer this question accurately.", []

        # 1. Build the context string
        context_items = []
        valid_filenames = set()
        for idx, chunk in enumerate(retrieved_chunks):
            filename = chunk["filename"]
            valid_filenames.add(filename)
            context_items.append(
                f"--- Document {idx + 1} ---\n"
                f"Source File: {filename}\n"
                f"Content:\n{chunk['text']}\n"
            )
        context_str = "\n".join(context_items)

        # 2. Define prompts
        system_prompt = (
            "You are 'AskTheCompany', a secure enterprise assistant. Your job is to answer the user's question "
            "using ONLY the provided document chunks.\n\n"
            "CRITICAL RULES:\n"
            "1. For EVERY claim or fact you present, you MUST cite the source document using the exact format: [Source: filename].\n"
            "2. Do NOT make up any citations. Only cite the files listed in the context.\n"
            "3. If the context does not contain the answer, state: 'I could not find the answer in the available company documents.'\n"
            "4. Keep your answer professional, concise, and factual."
        )

        prompt = (
            f"Context Chunks:\n{context_str}\n\n"
            f"Question: {query_text}\n\n"
            f"Answer:"
        )

        # 3. Get answer from LLM
        raw_answer = self.call_ollama(prompt, system_prompt)

        # 4. Citation Validation Guardrail
        # Find all citations matching [Source: filename]
        citations = re.findall(r"\[Source:\s*([^\]]+)\]", raw_answer)
        
        valid_citations = []
        invalid_citations = []
        
        for citation in citations:
            citation_clean = citation.strip()
            if citation_clean in valid_filenames:
                valid_citations.append(citation_clean)
            else:
                invalid_citations.append(citation_clean)

        # If there are invalid (hallucinated) citations, remove them or correct them
        validated_answer = raw_answer
        for invalid in invalid_citations:
            # Remove the invalid citation from the text
            validated_answer = re.sub(rf"\[Source:\s*{re.escape(invalid)}\]", "", validated_answer)
            
        if invalid_citations:
            logger.warning(f"Warning: Removed hallucinated citations: {invalid_citations}")

        # Clean up any double spaces resulting from removals
        validated_answer = re.sub(r'\s+', ' ', validated_answer).strip()

        return validated_answer, list(set(valid_citations))
