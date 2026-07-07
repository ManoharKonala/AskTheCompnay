import os
import json
import re
import tempfile
from typing import List, Dict, Any
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from unstructured.partition.auto import partition
from unstructured.chunking.title import chunk_by_title
import logging

logger = logging.getLogger(__name__)

# Initialize Presidio engines lazily or globally
# For simplicity, we initialize them here globally, but in a production system
# they could be part of a singleton pattern or dependency injection.
try:
    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
except Exception as e:
    logger.error(f"Failed to initialize Presidio: {e}")
    analyzer = None
    anonymizer = None

class BaseParser:
    def redact_pii(self, text: str) -> str:
        if not text or not analyzer or not anonymizer:
            return text
        try:
            results = analyzer.analyze(
                text=text, 
                entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "CREDIT_CARD", "US_SSN"], 
                language='en'
            )
            anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
            return anonymized.text
        except Exception as e:
            logger.warning(f"PII Redaction failed: {e}")
            return text

    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

class ConfluenceParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        pattern = r"(?=(?:^|\n)#+\s+)"
        sections = re.split(pattern, content)
        
        chunks = []
        chunk_idx = 0
        doc_allowed_groups = ["Public"]
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
                
            acl_match = re.search(r">\s*\*\*Allowed Groups:\*\*\s*([^\n]+)", section, re.IGNORECASE)
            if acl_match:
                groups = [g.strip() for g in acl_match.group(1).split(",") if g.strip()]
                allowed_groups = groups
            else:
                allowed_groups = doc_allowed_groups
                
            # Redact PII
            redacted_section = self.redact_pii(section)
                
            chunks.append({
                "text_content": redacted_section,
                "chunk_index": chunk_idx,
                "allowed_groups": allowed_groups
            })
            chunk_idx += 1
            
        return chunks

class SlackParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        with open(filepath, "r", encoding="utf-8") as f:
            messages = json.load(f)
            
        if not isinstance(messages, list):
            return []
            
        messages.sort(key=lambda x: float(x.get("ts", 0)))
        
        threads = []
        current_thread = []
        last_ts = 0.0
        
        for msg in messages:
            user = msg.get("user", "Unknown")
            text = msg.get("text", "")
            ts_str = msg.get("ts", "0")
            ts = float(ts_str)
            
            if not current_thread:
                current_thread.append((user, text))
            else:
                if ts - last_ts < 600:
                    current_thread.append((user, text))
                else:
                    threads.append(current_thread)
                    current_thread = [(user, text)]
            last_ts = ts
            
        if current_thread:
            threads.append(current_thread)
            
        chunks = []
        for idx, thread in enumerate(threads):
            thread_text = []
            for user, text in thread:
                thread_text.append(f"User {user}: {text}")
            full_thread_content = "\n".join(thread_text)
            
            redacted_content = self.redact_pii(full_thread_content)
            
            chunks.append({
                "text_content": f"[Slack Conversation {idx}]\n" + redacted_content,
                "chunk_index": idx,
                "allowed_groups": ["Public"]
            })
            
        return chunks

class ExcelCSVParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        try:
            elements = partition(filename=filepath)
            chunks_elements = chunk_by_title(elements)
        except Exception as e:
            logger.error(f"Unstructured parsing failed for {filepath}: {e}")
            return []
            
        chunks = []
        filename_lower = os.path.basename(filepath).lower()
        allowed_groups = ["Public"]
        if "salary" in filename_lower or "payroll" in filename_lower or "financial" in filename_lower:
            allowed_groups = ["HR", "Management", "Finance"]
            
        for idx, chunk in enumerate(chunks_elements):
            text = str(chunk)
            redacted_text = self.redact_pii(text)
            chunks.append({
                "text_content": f"Table: {os.path.basename(filepath)} - Chunk {idx}\n\n{redacted_text}",
                "chunk_index": idx,
                "allowed_groups": allowed_groups
            })
            
        return chunks

class PDFParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        try:
            # Unstructured handles OCR automatically via Tesseract/Paddle if installed
            elements = partition(filename=filepath, strategy="hi_res")
            chunks_elements = chunk_by_title(elements)
        except Exception as e:
            logger.error(f"Unstructured parsing failed for {filepath}: {e}")
            return []
            
        chunks = []
        for idx, chunk in enumerate(chunks_elements):
            text = str(chunk)
            if not text.strip():
                continue
            redacted_text = self.redact_pii(text)
            chunks.append({
                "text_content": f"Document: {os.path.basename(filepath)} - Part {idx+1}\n\n{redacted_text}",
                "chunk_index": idx,
                "allowed_groups": ["Public"]
            })
            
        return chunks

