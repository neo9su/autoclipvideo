# ── Build stage: Frontend ──────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build

# ── Runtime stage: Backend + Frontend static ──────────────────────────────────
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
       aiohttp \
       opencv-python-headless \
       numpy \
       scipy \
       Pillow \
       imagehash \
       openpyxl \
       sentence-transformers \
       noisereduce \
       soundfile \
       pydantic \
    && pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium

# Copy backend
COPY backend/ ./backend/

# Copy frontend build
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create directories
RUN mkdir -p /app/recordings /app/voice_output /app/data

# Environment defaults
ENV GPU_SERVICE_URL=http://gpu:8877 \
    COMFYUI_URL=http://gpu:8188 \
    WATCHDOG_URL=http://gpu:8878 \
    MAX_CONCURRENT_CLIPS=1 \
    MEM_WARN_GB=5 \
    PYTHONUNBUFFERED=1

# Database volume
VOLUME ["/app/data", "/app/recordings", "/app/voice_output"]

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8899/api/status || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8899"]
