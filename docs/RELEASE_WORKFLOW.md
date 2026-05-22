# GeoRAG Planning Assistant 发布工作流

这份文档只回答一件事：以后如何把代码安全、可追踪地发布到服务器。

## 1. 分支约定

- `prod-hardening`：正式生产主线
- `fix/*`、`feat/*`：短期开发分支
- `backup/local-YYYYMMDD-HHMM`：本地脏状态快照
- `backup/server-YYYYMMDD-HHMM`：服务器上线前快照
- `deploy-YYYYMMDD-short-name`：正式上线 tag

规则：

- 服务器当前运行的代码必须能对应到 GitHub 上的一个明确 commit
- 不要长期在服务器上保留未提交源码改动
- 如果服务器临时热修过，必须尽快收口回 GitHub

## 2. 日常开发

从生产主线拉一个短分支：

```bash
git switch prod-hardening
git pull --ff-only origin prod-hardening
git switch -c fix/your-change
```

开发完成后：

```bash
git add -A
git commit -m "fix: describe your change"
git push -u origin fix/your-change
```

确认无误后，把变更合回 `prod-hardening`。

## 3. 有脏状态时先备份

如果本地工作区不干净，先封存再开发：

```bash
git switch -c backup/local-YYYYMMDD-HHMM
git add -A
git commit -m "backup(local): snapshot before new work"
git push -u origin backup/local-YYYYMMDD-HHMM
```

如果服务器工作区不干净，也先保留一个快照分支。即使脏项只是生成目录，也要先确认再继续。

## 4. 正式发布

先在本地确认要发布的 commit：

```bash
git switch prod-hardening
git pull --ff-only origin prod-hardening
git rev-parse HEAD
```

假设要发布的 commit 是 `YOUR_GIT_COMMIT_SHA`。

服务器发布步骤：

```bash
cd /srv/geoai/app
git fetch origin
git switch prod-hardening
git pull --ff-only origin prod-hardening
node scripts/deploy_frontend_build.mjs \
  --expected-commit YOUR_GIT_COMMIT_SHA \
  --npm-install skip
```

如果前端依赖刚发生变化，把 `--npm-install skip` 改成 `--npm-install ci`。

## 5. 前端构建注意事项

- `scripts/deploy_frontend_build.mjs` 会先检查 `git rev-parse HEAD` 是否等于 `--expected-commit`
- 构建成功后会写出 `frontend/dist/build-meta.json`
- 线上静态资源版本必须以 `build-meta.json` 为准，而不是以浏览器缓存判断
- 当前前端依赖建议服务器使用 `Node 20.19+` 或 `Node 22 LTS`
- 如果服务器仍是 `Node 18`，有可能在 `@tailwindcss/oxide`、`vite` 或 `cesium` 依赖上出现构建兼容问题

## 6. 登录与加载页发布注意事项

登录页和启动加载页上线后，发布流程要额外检查这些前提：

- `Backend/.env` 必须设置 `ADMIN_USERNAME`
- `Backend/.env` 必须设置 `ADMIN_PASSWORD_HASH` 或 `ADMIN_PASSWORD`
- `AUTH_COOKIE_NAME` 应保持与前端一致，默认是 `geoai_session`
- 生产环境 `AUTH_COOKIE_SECURE=True`
- 生产环境必须通过 `HTTPS` 访问，否则浏览器不会带上安全 Cookie
- `/health` 和 `/api/search/health` 保持匿名可访问，供启动加载页使用
- 其他受保护业务接口未登录访问应返回 `401`

详细认证说明见 [AUTH_BOOT_DEPLOY.md](/D:/work/Project/ragAI知识库%20(2)/ragAI知识库/docs/AUTH_BOOT_DEPLOY.md:1)。

## 7. 发布后验证

服务器上执行：

```bash
cd /srv/geoai/app
git branch --show-current
git rev-parse HEAD
git status --short
cat frontend/dist/build-meta.json
curl -s http://127.0.0.1:8000/health
curl -s https://SERVER_PUBLIC_IP/health
curl -s https://SERVER_PUBLIC_IP/api/search/health
```

必须确认：

- 当前分支是 `prod-hardening`
- 当前 `HEAD` 等于你准备发布的 commit
- `git status --short` 为空，或只剩明确允许的临时文件
- `frontend/dist/build-meta.json` 里的 `git_commit` 也等于同一个 commit

如果本次发布包含登录相关改动，再补做一次会话验证：

```bash
curl -s -c /tmp/geoai_cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_ADMIN_USERNAME","password":"YOUR_ADMIN_PASSWORD"}' \
  https://SERVER_PUBLIC_IP/api/auth/login

curl -s -b /tmp/geoai_cookie.txt https://SERVER_PUBLIC_IP/api/auth/me
curl -s -b /tmp/geoai_cookie.txt https://SERVER_PUBLIC_IP/api/spatial/provinces-test
```

## 8. 热修原则

如果必须直接在服务器上改代码：

1. 先确认改动范围足够小
2. 先做 `backup/server-*`
3. 改完后立刻收口回 GitHub
4. 不要让服务器工作目录长期维持脏状态

## 9. 版本标记

每次正式上线后打 tag：

```bash
git tag -a deploy-YYYYMMDD-short-name -m "production deploy"
git push origin deploy-YYYYMMDD-short-name
```

这样以后可以快速回答三件事：

- 线上现在跑的是哪个版本
- 某次上线改了什么
- 需要回滚时应该回到哪个点
