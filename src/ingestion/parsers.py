import os
import json
import re
import pandas as pd
from pypdf import PdfReader
from typing import List, Dict, Any

class BaseParser:
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        """
        Parses a file and returns a list of chunks.
        Each chunk is a dict: {
            "text_content": str,
            "chunk_index": int,
            "allowed_groups": List[str]
        }
        """
        raise NotImplementedError

class ConfluenceParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Split by headers (e.g., #, ##, ###)
        # We want to keep the headers as part of the text
        pattern = r"(?=(?:^|\n)#+\s+)"
        sections = re.split(pattern, content)
        
        chunks = []
        chunk_idx = 0
        
        # Default document-level ACL
        doc_allowed_groups = ["Public"]
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
                
            # Parse ACLs in this section
            # Look for: > **Allowed Groups:** Group1, Group2
            acl_match = re.search(r">\s*\*\*Allowed Groups:\*\*\s*([^\n]+)", section, re.IGNORECASE)
            if acl_match:
                groups = [g.strip() for g in acl_match.group(1).split(",") if g.strip()]
                allowed_groups = groups
            else:
                allowed_groups = doc_allowed_groups
                
            chunks.append({
                "text_content": section,
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
            
        # Sort messages by timestamp
        messages.sort(key=lambda x: float(x.get("ts", 0)))
        
        # Group messages into conversation threads
        # We group messages if:
        # 1. They have the same thread_ts
        # 2. Or they are sequential and within 10 minutes (600 seconds) of the previous message
        threads = []
        current_thread = []
        last_ts = 0.0
        
        for msg in messages:
            user = msg.get("user", "Unknown")
            text = msg.get("text", "")
            ts_str = msg.get("ts", "0")
            ts = float(ts_str)
            
            # Check if we should start a new thread
            if not current_thread:
                current_thread.append((user, text))
            else:
                # If within 10 minutes, group them
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
            
            chunks.append({
                "text_content": f"[Slack Conversation {idx}]\n" + full_thread_content,
                "chunk_index": idx,
                "allowed_groups": ["Public"]
            })
            
        return chunks

class ExcelCSVParser(BaseParser):
    def __init__(self, rows_per_chunk: int = 20):
        self.rows_per_chunk = rows_per_chunk

    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        if filepath.endswith(".csv"):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)
            
        chunks = []
        chunk_idx = 0
        
        # We chunk the table by rows, preserving the header
        total_rows = len(df)
        if total_rows == 0:
            return []
            
        # Check if there is any column or filename pattern indicating ACLs
        # For example, if filename contains 'salary' or 'finance', default to Finance/HR
        filename_lower = os.path.basename(filepath).lower()
        allowed_groups = ["Public"]
        if "salary" in filename_lower or "payroll" in filename_lower or "financial" in filename_lower:
            allowed_groups = ["HR", "Management", "Finance"]
            
        for i in range(0, total_rows, self.rows_per_chunk):
            df_slice = df.iloc[i : i + self.rows_per_chunk]
            markdown_table = df_slice.to_markdown(index=False)
            
            chunk_text = f"Table: {os.path.basename(filepath)} (Rows {i+1} to {min(i+self.rows_per_chunk, total_rows)})\n\n{markdown_table}"
            
            chunks.append({
                "text_content": chunk_text,
                "chunk_index": chunk_idx,
                "allowed_groups": allowed_groups
            })
            chunk_idx += 1
            
        return chunks

class PDFParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        reader = PdfReader(filepath)
        chunks = []
        chunk_idx = 0
        
        # Check for scanned PDF vs text PDF
        # We will extract text page by page
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            
            # If text is empty or extremely short, try OCR
            if not text or len(text.strip()) < 50:
                text = self._ocr_page(filepath, page_num)
                
            if not text or not text.strip():
                continue
                
            # Clean up text a bit
            text = re.sub(r'\s+', ' ', text).strip()
            
            chunks.append({
                "text_content": f"Document: {os.path.basename(filepath)}, Page {page_num + 1}\n\n{text}",
                "chunk_index": chunk_idx,
                "allowed_groups": ["Public"]  # Default
            })
            chunk_idx += 1
            
        return chunks

    def _ocr_page(self, filepath: str, page_num: int) -> str:
        # Fallback OCR using PaddleOCR if available
        try:
            from paddleocr import PaddleOCR
            # Initialize PaddleOCR (runs on CPU by default or GPU if available)
            ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
            
            # We need to convert PDF page to image to run OCR
            # Since pdf2image requires poppler (which might not be installed on Windows),
            # we can try using fitz (PyMuPDF) or pdfplumber if available,
            # or just write a stub/placeholder or try to use pypdfium2 which is installed!
            # pypdfium2 is in our virtual environment! Let's use pypdfium2 to render the page to an image.
            import pypdfium2 as pdfium
            
            doc = pdfium.PdfDocument(filepath)
            page = doc[page_num]
            bitmap = page.render(scale=2)  # render at 144 DPI
            pil_img = bitmap.to_pil()
            
            # Save temporary image
            temp_img_path = f"temp_page_{page_num}.png"
            pil_img.save(temp_img_path)
            
            # Run OCR
            result = ocr.ocr(temp_img_path, cls=True)
            
            # Clean up temp file
            if os.path.exists(temp_img_path):
                os.remove(temp_img_path)
                
            # Extract text from OCR result
            text_lines = []
            if result and result[0]:
                for line in result[0]:
                    text_lines.append(line[1][0])
            return "\n".join(text_lines)
        except Exception as e:
            print(f"OCR failed for {filepath} page {page_num}: {e}")
            return ""
