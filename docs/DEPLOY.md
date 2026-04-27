# GeoAI 竞赛环境部署指南

本文档用于小型单机竞赛演示部署，当前推荐采用 **非 Docker** 方式部署。

## 目标服务器

- 操作系统：Ubuntu 22.04 LTS 或 Ubuntu 24.04 LTS
- CPU/内存：至少 2 vCPU / 4 GB RAM
- 磁盘：至少 80 GB
- 公网访问：只开放 `22`、`80`，如启用 HTTPS 再开放 `443`

竞赛快速演示时，可以直接把服务器公网 IP 提供给评委：

```text
http://SERVER_PUBLIC_IP
```

## 运行目录规划

```text
/srv/geoai/app          仓库代码目录
/srv/geoai/venv         后端 Python 虚拟环境
/srv/geoai/frontend     前端构建产物目录，可复制或链接 frontend/dist
/etc/systemd/system/geoai-backend.service
/etc/nginx/sites-available/geoai
```

公网请求路径应为：

```text
/       -> 前端静态页面
/api    -> 反向代理到 127.0.0.1:8000 上的 FastAPI 后端
```

不要把 PostgreSQL、MySQL、Redis、MinIO 端口直接暴露到公网。

## 当前依赖范围

- PostgreSQL + pgvector：必需，用于 `policy_chunks` 向量检索数据。
- PostGIS：必需，用于 `spatial_regions` 空间查询数据。
- MySQL：必需，使用 `disaster_knowledge.geoai_metadata` 存储标准元数据。
- MinIO：当前竞赛主流程不需要。它只是后续文档对象存储能力的预留，例如 AI 引用文档后点击下载源文件。

## 安装基础软件

```bash
apt update
apt install -y nginx git curl python3-venv python3-pip nodejs npm postgresql postgresql-contrib postgis mysql-server redis-server
systemctl enable --now nginx
systemctl enable --now postgresql
systemctl enable --now mysql
systemctl enable --now redis-server
```

## 拉取代码

```bash
mkdir -p /srv/geoai
cd /srv/geoai
git clone https://github.com/edjsh175/-AI---RAG-.git app
cd app
git checkout prod-hardening
```

## 数据库初始化

先创建 PostgreSQL 应用用户和数据库。执行前请把示例密码替换为强密码。

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

如果 `CREATE EXTENSION vector` 失败，说明服务器缺少匹配当前 PostgreSQL 版本的 pgvector 扩展。需要先安装或编译 pgvector，再重新执行扩展创建命令。`geoai_db` 中必须同时存在 `vector` 和 `postgis`，否则不要继续部署。

初始化应用需要的 PostgreSQL 核心表：

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

向量检索路径要求 `policy_chunks` 存在并已导入标准文档切片及 embedding。启用地图区域查询时，空间检索还要求 `spatial_regions` 存在并已导入生产空间数据。公网验收前必须先完成这些数据导入。

创建 MySQL 元数据数据库。按当前服务器截图口径，数据库名为 `disaster_knowledge`，元数据表名为 `geoai_metadata`。

```bash
mysql -uroot -p <<'SQL'
CREATE DATABASE IF NOT EXISTS disaster_knowledge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'geoai_mysql'@'localhost' IDENTIFIED BY 'replace_with_strong_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON disaster_knowledge.* TO 'geoai_mysql'@'localhost';
FLUSH PRIVILEGES;
SQL
```

导入项目使用的标准元数据：

```bash
mysql -uroot -p disaster_knowledge < /path/to/geoai_metadata.sql
```

导入后的 `geoai_metadata` 表至少应包含这些字段：`standard_code`、`release_date`、`implement_date`、`draft_unit`、`keyword`、`chinese_name`、`english_name`、`standard_status`、`release_unit`、`charge_unit`、`replace_standard`、`application_scope`。

## 后端环境变量

在服务器上创建 `Backend/.env`。所有密钥和密码都要替换为强随机值。

