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

## Current Dependency Scope

- PostgreSQL with pgvector is required for vector search data in `policy_chunks`.
- PostGIS is required for spatial lookup data in `spatial_regions`.
- MySQL is required for standard metadata in `standard_norm_detail`.
- MinIO is not required for the current competition path. It is reserved for a later document-object workflow, for example clicking an AI-cited document and downloading the source file.

## Install Base Packages

```bash
apt update
apt install -y nginx git curl python3-venv python3-pip nodejs npm postgresql postgresql-contrib postgis mysql-server redis-server
systemctl enable --now nginx
systemctl enable --now postgresql
systemctl enable --now mysql
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

## Database Initialization

Create the PostgreSQL application user and database. Replace passwords before running these commands.

```bash
sudo -u postgres psql <<'SQL'
CREATE USER geoai WITH PASSWORD 'replace_with_strong_password';
CREATE DATABASE geoai_db OWNER geoai;
\c geoai_db
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
GRANT ALL PRIVILEGES ON DATABASE geoai_db TO geoai;
GRANT USAGE, CREATE ON SCHEMA public TO geoai;
SQL
```

If `CREATE EXTENSION vector` fails, install the pgvector package that matches the server PostgreSQL version, or build and install pgvector before rerunning the command. Do not continue deployment until both `vector` and `postgis` are available in `geoai_db`.

Initialize the core PostgreSQL tables used by the app:

```bash
sudo -u postgres psql -d geoai_db <<'SQL'
CREATE TABLE IF NOT EXISTS policy_chunks (
    id bigserial PRIMARY KEY,
    standard_code varchar(100),
    category varchar(100),
    keyword varchar(100),
    chinese_name varchar(500),
    english_name varchar(500),
    release_date varchar(20),
    implement_date varchar(20),
    standard_status varchar(50),
    release_unit varchar(255),
    charge_unit varchar(255),
    draft_unit varchar(255),
    replace_standard varchar(500),
    application_scope text,
    document_name varchar(255),
    header_path text,
    content text,
    embedding vector(2048)
);

CREATE INDEX IF NOT EXISTS idx_policy_chunks_standard_code
    ON policy_chunks (standard_code);

CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS spatial_regions (
    id serial PRIMARY KEY,
    adcode varchar(20),
    region_name varchar(100),
    geometry geometry(MultiPolygon, 4326),
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_spatial_regions_geometry
    ON spatial_regions USING gist (geometry);

ALTER TABLE policy_chunks OWNER TO geoai;
ALTER TABLE spatial_regions OWNER TO geoai;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO geoai;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO geoai;
SQL
```

The vector search path expects `policy_chunks` to exist and contain embedded standard chunks. Spatial search expects `spatial_regions` to exist when map-region queries are enabled. Import the production vector/spatial data before public verification.

Create the MySQL metadata database. The application expects a table named `standard_norm_detail`.

```bash
mysql -uroot -p <<'SQL'
CREATE DATABASE IF NOT EXISTS geoai_metadata CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'geoai_mysql'@'localhost' IDENTIFIED BY 'replace_with_strong_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON geoai_metadata.* TO 'geoai_mysql'@'localhost';
FLUSH PRIVILEGES;
SQL
```

Import the standard metadata dump used by the project:

```bash
mysql -uroot -p geoai_metadata < /path/to/standard_norm_detail.sql
```

The imported `standard_norm_detail` table must include at least these fields: `standard_code`, `release_date`, `implement_date`, `draft_unit`, `keyword`, `chinese_name`, `english_name`, `standard_status`, `release_unit`, `charge_unit`, `replace_standard`, and `application_scope`.

## Backend Environment

Create `Backend/.env` on the server. Use strong random values for secrets.

```env
DEBUG=False
HOST=127.0.0.1
PORT=8000

SYSTEM_API_KEY=replace_with_strong_random_value
SECRET_KEY=replace_with_strong_random_value

DATABASE_URL=postgresql+asyncpg://geoai:replace_with_strong_password@127.0.0.1:5432/geoai_db
MYSQL_URL=mysql+aiomysql://geoai_mysql:replace_with_strong_password@127.0.0.1:3306/geoai_metadata
REDIS_URL=redis://127.0.0.1:6379/0

PUBLIC_API_BASE_URL=http://SERVER_PUBLIC_IP
CORS_ORIGINS=["http://SERVER_PUBLIC_IP"]
```

Do not add MinIO variables unless the optional document-object download workflow is being deployed. If that later workflow is enabled, keep MinIO internal, keep the bucket private, and do not open ports `9000` or `9001` publicly.

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
        proxy_buffering off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri /index.html;
    }

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
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
mysql -ugeoai_mysql -p geoai_metadata -e "SELECT COUNT(*) FROM standard_norm_detail;"
sudo -u postgres psql -d geoai_db -c "SELECT COUNT(*) FROM policy_chunks;"
```

The backend health response must report `status` as `healthy`. Treat `degraded` as a failed deployment, even when the HTTP status code is `200`.

Then open:

```text
http://SERVER_PUBLIC_IP
```

## Production Checklist

- `DEBUG=False`
- `SYSTEM_API_KEY` is set and not shared publicly
- `SECRET_KEY` is changed from defaults
- Security group exposes only `22`, `80`, and optionally `443`
- PostgreSQL, MySQL, and Redis bind only to localhost or private network
- `standard_norm_detail` is imported into MySQL
- `policy_chunks` is populated in PostgreSQL
- `spatial_regions` is populated when spatial search is part of the demo
- MinIO is not installed or exposed unless the optional document download workflow is enabled
- Upload body limit is set at Nginx with `client_max_body_size 100m`
- Backend service is managed by systemd and restarts automatically

## Docker Notes

Docker is optional for this project. If you later use Docker, keep `.dockerignore` strict and avoid copying local data, virtual environments, `.env` files, or build artifacts into images.
