# GeoAI 发布工作流

这份文档只回答一件事：以后如何安全地把代码发布到服务器。

## 1. 角色分工

- `prod-hardening`：正式生产主线
- `fix/*` 或 `feat/*`：临时开发分支
- 服务器：运行环境，不是长期源码主战场
- GitHub：版本标准和备份标准

规则：

- 服务器当前运行的代码，必须能对应到 GitHub 上的一个明确 commit
- 不要长期在服务器上保留未提交改动
- 如果服务器上做了热修，必须尽快提交并推回 GitHub

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

## 3. 正式发布

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

如果前端依赖刚发生过变化，把 `--npm-install skip` 改成 `--npm-install ci`。

## 4. 发布后验证

服务器上执行：

```bash
cd /srv/geoai/app
git branch --show-current
git rev-parse HEAD
cat frontend/dist/build-meta.json
curl -s http://127.0.0.1/health
curl -s http://127.0.0.1/ | grep -o '/assets/index-[^"]*\.js' | head -n 1
```

必须确认：

- 当前分支是 `prod-hardening`
- 当前 `HEAD` 等于你准备发布的 commit
- `frontend/dist/build-meta.json` 里的 `git_commit` 也等于同一个 commit

## 5. 热修原则

如果必须在服务器上直接改代码：

1. 先确认改动范围足够小
2. 改完后立刻 `git add`、`git commit`
3. 尽快推回 GitHub
4. 不要让“服务器工作目录脏状态”持续存在

如果暂时不能马上整理，就先创建一个备份分支，例如：

```bash
git switch -c backup/server-YYYYMMDD-HHMM
git add -A
git commit -m "backup(server): snapshot before reconciliation"
git push -u origin backup/server-YYYYMMDD-HHMM
```

## 6. 版本标记

每次正式上线后打 tag：

```bash
git tag -a deploy-YYYYMMDD-short-name -m "production deploy"
git push origin deploy-YYYYMMDD-short-name
```

这样以后能快速回答三件事：

- 线上现在跑的是哪个版本
- 某次上线改了什么
- 需要回滚时应该回到哪个点
