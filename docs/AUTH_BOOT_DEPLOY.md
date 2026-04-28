# 登录页与启动加载页部署说明

本文记录 GeoAI 当前“单管理员登录 + 启动加载页”的运行方式，以及部署时必须注意的事项。

## 1. 功能范围

当前实现包含：

- 登录页：`/login`
- 启动加载页：前端启动阶段的全屏等待页
- 后端认证接口：
  - `POST /api/auth/login`
  - `POST /api/auth/logout`
  - `GET /api/auth/me`
- 整站登录门禁

保留匿名访问的接口：

- `GET /health`
- `GET /api/search/health`

## 2. 当前认证模型

- 只支持单管理员账号
- 用户信息不进数据库
- 管理员账号从 `Backend/.env` 读取
- 会话通过 `JWT + HttpOnly Cookie` 维持
- 前端通过 `/api/auth/me` 恢复登录态

## 3. 必要环境变量

`Backend/.env` 至少要有这些项：

```env
SECRET_KEY=replace_with_strong_random_value
ACCESS_TOKEN_EXPIRE_MINUTES=30

ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=
# 或者使用明文回退：
ADMIN_PASSWORD=replace_with_strong_password

AUTH_COOKIE_NAME=geoai_session
AUTH_COOKIE_SECURE=True
```

说明：

- 生产环境优先使用 `ADMIN_PASSWORD_HASH`
- 如果暂时没有哈希生成流程，可以短期使用 `ADMIN_PASSWORD`
- `SECRET_KEY` 不能使用开发默认值
- 登录 Cookie 名与前端必须一致

## 4. HTTPS 要求

生产环境必须满足：

- 登录页通过 `HTTPS` 打开
- 后端认证接口通过 `HTTPS` 访问
- `AUTH_COOKIE_SECURE=True`

原因：

- `Secure` Cookie 在 `HTTP` 下不会发送
- 如果用户用 `http://` 打开站点，会出现“登录成功但后续接口仍未登录”的假象

建议：

- 对外使用时优先引导用户访问 `https://SERVER_PUBLIC_IP/`
- 如果将来证书和域名都稳定，可以再考虑是否把 `80` 统一跳转到 `443`

## 5. 启动加载页判定条件

启动加载页不是假动画，而是等待真实初始化完成。当前至少依赖三类状态：

1. 会话恢复完成
2. 后端健康检查通过
3. 核心地图与行政区划数据已就绪

因此如果下面任一条件不满足，前端会停留在加载态或失败态：

- `/health` 不通
- `/api/auth/me` 返回异常
- `china-provinces.json` 无法加载
- 当前地图引擎未完成初始化

## 6. 发布前检查

涉及登录或加载页改动时，发布前至少确认：

- `frontend` 本地 `npm run lint` 通过
- `frontend` 本地 `npm run build` 通过
- 后端能正常导入并启动
- 未登录访问受保护接口返回 `401`
- 登录后 `/api/auth/me` 返回当前管理员身份
- 登录后访问一个受保护接口返回 `200`

## 7. 服务器发布步骤

```bash
cd /srv/geoai/app
git fetch origin
git switch prod-hardening
git pull --ff-only origin prod-hardening
node scripts/deploy_frontend_build.mjs \
  --expected-commit YOUR_GIT_COMMIT_SHA \
  --npm-install ci
sudo systemctl restart geoai-backend
```

如果 `package.json` 没变化，可以把 `--npm-install ci` 改成 `--npm-install skip`。

## 8. 服务器构建环境注意事项

当前前端构建依赖对 Node 版本较敏感：

- 推荐 `Node 20.19+`
- 更稳妥的是 `Node 22 LTS`

如果服务器还是 `Node 18`，可能遇到：

- `@tailwindcss/oxide` 原生绑定找不到
- `vite` / `@vitejs/plugin-react` 引擎版本告警
- `cesium` 相关依赖的 Node 版本不兼容

一旦服务器前端依赖升级，优先考虑先升级 Node，再跑构建。

## 9. 发布后验收

### 匿名接口

```bash
curl -s https://SERVER_PUBLIC_IP/health
curl -s https://SERVER_PUBLIC_IP/api/search/health
```

### 登录流

```bash
curl -s -c /tmp/geoai_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_ADMIN_USERNAME","password":"YOUR_ADMIN_PASSWORD"}' \
  https://SERVER_PUBLIC_IP/api/auth/login

curl -s -b /tmp/geoai_cookie.txt https://SERVER_PUBLIC_IP/api/auth/me
curl -s -b /tmp/geoai_cookie.txt https://SERVER_PUBLIC_IP/api/spatial/provinces-test
```

### 版本一致性

```bash
cd /srv/geoai/app
git rev-parse HEAD
cat frontend/dist/build-meta.json
git status --short
```

必须确认：

- `HEAD` 等于本次发布 commit
- `build-meta.json.git_commit` 等于同一 commit
- 工作区没有遗留源码脏改动

## 10. 常见故障

### 1. 登录成功后立刻掉回登录页

优先检查：

- 是否用 `http://` 访问了站点
- `AUTH_COOKIE_SECURE` 是否为 `True`
- 浏览器是否真的带上了认证 Cookie

### 2. 启动加载页一直不消失

优先检查：

- `/health` 是否正常
- `/api/auth/me` 是否正常
- 行政区划数据是否能加载
- 地图引擎资源是否正常返回

### 3. nginx 返回 `502`

优先检查：

- `geoai-backend` 是否刚重启，Uvicorn 是否已经真正起来
- `systemctl status geoai-backend`
- `journalctl -u geoai-backend -n 100 --no-pager`
- `curl http://127.0.0.1:8000/health`
