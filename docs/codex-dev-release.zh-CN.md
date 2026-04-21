# Codex 开发、发布与自动部署协作手册

本文给团队同事使用，目标是把一次代码变更从“让 Codex 写完代码”推进到“提交仓库、打 tag、构建镜像、服务器自动部署”。

## 1. 总体链路

推荐链路如下：

```text
需求/缺陷
  -> 同事让 Codex 修改代码
  -> Codex 运行测试和静态检查
  -> Codex 提交 commit 并 push
  -> 人工 review / 合并
  -> 需要发布时打版本 tag
  -> GitHub Actions 根据 tag 构建镜像并推送 GHCR
  -> 服务器检测到新镜像 tag
  -> 服务器本地执行单服务部署
  -> 验证通过后进入下一服务或结束
```

核心原则：

- 代码提交和镜像构建在 GitHub 仓库完成。
- 镜像发布以 tag 为准。
- 生产部署在服务器本地执行，不把生产密钥提交到 Git。
- 自动部署优先使用“服务器拉取式”，即服务器自己检查并部署已批准的 tag。
- 如果启用 GitHub Actions 直连生产，必须单独评审安全风险。

## 2. 角色分工

同事负责：

- 描述需求。
- 判断是否允许 Codex 提交。
- Review Codex 的 diff。
- 决定是否发布。
- 确认发布 tag。

Codex 负责：

- 阅读代码。
- 实现变更。
- 运行测试。
- 总结改动。
- 创建 commit。
- 在明确授权时 push 或打 tag。

GitHub Actions 负责：

- 根据 tag 编译代码。
- 构建 Docker 镜像。
- 推送到 GHCR。

生产服务器负责：

- 保存 `.env.prod`、`control/`、`data/`、`log/`。
- 拉取新镜像。
- 使用 `dc-quant-deploy` 单服务重启或部署。
- 保存部署日志和回滚能力。

## 3. 前置准备

### 3.1 本地开发机

同事本地需要：

- Git。
- Codex。
- 对应源码仓库访问权限。
- Maven / Node / JDK 等项目构建工具。
- GitHub 推送权限。

建议先配置 Git 身份：

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### 3.2 GitHub 仓库

每个服务仓库需要具备：

- `Dockerfile` 或等价镜像构建入口。
- GitHub Actions 镜像构建 workflow。
- `GHCR` 推送权限。
- tag 触发规则。
- main 分支保护或 review 规则。

建议 workflow 触发：

```yaml
on:
  push:
    tags:
      - "v*"
```

镜像 tag 与 Git tag 保持一致。

### 3.3 生产服务器

生产服务器需要：

- Docker Engine。
- Docker Compose plugin。
- `dc-quant-deploy` 仓库。
- `.env.prod`。
- GHCR 登录态，或镜像为公开可拉取。
- `control/`、`data/`、`log/` 运行目录。

生产服务器不需要保存源码仓库，也不需要本地编译 Java。

## 4. 服务与镜像对应关系

| 服务 | 源码仓库 | 镜像 |
| --- | --- | --- |
| `gateway` / `GW` | `bliplink/gateway` | `ghcr.io/bliplink/gw:${GW_TAG}` |
| `mdsvr` | `bliplink/com.app.dc.mdsvr` | `ghcr.io/bliplink/mdsvr:${MDSVR_TAG}` |
| `apssvr` | `bliplink/com.app.dc.apssvr` | `ghcr.io/bliplink/apssvr:${APSSVR_TAG}` |
| `quantsvr` | `bliplink/com.app.dc.quantsvr` | `ghcr.io/bliplink/quantsvr:${QUANTSVR_TAG}` |
| `indsvr` | `bliplink/com.app.dc.indsvr` | `ghcr.io/bliplink/indsvr:${INDSVR_TAG}` |
| `simsvr` | `SKT-Walter/com.app.dc.simulation` | `ghcr.io/SKT-Walter/simsvr:${SIMSVR_TAG}` |
| `batchsvr` | `bliplink/com.app.dc.batchsvr` | `ghcr.io/bliplink/batchsvr:${BATCHSVR_TAG}` |
| `web` | `SKT-Walter/com.app.dc.web` | `ghcr.io/SKT-Walter/web:${WEB_TAG}` |
| `zookeeper` | `bliplink/zookeeper` | `ghcr.io/bliplink/zookeeper:${ZOOKEEPER_TAG}` |

