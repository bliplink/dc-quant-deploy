# 2026-10-20 单页 Python API Docs 公共参考发布验收

## 已完成

API Docs 仓库（`bliplink/opentradingcore-api-docs`）分支 `codex/sdk-python-common-reference-20261020`，提交 `d969321`（`[skip ci]`）：在现有仅 Python 方法的单页面中，新增中英文 `Rate limits/限流规则`、`Error codes/错误码`、`Common enums/公共枚举`、`Parameters and conventions/参数约定`。内容依据运行 Gateway 的 `OpenApiRateLimitSecurityCheck` 和 `OpenApiResponseSanitizer`、当前 Python SDK 0.1.6 参数校验实现审阅。没有公开 HTTP、WebSocket 路由和租户管理方法。

本地 `scripts/prepare-public-api-docs-context.sh` 阶段把两种语言的公共章节加入发行构建；Python SDK 文档生成测试 3/3 通过，MkDocs 英文/中文 `--strict` 均通过，四种目录锚点在两种语言 HTML 均存在。

**Demo 部署：** 以现有 `local/dc-saas-api-docs:python-only-016-20261020` 为基础，叠加新生成 `site/en` 和 `site/zh`，构建 `local/dc-saas-api-docs:python-common-reference-20261020`。仅更新 Compose 服务 `api-docs`，部署覆盖文件 `config/api-docs-python-common-reference-20261020.yaml`；没有重启 Order/Trade/MD。容器 `dc-saas-api-docs-1` 运行 `healthy`，`/healthz` 返回 `200`；保留 0.1.6 SDK wheel（24598 字节）。

**公网实测：** `https://api.opentradingcore.com/en/` 和 `https://api.opentradingcore.com/zh/` 均返回 HTTP `200`，HTML 实际包含 `rate-limits`、`error-codes`、`common-enums`、`parameters` 四个锚点。主站动态选择语言的原导航逻辑没有更改。

## 仍未完成，不可宣称通过

- 公布的 wheel 仍为 **0.1.6**；先前查出的 `positions()` 缺少服务端必需 `securityid`，在 `codex/python-realtime-methods-sdk-017-20261020` 候选版改为 `positions(symbol)`，但尚未正式发布。
- 私有实时接收：此次新租户 `JGXHQ6` 的 Broker API Key 和两个 Trader API Key 均签名登录成功、成功入金、MD 标记价有效，但 `AccountStreams` **Maker** 的 WebSocket TOKEN 握手在延长至 **30 秒**后仍超时，发生在下单之前。所有临时 API Keys 已回收。Gateway 同时段日志有 `ReadProtoProcess` 与 `NotifyProcess` 队列 `critical[size:101]` 警告；这只能视为待核查相关性，尚不能认定最终根因。公开行情已通过不等于私有订阅可用。
- 新 Key 异步就绪偶发 `7000 API_NOT_EXIST`，测试仅对未就绪的**签名登录**增加有界重试，明确不重试不确定的写操作。
- `KMQ5U3` 曾发生 Order 接单结果成功，但 Projection 没有该记录的异常，订单权威一致性仍未闭环。

后续聚焦网关队列堆积/认证连接回复路径、服务端 Login TOKEN 会话变更及订单/Projection 的确认边界。当前未执行 HA SIGKILL 或 200 租户压力测试，也未使用 GitHub Actions。
