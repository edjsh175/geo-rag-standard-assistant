# GeoRAG Planning Assistant Frontend / GeoRAG 前端

## Overview / 概述

The frontend is a React + Vite application for GeoRAG Planning Assistant. It provides the chat retrieval workspace, document citation interactions, and 2D/3D map visualization.

GeoRAG 前端基于 React + Vite，提供智能检索聊天工作台、文档引用交互、以及二维/三维地图可视化界面。

Main capabilities:

- Chat-based retrieval and Q&A panel.
- 2D/3D map display and view switching.
- Document citation, detail drawer, and source-document download flow.
- Same-origin `/api` integration with the FastAPI backend.

## Local Development / 本地启动

```bash
cd frontend
npm install
npm run dev
```

Default local URL: `http://localhost:3000`

默认本地地址：`http://localhost:3000`

## API Configuration / API 配置

Frontend API configuration lives in `src/lib/api/config.ts`:

- Default: `/api`
- Local development: Vite proxies `/api` to `http://localhost:8000`
- Override with `VITE_API_URL` only for cross-origin or special deployment scenarios

前端 API 基础地址位于 `src/lib/api/config.ts`：

- 默认：`/api`
- 本地开发时，Vite 会把 `/api` 代理到 `http://localhost:8000`
- 仅在跨域或特殊部署场景通过 `VITE_API_URL` 覆盖

## Directory / 目录

```text
frontend/
├─ src/
│  ├─ components/
│  ├─ services/
│  ├─ store/
│  └─ App.tsx
├─ package.json
└─ vite.config.ts
```
