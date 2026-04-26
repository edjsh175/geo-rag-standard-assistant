# GeoAI Competition Deployment Guide

This guide is for a small single-server competition deployment without Docker.

## Target Server

- OS: Ubuntu 22.04 LTS or Ubuntu 24.04 LTS
- CPU/RAM: at least 2 vCPU / 4 GB RAM
- Disk: at least 80 GB
- Public access: open ports `22`, `80`, and optionally `443`

For a quick competition demo, you can give judges the server IP directly:

```text
http://SERVER_PUBLIC_IP
```

## Runtime Layout

```text
/srv/geoai/app          repository checkout
/srv/geoai/venv         backend Python virtual environment
/srv/geoai/frontend     frontend build output copied or linked from frontend/dist
/etc/systemd/system/geoai-backend.service
/etc/nginx/sites-available/geoai
```

The public request path should be:

```text
/       -> frontend static files
/api    -> FastAPI backend on 127.0.0.1:8000
```

Do not expose PostgreSQL, MySQL, Redis, or MinIO ports to the public internet.

## Install Base Packages

```bash
apt update
apt install -y nginx git curl python3-venv python3-pip nodejs npm postgresql postgresql-contrib redis-server
systemctl enable --now nginx
systemctl enable --now postgresql
systemctl enable --now redis-server
```

## Get The Code

```bash
mkdir -p /srv/geoai
cd /srv/geoai
git clone https://github.com/edjsh175/-AI---RAG-.git app
cd app
git checkout prod-hardening
```

## Backend Environment

Create `Backend/.env` on the server. Use strong random values for secrets.

```env
DEBUG=False
HOST=127.0.0.1
PORT=8000

SYSTEM_API_KEY=replace_with_strong_random_value
SECRET_KEY=replace_with_strong_random_value

DATABASE_URL=postgresql+asyncpg://geoai:replace_with_strong_password@127.0.0.1:5432/geoai_db
MYSQL_URL=mysql+aiomysql://root:replace_with_strong_password@127.0.0.1:3306/geoai_metadata
REDIS_URL=redis://127.0.0.1:6379/0

MINIO_URL=127.0.0.1:9000
MINIO_ACCESS_KEY=replace_with_minio_user
MINIO_SECRET_KEY=replace_with_minio_password
MINIO_BUCKET=geoai-assets
MINIO_SECURE=False

PUBLIC_API_BASE_URL=http://SERVER_PUBLIC_IP
CORS_ORIGINS=["http://SERVER_PUBLIC_IP"]
```

If the competition demo does not need document object storage, keep MinIO internal and do not open ports `9000` or `9001` publicly.

## Backend Service

```bash
cd /srv/geoai/app/Backend
python3 -m venv /srv/geoai/venv
/srv/geoai/venv/bin/pip install --upgrade pip
/srv/geoai/venv/bin/pip install -r requirements.txt
```

Create `/etc/systemd/system/geoai-backend.service`:

```ini
[Unit]
Description=GeoAI FastAPI backend
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
WorkingDirectory=/srv/geoai/app/Backend
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/geoai/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Start it:

```bash
systemctl daemon-reload
systemctl enable --now geoai-backend
systemctl status geoai-backend
```

## Frontend Build

```bash
cd /srv/geoai/app/frontend
npm ci
npm run build
```

The frontend defaults to `/api`, so no production API override is required when Nginx proxies `/api` on the same host.

## Nginx

Create `/etc/nginx/sites-available/geoai`:

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 100m;

    root /srv/geoai/app/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

Enable it:

```bash
ln -sf /etc/nginx/sites-available/geoai /etc/nginx/sites-enabled/geoai
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

## Verify

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://SERVER_PUBLIC_IP/health
curl -i http://SERVER_PUBLIC_IP/api/search/suggest
```

Then open:

```text
http://SERVER_PUBLIC_IP
```

## Production Checklist

- `DEBUG=False`
- `SYSTEM_API_KEY` is set and not shared publicly
- `SECRET_KEY` is changed from defaults
- Security group exposes only `22`, `80`, and optionally `443`
- Database, Redis, and MinIO bind only to localhost or private network
- Upload body limit is set at Nginx with `client_max_body_size 100m`
- Backend service is managed by systemd and restarts automatically

## Docker Notes

Docker is optional for this project. If you later use Docker, keep `.dockerignore` strict and avoid copying local data, virtual environments, `.env` files, or build artifacts into images.
