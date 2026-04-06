# 多阶段构建：后端API服务
FROM python:3.12-slim as backend

WORKDIR /app

# 安装系统依赖（PostGIS客户端等）
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY pyproject.toml requirements.txt ./

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY data/ ./data/

# 创建非root用户
RUN useradd -m -u 1000 geoai && chown -R geoai:geoai /app
USER geoai

# 暴露端口
EXPOSE 8000

# 启动命令（默认为API服务）
CMD ["uvicorn", "src.geoai.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# 前端构建阶段（如果需要）
FROM node:18-alpine as frontend

WORKDIR /app/frontend

# 复制前端代码（未来实现）
# COPY frontend/package.json frontend/package-lock.json ./
# RUN npm ci --only=production

# 构建前端
# RUN npm run build

# 最终阶段：Nginx服务
FROM nginx:alpine

# 复制Nginx配置
COPY docker/nginx.conf /etc/nginx/nginx.conf

# 从前端阶段复制构建产物
# COPY --from=frontend /app/frontend/dist /usr/share/nginx/html

# 从后端阶段复制静态文件（如果需要）
# COPY --from=backend /app/static /usr/share/nginx/html/static

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]