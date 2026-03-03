FROM python:3.12-slim

WORKDIR /app

# Install system deps (minimal — no ffmpeg needed, qwen-asr handles OGG natively)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch FIRST (separate from requirements.txt to use custom index)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server.py .

# Pre-download model at build time into image layers
# This makes container startup fast (no download on first run)
# Set TRANSFORMERS_CACHE to a predictable location
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface
ENV ASR_MODEL=Qwen/Qwen3-ASR-1.7B

RUN python -c "\
from qwen_asr import Qwen3ASRModel; \
print('Downloading model...'); \
Qwen3ASRModel.from_pretrained('Qwen/Qwen3-ASR-1.7B', device_map='cpu'); \
print('Model downloaded successfully')"

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -f http://localhost:8086/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8086"]