```env
DEBUG=False
HOST=127.0.0.1
PORT=8000

SYSTEM_API_KEY=replace_with_strong_random_value
SECRET_KEY=replace_with_strong_random_value

DATABASE_URL=postgresql+asyncpg://geoai:replace_with_strong_password@127.0.0.1:5432/geoai_db
MYSQL_URL=mysql+aiomysql://geoai_mysql:replace_with_strong_password@127.0.0.1:3306/disaster_knowledge
REDIS_URL=redis://127.0.0.1:6379/0

PUBLIC_API_BASE_URL=http://SERVER_PUBLIC_IP
CORS_ORIGINS=["http://SERVER_PUBLIC_IP"]
```

除非要部署可选的文档对象存储和下载流程，否则不要添加 MinIO 相关变量。后续如果启用 MinIO，也必须保持 MinIO 内网访问、bucket 私有，并且不要对公网开放 `9000` 或 `9001`。

## 后端服务

```bash
cd /srv/geoai/app/Backend
python3 -m venv /srv/geoai/venv
/srv/geoai/venv/bin/pip install --upgrade pip
/srv/geoai/venv/bin/pip install -r requirements.txt
```

创建 `/etc/systemd/system/geoai-backend.service`：

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

启动后端服务：

```bash
systemctl daemon-reload
systemctl enable --now geoai-backend
systemctl status geoai-backend
```

## 前端构建

```bash
cd /srv/geoai/app
node scripts/deploy_frontend_build.mjs \
  --expected-commit YOUR_GIT_COMMIT_SHA \
  --npm-install ci
```

前端默认请求 `/api`。只要 Nginx 在同一域名下代理 `/api` 到后端，生产环境不需要额外配置 `VITE_API_URL`。

Build guard:
- `scripts/deploy_frontend_build.mjs` checks that `git rev-parse HEAD` matches `--expected-commit` before it runs the build.
- The script writes `frontend/dist/build-meta.json` after a successful build so the live static assets can be traced back to one exact commit.
- If dependencies are already up to date, you can replace `--npm-install ci` with `--npm-install skip`.

Verify the deployed frontend revision:
```bash
cat /srv/geoai/app/frontend/dist/build-meta.json
curl -s http://SERVER_PUBLIC_IP/build-meta.json
```

If `build-meta.json` shows the wrong `git_commit`, treat it as a source-version mismatch on the server rather than a browser cache issue.
## Nginx

创建 `/etc/nginx/sites-available/geoai`：

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

启用 Nginx 配置：

```bash
ln -sf /etc/nginx/sites-available/geoai /etc/nginx/sites-enabled/geoai
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

## 验收检查

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://SERVER_PUBLIC_IP/health
curl -i http://SERVER_PUBLIC_IP/api/search/suggest
mysql -ugeoai_mysql -p disaster_knowledge -e "SELECT COUNT(*) FROM geoai_metadata;"
sudo -u postgres psql -d geoai_db -c "SELECT COUNT(*) FROM policy_chunks;"
```

后端健康检查响应中的 `status` 必须是 `healthy`。如果返回 `degraded`，即使 HTTP 状态码曾经是 `200`，也应视为部署失败。当前代码会在核心依赖异常时返回 `503/degraded`。

最后在浏览器中打开：

```text
http://SERVER_PUBLIC_IP
```

## 生产检查清单

- `DEBUG=False`
- `SYSTEM_API_KEY` 已设置，且不对外公开
- `SECRET_KEY` 已替换为强随机值
- 安全组只开放 `22`、`80`，如启用 HTTPS 再开放 `443`
- PostgreSQL、MySQL、Redis 只监听 localhost 或私有网络
- MySQL 已导入 `disaster_knowledge.geoai_metadata`
- PostgreSQL 已导入并填充 `policy_chunks`
- 如果演示包含空间检索，PostgreSQL 已导入并填充 `spatial_regions`
- 除非启用可选文档下载流程，否则不要安装或暴露 MinIO
- Nginx 已设置上传体积限制 `client_max_body_size 100m`
- 后端服务已由 systemd 管理，并配置自动重启

## Docker 说明

Docker 对当前项目是可选项。本部署指南不依赖 Docker。如果后续改用 Docker 部署，需要保持 `.dockerignore` 严格，避免把本地数据、虚拟环境、`.env` 文件或构建产物复制进镜像。
