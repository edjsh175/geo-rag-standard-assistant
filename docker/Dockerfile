FROM python:3.12-slim AS backend

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY Backend/requirements.txt ./Backend/requirements.txt
RUN pip install --no-cache-dir -r Backend/requirements.txt

COPY Backend/ ./Backend/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY data/ ./data/

RUN useradd -m -u 1000 geoai && chown -R geoai:geoai /app
USER geoai

EXPOSE 8000
CMD ["uvicorn", "Backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:alpine AS frontend-runtime
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-build /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
