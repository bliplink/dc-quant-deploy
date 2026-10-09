# API Docs 正式镜像发布与主站入口回归

OpenTradingCore API Docs 的**唯一发布仓库**是 [bliplink/opentradingcore-api-docs](https://github.com/bliplink/opentradingcore-api-docs)，分支固定 `saas-crypto`。不要修改 `dc-quant-deploy/docs/public-api` 的历史快照当成正式发布。

## 发布链

1. 在独立仓库修改中英文文档、OpenAPI YAML 和示例；合并或推送到 `saas-crypto`。
2. GitHub Actions **Publish OpenTradingCore API Docs** 运行双语一致性、schema、示例离线测试，并发布 `linux/amd64` / `linux/arm64` GHCR Docker 镜像。
3. Actions 成功后，根据**提交 SHA 的完整镜像标签**发布，禁止使用无法追溯的本地镜像或盲目使用浮动 `latest`。
4. Mac mini 的 Docker Compose `api-docs` 服务镜像来自：
   `ghcr.io/bliplink/opentradingcore-api-docs-web:sha-<FULL_COMMIT_SHA>`。
5. 备份部署环境文件，更新 `API_DOCS_TAG`，再执行（路径以现有部署环境为准）：

   ```sh
   docker compose -p dc-saas --env-file <SAAS_ENV_FILE> -f <DEPLOY_COMPOSE_YAML> \
     pull api-docs
   docker compose -p dc-saas --env-file <SAAS_ENV_FILE> -f <DEPLOY_COMPOSE_YAML> \
     up -d --no-deps --no-build api-docs
   ```

6. 验收 `dc-saas-api-docs` 为 `healthy`、无新增重启，检查 `/healthz`、`/en/`、`/zh/`、API Key 文档、Broker 指南、逐接口字段参考与 Python 示例返回 HTTP 200。
7. 主站 `opentradingcore.com` PC、手机导航的 API / View API Docs 均应链接到 `https://api.opentradingcore.com/`；该入口由 API Docs 的 Nginx 重定向到英文首页，并非主站复制的一份旧文档。**更新 API Docs 镜像本身不需要重发主站镜像。**
8. 使用 `tests/public-api-docs-entry-smoke.js` 执行无凭据的 Playwright 入口回归。失败时恢复备份的 `API_DOCS_TAG`，重新启动单独 `api-docs` 服务。

## 2026-10-09 部署基线

- API Docs：`sha-0536afb22a2c8e2e349f31357111eebf63511331`（已按正式 GHCR 镜像发布）
- LoginSvr：`sha-6913193`（Broker 未指定 permissions 时默认只读）
- 本站点不托管交易 GW，请勿把 `api.opentradingcore.com` 误写成交易签名登录 `POST /api` 地址。

## 真实接口验收

文档镜像构建、页面 HTTP 200 或模拟签名测试，**不等同于**真实 Trader/Broker E2E 已通过。完整验收需要隔离测试租户、有效的受保护测试凭据、下单与成交权威查询；测试完成后撤销临时 Key，不触碰当前正在工作的 Robot Key。
