FROM python:3.11-slim

# System dependencies for building native extensions and OCR/PDF parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and pre-install CPU-optimized PyTorch
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio

# Install Python dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    (python -m spacy download en_core_web_sm || true)

# Copy application code
COPY . .

# Expose FastAPI and Streamlit ports
EXPOSE 8000 8501

# Default: run FastAPI server
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
