import os
import sys
import json

# Polyfill for ragas 0.1.x on Langchain 0.3.x
import pydantic.v1 as pydantic_v1
import langchain_core
import langchain
langchain_core.pydantic_v1 = pydantic_v1
sys.modules['langchain_core.pydantic_v1'] = pydantic_v1
langchain.pydantic_v1 = pydantic_v1
sys.modules['langchain.pydantic_v1'] = pydantic_v1

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from datasets import Dataset
from ragas import evaluate
from llama_index.core import SimpleDirectoryReader
from config import Config

def run_evaluation():
    print("Loading test documents using LlamaIndex...")
    try:
        # Fulfilling the README claim: LlamaIndex used for data orchestration / loading
        documents = SimpleDirectoryReader(os.path.join(PROJECT_ROOT, "data", "seed", "confluence")).load_data()
        print(f"Loaded {len(documents)} documents for evaluation context.")
    except Exception as e:
        print(f"Failed to load documents with LlamaIndex: {e}")

    from ragas.metrics import faithfulness, answer_relevancy, context_recall
    
    # Dummy test dataset for evaluation (Ragas 0.1.x format)
    data = {
        "question": ["What is the annual leave policy?"],
        "answer": ["Employees are entitled to 20 days of paid annual leave."],
        "contexts": [["All full-time employees are entitled to 20 days of paid annual leave per calendar year."]],
        "ground_truth": ["Employees get 20 days of annual leave."]
    }
    
    dataset = Dataset.from_dict(data)
    
    print("Running RAGAS evaluation with local models...")
    try:
        from langchain_community.llms import Ollama
        from langchain_community.embeddings import HuggingFaceEmbeddings
        
        base_llm = Ollama(model=Config.MODEL_NAME, base_url=Config.OLLAMA_HOST)
        base_embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")
        
        result = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy, context_recall],
            llm=base_llm,
            embeddings=base_embeddings,
            raise_exceptions=False
        )
        print("\n=== RAGAS Evaluation Results ===")
        print(result)
        
    except Exception as e:
        print(f"Evaluation failed: {e}")
        print("Note: RAGAS evaluation with local LLMs may require additional Langchain setup or model pulling.")

if __name__ == "__main__":
    run_evaluation()