## 5. Codex 日常开发流程

### 5.1 开始任务

进入目标源码仓库：

```bash
git checkout main
git pull --ff-only
git checkout -b feat/<short-name>
```

给 Codex 的推荐指令：

```text
请实现这个需求：<写清楚需求>

要求：
1. 先阅读相关代码，不要凭空改。
2. 修改完成后运行必要测试。
3. 不要提交真实密钥或生产配置。
4. 完成后提交到当前分支，commit message 用英文动词开头。
5. 最后说明改了什么、怎么验证、是否还有风险。
```

如果是修 bug：

```text
请定位并修复这个问题：<现象、日志、复现步骤>

要求：
1. 先找根因，再改代码。
2. 尽量补测试或给出可验证命令。
3. 修复完成后提交 commit。
```

### 5.2 Codex 提交前检查

Codex 应至少完成：

```bash
git status --short
git diff
```

按项目类型运行：

```bash
mvn test
```

或：

```bash
npm test
npm run build
```

如果测试无法运行，Codex 必须在最终说明里写清楚原因。

### 5.3 提交和推送

Codex 可以在明确授权后提交：

```bash
git add <changed-files>
git commit -m "Fix apssvr timeout handling"
git push origin feat/<short-name>
```

推荐通过 PR 合并到 `main`。如果团队允许直接推主分支，也必须先确认：

```bash
git status --short
git log --oneline -5
```

## 6. 发布 tag 规则

推荐 tag 规则：

- 测试版：`v0.0.2-test.1`
- 预发布：`v0.0.2-rc.1`
- 正式版：`v0.0.2`

每个服务仓库独立打 tag。不要在一个仓库里用同一个 tag 代表多个服务。

打 tag 前必须确认：

```bash
git checkout main
git pull --ff-only
git status --short
git log --oneline -5
```

创建并推送 tag：

```bash
git tag -a v0.0.2-test.1 -m "Release v0.0.2-test.1"
git push origin v0.0.2-test.1
```

推送 tag 后，GitHub Actions 应自动构建并推送镜像：

```text
ghcr.io/<owner>/<image>:v0.0.2-test.1
```

## 7. 等待镜像编译完成

同事需要在 GitHub Actions 页面确认：

- workflow 成功。
- 镜像 push 成功。
- GHCR 能看到新 tag。

也可以在服务器上验证镜像是否可拉取：

```bash
docker pull ghcr.io/bliplink/apssvr:v0.0.2-test.1
```

如果镜像是私有的，服务器需要先登录：

```bash
docker login ghcr.io
```

## 8. 服务器自动部署推荐方案

推荐使用“服务器拉取式自动部署”，避免 GitHub Actions 直接持有生产 SSH 权限。

### 8.1 发布请求文件

在服务器本地维护一个待发布文件，例如：

```text
/data/strategy/dc-quant-deploy/releases/prod/apssvr.tag
```

内容只有一个 tag：

```text
v0.0.2-test.1
```

服务器自动部署脚本读取这个文件，与当前 `.env.prod` 中的 `APSSVR_TAG` 比较。如果不同，则执行：

