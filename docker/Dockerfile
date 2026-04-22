# Multi-stage build: backend image
FROM python:3.12-slim as backend

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies used by Backend/main.py entrypoint
COPY Backend/requirements.txt ./Backend/requirements.txt
RUN pip install --no-cache-dir -r Backend/requirements.txt

# Copy source code
COPY Backend/ ./Backend/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY data/ ./data/

RUN useradd -m -u 1000 geoai && chown -R geoai:geoai /app
USER geoai

EXPOSE 8000

# Single backend entrypoint (aligned with frontend /api contract)
CMD ["uvicorn", "Backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Frontend build stage (placeholder)
FROM node:18-alpine as frontend

WORKDIR /app/frontend

# Final stage: nginx
FROM nginx:alpine

COPY docker/nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
