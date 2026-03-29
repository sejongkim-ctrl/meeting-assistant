# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.13-slim
WORKDIR /app

# Install dependencies
COPY requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt

# Copy backend source
COPY backend/ backend/
COPY meeting_engine.py speaker_naming.py diarization.py ./

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist/ frontend/dist/

# Create meetings directory for WAV storage
RUN mkdir -p meetings

EXPOSE 8001
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