```bash
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

部署成功后，把 `.env.prod` 中的 `APSSVR_TAG` 更新为新 tag，并记录部署日志。

### 8.2 自动部署脚本职责

自动部署脚本应该做这些事：

1. 加锁，避免两个部署同时执行。
2. 读取目标服务和目标 tag。
3. 校验 tag 格式。
4. 生成 `compose.override.generated.yaml`。
5. `docker pull` 目标镜像。
6. 更新 `.env.prod` 中对应服务 tag。
7. `./restart-service.sh <service>`。
8. 校验容器状态、端口、最近日志。
9. 成功则记录当前版本。
10. 失败则恢复旧 tag 并重启旧镜像。

### 8.3 定时检查

可以用 cron 每分钟检查一次发布请求：

```cron
* * * * * cd /data/strategy/dc-quant-deploy && ./auto-deploy-pending-release.sh >> /data/strategy/log/auto-deploy.log 2>&1
```

注意：`auto-deploy-pending-release.sh` 是需要额外实现的脚本。当前仓库已有 `restart-service.sh`，但完整自动部署守护脚本需要单独补齐。

## 9. GitHub Actions 直连生产方案

如果团队明确接受 GitHub Actions 持有生产 SSH 权限，也可以在镜像构建成功后直接执行远程部署。

这种方案需要 GitHub Secrets：

- `PROD_HOST`
- `PROD_PORT`
- `PROD_USER`
- `PROD_SSH_KEY`

远程执行逻辑示例：

```bash
cd /data/strategy/dc-quant-deploy
git pull --ff-only
./deploy-image-tag.sh apssvr v0.0.2-test.1
```

但这条路线风险更高：

- GitHub Secrets 泄漏会影响生产。
- workflow 配错可能误发生产。
- 生产发布审计会依赖 GitHub Actions。

所以默认建议服务器拉取式自动部署。

## 10. 单服务发布顺序

生产推荐逐服务发布，不要一次替换所有服务。

建议顺序：

1. `batchsvr`
2. `simsvr`
3. `indsvr`
4. `apssvr`
5. `mdsvr`
6. `quantsvr`
7. `gateway`
8. `web`
9. `zookeeper`

`zookeeper` 是注册中心，应该放最后。

## 11. 发布验收

单服务发布后至少检查：

```bash
docker ps --filter name=dc-apssvr
docker logs dc-apssvr --tail 200
```

检查端口：

```bash
bash -c 'exec 3<>/dev/tcp/127.0.0.1/30035'
```

检查业务日志：

```bash
tail -n 100 /data/strategy/log/APSSvr.log
```

检查最近错误：

```bash
docker logs dc-apssvr --since 5m 2>&1 | grep -Ei 'ERROR|Exception|timeout|permission denied' || true
```

如果是 `gateway`，还要验证 `/web/`、API、MCP。

如果是 `QuantSvr`、`INDSvr`、`SIMSvr`、`BatchSvr`，还要验证 ClickHouse 中的关键表。

## 12. 回滚

回滚优先按镜像 tag：

1. 找到上一个稳定 tag。
2. 修改 `.env.prod` 对应变量。
3. 拉取旧镜像。
4. 重启单服务。

示例：

```bash
cd /data/strategy/dc-quant-deploy
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull apssvr
./restart-service.sh apssvr
```

如果已经实现 `deploy-image-tag.sh`，则可以：

```bash
./deploy-image-tag.sh apssvr v0.0.1-test.3
```

回滚不删除 ClickHouse 数据。

## 13. 给 Codex 的发布指令模板

### 13.1 只开发并提交

```text
请在当前仓库实现：<需求>

完成后：
1. 运行必要测试。
2. 提交 commit。
3. 不要打 tag。
4. 最后告诉我 commit hash、测试结果和风险。
```

### 13.2 开发、提交、推送分支

```text
请在当前分支实现：<需求>

完成后：
1. 运行必要测试。
2. 提交 commit。
3. push 当前分支到 origin。
4. 不要打 tag。
```

### 13.3 发布 tag

```text
请发布 <service> 的 <tag>。

要求：
1. 确认当前分支是 main。
2. 确认 git status 干净。
3. 确认最近 commit 是要发布的版本。
4. 创建 annotated tag。
5. push tag。
6. 不要修改生产服务器。
```

### 13.4 部署服务器

```text
请把生产服务器上的 <service> 切到镜像 tag <tag>。

要求：
1. 先确认 GHCR 镜像可以 pull。
2. 更新 .env.prod 对应 tag。
3. 只重启这个服务，不影响其它服务。
4. 检查容器、端口、日志。
5. 如果失败，恢复旧 tag。
```

## 14. 当前还需要补齐的自动化

当前 `dc-quant-deploy` 已具备：

- `deploy.sh`
- `validate.sh`
- `restart-service.sh`
- `deploy-service.sh`
- `rollback-service.sh`
- `compose.yaml`

如果要做到“tag 构建完成后服务器完全自动部署”，还需要补齐：

- `deploy-image-tag.sh <service> <tag>`：更新 `.env.prod` 并部署单服务。
- `auto-deploy-pending-release.sh`：服务器定时检测待发布 tag。
- 发布请求目录或发布 manifest，例如 `releases/prod/*.tag`。
- 每个服务仓库的 GitHub Actions 镜像构建 workflow。
- 部署成功/失败日志和通知机制。

建议先从单服务 `apssvr` 或 `batchsvr` 打通，再推广到其它服务。
