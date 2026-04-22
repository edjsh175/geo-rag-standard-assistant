# GeoAI Frontend

## 概述
前端基于 React + Vite，提供：
- 聊天检索交互面板
- 2D/3D 地图展示与联动
- 文档引用与详情抽屉

## 本地启动
```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://localhost:3000`

## API 配置
前端 API 基础地址位于 `src/lib/api/config.ts`：
- 默认：`http://localhost:8000/api`
- 可通过 `VITE_API_URL` 覆盖

## 目录
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
